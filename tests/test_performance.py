"""Performance-related behaviour.

- Relations dry-runs use in-memory entries (no disk re-read), and the
  RDA cipher uses a cached keystream with a big-int XOR.
- Snapshot policy: the pre-flash snapshot is taken from the old target
  bytes in memory, skipped when that md5 is already stored, and the
  archive is written once per flash.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")
sys.path.insert(0, "..")

T = tempfile.mkdtemp()
os.environ["ANN0140_HOME"] = T

from synthetic_rda import make_synthetic_rda  # noqa: E402
from annoedit.appsettings import Settings  # noqa: E402
from annoedit.backup import atomic_write_bytes  # noqa: E402
from annoedit.rda import _decrypt, read_rda  # noqa: E402
from annoedit.session import Session, SessionError  # noqa: E402

GAME = make_synthetic_rda(os.path.join(T, "game", "data1.rda"))
PRESETS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "annoedit", "presets")


def mk():
    return Session(backup_root=os.path.join(T, "b"),
                   exports_root=os.path.join(T, "e"),
                   settings=Settings(os.path.join(T, "c")),
                   persona_dirs=(PRESETS,))


class F16Tests(unittest.TestCase):
    def _leif(self, s):
        return [p for ps in s.proj.profiles.values()
                for p in ps if "Leif" in p.name][0]

    def test_relations_dry_run_does_not_re_read_the_archive(self):
        s = mk()
        s.open(GAME)
        import annoedit.rda as rda_mod
        reads = {"n": 0}
        orig = rda_mod.read_rda

        def counted(path, strict=False):
            reads["n"] += 1
            return orig(path, strict)

        rda_mod.read_rda = counted
        try:
            leif = self._leif(s)
            s.set_relations(leif, war=["1645024"])       # dry-run runs
            s.set_mode(leif, "The Admiral")             # persona pick too
        finally:
            rda_mod.read_rda = orig
        self.assertEqual(reads["n"], 0,
                         "a relations click/persona pick must not"
                         "re-read the archive from disk")
        s.close()

    def test_relations_dry_run_includes_pending_dials(self):
        # a pending dial insert + a relations edit must BOTH survive the
        # same dry-run (insert/dial interactions exercised)
        s = mk()
        s.open(GAME)
        leif = self._leif(s)
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        s.set_relations(leif, war=["1645024"])
        self.assertEqual(s.rels[leif.guid]["War"], ["1645024"])
        s.close()

    def test_decrypt_equivalence_random_buffers(self):
        import random
        import struct
        random.seed(7)
        for size in (0, 1, 2, 3, 17, 100, 999, 540, 4096, 65537):
            b = bytes(random.randrange(256) for _ in range(size))

            def old(buf, seed):
                words = struct.unpack("<%dH" % (len(buf) // 2),
                                      buf[:len(buf) // 2 * 2])
                num = seed
                out = []
                for w in words:
                    num = (num * 214013 + 2531011) & 0xFFFFFFFF
                    out.append(w ^ ((num >> 16) & 0x7FFF))
                res = struct.pack("<%dH" % len(out), *out)
                if len(buf) % 2:
                    res += buf[-1:]
                return res
            self.assertEqual(_decrypt(b, 0xA2C2A), old(b, 0xA2C2A), size)
        # seed 0 still refused
        with self.assertRaises(ValueError):
            _decrypt(b"x", 0)

    def test_read_rda_roundtrip_survives_cipher(self):
        entries = read_rda(GAME, strict=True)
        out = os.path.join(T, "rt.rda")
        from annoedit.rda import write_rda
        write_rda(entries, out)
        back = read_rda(out, strict=True)
        self.assertEqual(set(back), set(entries))
        for k in entries:
            self.assertEqual(back[k][0], entries[k][0])


class F20Tests(unittest.TestCase):
    def _leif(self, s):
        return [p for ps in s.proj.profiles.values()
                for p in ps if "Leif" in p.name][0]

    def test_failed_build_takes_no_snapshot(self):
        # force the build to fail (a bad pending dial) -> no pre-flash
        # snapshot, and the target is untouched
        s = mk()
        s.open(GAME)
        leif = self._leif(s)
        target = os.path.join(T, "live_f20a.rda")
        atomic_write_bytes(target, open(GAME, "rb").read())
        before = open(target, "rb").read()
        s.settings.set("live_path", target)
        # queue a valid edit then break the build: monkeypatch _build
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        orig = s._build

        def broken(out_path, snapshot=None, base_entries=None,
                   roster=None, expected_plan=None):
            raise SessionError("boom")

        s._build = broken
        try:
            with self.assertRaises(SessionError):
                s.flash(target)
        finally:
            s._build = orig
        snaps = [n for n in os.listdir(s.store.root)
                 if n.startswith("pre-flash-")]
        self.assertEqual(snaps, [])
        self.assertEqual(open(target, "rb").read(), before)
        s.close()

    def test_skip_when_target_already_preserved(self):
        # flashing over a target whose bytes are already the store's
        # vanilla copy -> NO new pre-flash snapshot (nothing to keep)
        s = mk()
        s.open(GAME)
        leif = self._leif(s)
        target = os.path.join(T, "live_f20b.rda")
        atomic_write_bytes(target, open(GAME, "rb").read())
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        s.flash(target)
        snaps = []
        pf = os.path.join(s.store.root, "pre-flash")
        for _dp, _dn, fns in os.walk(pf):
            snaps += [n for n in fns
                      if n.startswith("pre-flash-")]
        self.assertEqual(snaps, [],
                         "old target == the first-open/vanilla copy "
                         "already in the store — snapshot must be skipped")
        s.close()

    def test_snapshot_taken_after_success_and_names_old_target(self):
        s = mk()
        s.open(GAME)
        leif = self._leif(s)
        # first flash in place -> old target == first-open copy -> skipped
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        rep1 = s.flash()
        # second flash: old target = rep1's modded archive -> kept
        s.set_dial(leif, "Build/BuildingSpeed", "160")
        rep2 = s.flash()
        sdir = s.store.snap_dir(GAME)   # in-place flash target = GAME
        snaps = [n for n in os.listdir(sdir)
                 if n.startswith("pre-flash-")]
        self.assertEqual(len(snaps), 1)
        self.assertTrue(snaps[0].startswith(f"pre-flash-{rep1['md5']}"))
        # snapshot bytes == the OLD target exactly (md5 of the raw RDA
        # container, before the second flash replaced it)
        import hashlib
        with open(os.path.join(sdir, snaps[0]), "rb") as f:
            data = f.read()
        self.assertEqual(hashlib.md5(data).hexdigest(), rep1["md5"])
        self.assertNotEqual(rep2["md5"], rep1["md5"])
        s.close()

    def test_flash_writes_the_archive_once(self):
        # write_rda builds directly into the target dir; no second full
        # copy of the archive may be written to backups/ (no .flashbuild
        # leftovers in the store, no pre-flash tmp files)
        s = mk()
        s.open(GAME)
        leif = self._leif(s)
        target = os.path.join(T, "live_f20c.rda")
        atomic_write_bytes(target, open(GAME, "rb").read())
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        s.flash(target)
        leftovers = [n for n in os.listdir(s.store.root)
                     if n.startswith(".flashbuild") or n.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertEqual(os.path.basename(s.source_path),
                         os.path.basename(GAME))
        s.close()

    def test_flash_preserves_target_mode(self):
        s = mk()
        s.open(GAME)
        leif = self._leif(s)
        target = os.path.join(T, "live_f20d.rda")
        atomic_write_bytes(target, open(GAME, "rb").read())
        os.chmod(target, 0o644)
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        s.flash(target)
        self.assertEqual(os.stat(target).st_mode & 0o7777, 0o644,
                         "regression: the flash must keep the live"
                         "file's mode")
        s.close()


if __name__ == "__main__":
    unittest.main()
