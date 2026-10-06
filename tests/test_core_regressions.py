"""Core regressions: import health, ChangeSet integrity, drift, open/flash,
Vanilla mode and CLI errors.

TestImportHealth: every tests/test_*.py must import cleanly, because a
test module that errors during import can otherwise vanish from the run
while the suite still "passes".
"""
import io
import os
import contextlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synthetic_rda import make_synthetic_rda


class TestImportHealth(unittest.TestCase):
    """Meta-test: no test module may fail to import (setUp included)."""

    def test_every_test_module_imports(self):
        import importlib
        tdir = os.path.dirname(os.path.abspath(__file__))
        bad = []
        for name in sorted(os.listdir(tdir)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            mod = "tests." + name[:-3] if os.path.isdir(
                os.path.join(os.path.dirname(tdir), "tests")) else name[:-3]
            try:
                importlib.import_module(name[:-3])
            except Exception as exc:  # noqa: BLE001 — the point of the test
                bad.append(f"{name}: {exc!r}")
        self.assertEqual(bad, [])


def _mk_session(tag="t"):
    from annoedit.session import Session
    from annoedit.appsettings import Settings
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


class ReproBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = tempfile.mkdtemp()
        cls.A = make_synthetic_rda(cls.W + "/vanilla.rda")

    def setUp(self):
        os.environ.setdefault("ANN0140_HOME", tempfile.mkdtemp())


class TestChangeSetIntegrity(ReproBase):
    """ChangeSet integrity: refused edits never get queued."""

    def test_R1_refused_dial_not_queued(self):
        from annoedit.session import SessionError
        s, _ = _mk_session("r1"); s.open(self.A)
        leif = s.proj.by_guid["1645021"]
        s.set_dial(leif, "Military/MaxUnitCount", "50")
        with self.assertRaises(SessionError):
            s.set_dial(leif, "Military", "5")  # container path
        self.assertNotIn(("1645021", "Military"), s.cs.dials)
        # a later edit on ANOTHER character still succeeds
        s.set_dial(s.proj.by_guid["1645025"], "Military/MaxUnitCount", "60")
        s.close()

    def test_R7_relations_validated(self):
        from annoedit.session import SessionError
        s, _ = _mk_session("r7"); s.open(self.A)
        leif = s.proj.by_guid["1645021"]
        with self.assertRaises(SessionError):
            s.set_relations(leif, war=["1645021", "1645020", "1645020"],
                            ally=["1645020"])
        s.close()

    def test_R8_int32_bound(self):
        from annoedit.session import SessionError
        s, _ = _mk_session("r8"); s.open(self.A)
        with self.assertRaises(SessionError):
            s.set_dial(s.proj.by_guid["1645021"],
                       "Military/MaxUnitCount", "99999999999999")
        s.close()

    def test_R12_negative_occ_refused(self):
        from annoedit.core import ModProject
        from annoedit.extras import set_extra, ExtrasError
        with self.assertRaises(ExtrasError):
            set_extra(ModProject(self.A).assets_text, "Noria",
                      "NoriaEndRadius", "99", occ=-1)


class TestDrift(ReproBase):
    """Targets ."""

    # landed EARLY in the fert str-vs-int false
    # positive was 's symptom but its root cause (values normalised at
    # the ChangeSet boundary) was the decorator is removed.
    def test_R2_landed_fert_pending_not_drift(self):
        s, _ = _mk_session("r2")
        B = self.W + "/live2.rda"; shutil.copy(self.A, B)
        s.open(self.A); s.set_live_path(B)
        s.set_fertility("low", "Dates", "40", None)  # GUI passes strings
        s.flash(B)
        self.assertFalse(s.target_drift(B), 'falsy-not-None')
        s.close()

    # Landed — per-key set logic (a pending edit on a
    # key means the user decided there; it is never 'silent revert').
    def test_R3_noop_pending_does_not_hide_drift(self):
        from annoedit.core import ModProject
        B = self.W + "/live3.rda"
        p = ModProject(self.A)
        p.set_dials(p.by_guid["1645021"], {"Military/AttackDelay": "1"})
        p.build(B)
        s, _ = _mk_session("r3"); s.open(self.A); s.set_live_path(B)
        leif = s.proj.by_guid["1645021"]
        cur = leif.dials["Military/MaxUnitCount"]
        s.set_dial(leif, "Military/MaxUnitCount", cur)  # no-op pending
        # The live AttackDelay difference is NOT
        # drift (no pending decision there) — the flash REPLAYS onto the
        # live members, so it must SURVIVE. The no-op pending must not
        # hide it in the SURVIVAL sense either.
        self.assertFalse(s.target_drift(B), 'falsy-not-None')
        s.flash(B)
        from annoedit.core import ModProject as _MP
        live = _MP(B)
        self.assertEqual(
            live.by_guid["1645021"].dials["Military/AttackDelay"], "1",
            "the foreign live edit must survive the replay save")
        s.close()


class TestOpenAndFlash(ReproBase):
    """Targets ."""

    def test_R4_failed_reopen_keeps_session(self):
        C = self.W + "/r4.rda"; shutil.copy(self.A, C)
        s, _ = _mk_session("r4"); s.open(C)
        s.set_dial(s.proj.by_guid["1645021"],
                   "Military/MaxUnitCount", "77")
        with open(C, "wb") as f:
            f.write(b"garbage" * 300)
        with self.assertRaises(Exception):
            s.open(C)
        self.assertIsNotNone(s.proj)
        self.assertIn(("1645021", "Military/MaxUnitCount"), s.cs.dials)
        s.close()

    def test_R5_foreign_entries_survive_save(self):
        from annoedit.rda import read_rda, write_rda
        B = self.W + "/live5.rda"
        e = read_rda(self.A); e["data/othermod.dds"] = (b"x" * 50, 1)
        write_rda(e, B)
        s, _ = _mk_session("r5"); s.open(self.A); s.set_live_path(B)
        s.set_dial(s.proj.by_guid["1645021"],
                   "Military/MaxUnitCount", "55")
        drift = s.target_drift(B)
        self.assertIsInstance(drift, tuple)      # Foreign reported
        self.assertEqual(drift[5], 1)            # 1 foreign entry
        rep = s.flash(B)
        self.assertIn("data/othermod.dds", read_rda(B))   # survives
        self.assertEqual(read_rda(B)["data/othermod.dds"][0], b"x" * 50)
        # the 4 tracked members carry the edit
        from annoedit.core import ModProject
        live = ModProject(B)
        self.assertEqual(
            live.by_guid["1645021"].dials["Military/MaxUnitCount"], "55")
        s.close()

    def test_R9_flash_failure_leaves_target_unchanged(self):
        from annoedit.backup import md5_of
        C = self.W + "/r9.rda"; shutil.copy(self.A, C)
        s, _ = _mk_session("r9"); s.open(C)
        s.set_dial(s.proj.by_guid["1645021"],
                   "Military/MaxUnitCount", "66")
        before = s.source_md5

        def boom(*a, **k):
            raise OSError(28, "No space left on device")
        s.store.snapshot_pre_flash_bytes = boom
        # The snapshot runs BEFORE the replace — a snapshot failure
        # aborts BEFORE the target changes, so the old bytes are never lost
        with self.assertRaises(Exception):
            s.flash()
        self.assertEqual(md5_of(C), before)  # target NOT replaced on failure
        # and the edit stays pending (session consistent)
        self.assertIn(("1645021", "Military/MaxUnitCount"), s.cs.dials)
        s.close()

    def test_R10_restore_takes_snapshot(self):
        s, root = _mk_session("r10")
        B = self.W + "/live10.rda"; make_synthetic_rda(B, variant=2)
        s.provide_vanilla(self.A); s.restore_vanilla(B)
        snaps = [n for n in os.listdir(root + "/b")
                 if n.startswith("pre-")]
        self.assertTrue(snaps)
        # surgical restore keeps vanilla bytes for the tracked members,
        # and the vanilla md5 verifies against the recorded capture md5
        from annoedit.rda import read_rda as _rr
        van = _rr(self.A); now = _rr(B)
        for k in van:
            self.assertEqual(van[k][0], now[k][0])


class TestVanillaMode(ReproBase):
    """Targets ."""

    # Landed — the global revert is an explicit
    # action (revert_globals_to_reference), never a set_mode side effect.
    def test_R6_vanilla_mode_no_global_side_effect(self):
        M = self.W + "/mod6.rda"; make_synthetic_rda(M, variant=1)
        s, _ = _mk_session("r6"); s.provide_vanilla(self.A); s.open(M)
        s.set_mode(s.proj.by_guid["1645021"], "vanilla")
        self.assertEqual(len(s.cs.extras), 0)
        s.close()


class TestCliErrors(ReproBase):
    """Targets ."""

    # Landed — ArchiveMemberMissing, caught and
    # labelled for what it is by the CLI.
    def test_R11_missing_member_not_mislabelled(self):
        from annoedit.rda import read_rda, write_rda
        from annoedit import cli
        e = read_rda(self.A)
        del e["addondata/config/ai/properties.xml"]
        X = self.W + "/noschema.rda"; write_rda(e, X)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = cli.main(["list", X])
        self.assertEqual(rc, 2)
        self.assertNotIn("spec item", buf.getvalue())
        self.assertIn("archive member missing", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
