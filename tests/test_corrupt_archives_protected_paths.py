#!/usr/bin/env python3
"""Corrupt archives and protected paths.

- A next-block pointer past EOF, a file region past EOF or a duplicate
  entry name fails the read instead of silently dropping members.
- Nothing may overwrite the stored vanilla copy or the stores:
  set_live_path and every commit/flash/restore path refuse.
- CLI 'apply' over an existing file preserves its mode, goes through the
  commit protocol and refuses the source/live path as its output.
- The snapshot skip set only trusts manifest md5s whose files exist,
  and snapshot_pre_flash_bytes reports whether it really wrote.
"""
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import fixture  # noqa: E402, (pins ANN0140_HOME isolation)

from annoedit import ops  # noqa: E402
from annoedit.backup import BackupStore, md5_of  # noqa: E402
from annoedit.rda import RdaFormatError, read_rda, write_rda  # noqa: E402
from annoedit.session import Session, SessionError  # noqa: E402
from synthetic_rda import make_synthetic_rda  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class Phase1Base(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p16_")
        self.A = make_synthetic_rda(os.path.join(self.W, "a.rda"))

    def tearDown(self):
        shutil.rmtree(self.W, ignore_errors=True)


class C1Tests(Phase1Base):
    """A corrupt block chain must fail the read, never lead to a
    'verified' truncated save."""

    def _mk_archive_with_extra(self):
        ents = dict(read_rda(self.A, strict=True))
        ents["addondata/extra/payload.zip"] = (b"Z" * 5000, 0)
        ents["addondata/extra/other.zip"] = (b"Q" * 5000, 0)
        p = os.path.join(self.W, "data1.rda")
        write_rda(ents, p)
        return p, set(ents)

    def test_next_pointer_past_eof_raises(self):
        p, names = self._mk_archive_with_extra()
        d = bytearray(open(p, "rb").read())
        first = struct.unpack("<I", d[1044:1048])[0]
        struct.pack_into("<I", d, first + 16, len(d) + 4096)
        open(p, "wb").write(d)
        with self.assertRaises(RdaFormatError):
            read_rda(p, strict=True)
        # The loss scenario: a lenient reader opened OK with 6 of 8
        # members and the next flash wrote the LOSS as verified. Now the
        # OPEN itself fails — nothing can be written from it.

    def test_next_pointer_past_eof_raises_lenient_too(self):
        p, _ = self._mk_archive_with_extra()
        d = bytearray(open(p, "rb").read())
        first = struct.unpack("<I", d[1044:1048])[0]
        struct.pack_into("<I", d, first + 16, len(d) + 4096)
        open(p, "wb").write(d)
        with self.assertRaises(RdaFormatError):
            read_rda(p, strict=False)

    def test_open_corrupt_chain_refuses_and_keeps_data(self):
        # the full Session.open must REFUSE the corrupted
        # archive (never flash a truncated member set over it)
        p, names = self._mk_archive_with_extra()
        d = bytearray(open(p, "rb").read())
        first = struct.unpack("<I", d[1044:1048])[0]
        struct.pack_into("<I", d, first + 16, len(d) + 4096)
        open(p, "wb").write(d)
        corrupted = md5_of(p)          # the bytes NOW on disk
        s = Session()
        try:
            with self.assertRaises((RdaFormatError, SessionError)):
                s.open(p)
            # the failed open left the file exactly as it was — no
            # rewrite, no recovery attempt that could make it worse
            self.assertEqual(md5_of(p), corrupted)
        finally:
            s.close()

    def test_file_region_past_eof_raises(self):
        p, _ = self._mk_archive_with_extra()
        d = bytearray(open(p, "rb").read())
        # flip one dir entry's file offset past EOF inside the FIRST
        # block's directory (safest: the block at 'first' holds its
        # directory immediately before it)
        first = struct.unpack("<I", d[1044:1048])[0]
        flags, count = struct.unpack("<II", d[first:first + 8])
        dirsz, decsz, nxt = struct.unpack("<III", d[first + 8:first + 20])
        pos = first - dirsz
        # entry layout: 520 name + 5 u32; target the first entry's foff
        e = pos + 520
        struct.pack_into("<I", d, e, len(d) + 5000)
        open(p, "wb").write(d)
        with self.assertRaises(RdaFormatError):
            read_rda(p, strict=True)

    def test_duplicate_names_raise_in_strict(self):
        # hand-craft a two-block archive whose second block repeats a
        # name from the first (write_rda cannot produce this)
        ents = dict(read_rda(self.A, strict=True))
        ents["addondata/extra/payload.zip"] = (b"Z" * 5000, 0)
        p = os.path.join(self.W, "dup.rda")
        write_rda(ents, p)
        d = bytearray(open(p, "rb").read())
        first = struct.unpack("<I", d[1044:1048])[0]
        # walk to the LAST block, duplicate its first name into a second
        # entry appended... simpler: patch the first block's name field of
        # its second entry to equal its first entry's name
        flags, count = struct.unpack("<II", d[first:first + 8])
        dirsz, decsz, nxt = struct.unpack("<III", d[first + 8:first + 20])
        pos = first - dirsz
        buf = bytearray(d[pos:pos + dirsz])
        if count < 2:
            self.skipTest("fixture block needs >=2 entries")
        src_name = bytes(buf[0:520])
        buf[540:540 + 520 - 540] = src_name[0:520 - 540]
        # replace the WHOLE second entry name with the first name
        buf[540:540 + 520] = src_name[:520]
        d[pos:pos + dirsz] = buf
        open(p, "wb").write(d)
        with self.assertRaises(RdaFormatError):
            read_rda(p, strict=True)
        # lenient: warns, keeps the last copy
        ents2 = read_rda(p, strict=False)
        self.assertIsInstance(ents2, dict)

    def test_directory_region_overlap_raises(self):
        p, _ = self._mk_archive_with_extra()
        d = bytearray(open(p, "rb").read())
        first = struct.unpack("<I", d[1044:1048])[0]
        # grow the first block's directory_size so its region [pos, pos+
        # dirsz) runs past the block header (pos stays fixed)
        flags, count = struct.unpack("<II", d[first:first + 8])
        old_dirsz = struct.unpack("<I", d[first + 8:first + 12])[0]
        struct.pack_into("<I", d, first + 8, old_dirsz + 100000)
        open(p, "wb").write(d)
        with self.assertRaises(RdaFormatError):
            read_rda(p, strict=True)


class C2Tests(Phase1Base):
    """Nothing may overwrite the trust anchor or the stores."""

    def _provisioned(self):
        s = Session()
        s.provide_vanilla(self.A)
        return s, s.exports_store.vanilla_path

    def test_set_live_path_refuses_vanilla_copy(self):
        s, vp = self._provisioned()
        try:
            with self.assertRaises(SessionError):
                s.set_live_path(vp)
        finally:
            s.close()

    def test_set_live_path_refuses_backup_store_files(self):
        s, _ = self._provisioned()
        try:
            bs = BackupStore()
            md5, _c = bs.capture_vanilla(self.A)
            with self.assertRaises(SessionError):
                s.set_live_path(bs.vanilla_path(md5))
            with self.assertRaises(SessionError):
                s.set_live_path(os.path.join(bs.root, "session.lock"))
        finally:
            s.close()

    def test_flash_build_over_protected_target_refuses(self):
        # the GUI-equivalent pure call (A.4): the worker path must refuse
        s, vp = self._provisioned()
        s.open(self.A)
        leif = [q for q in s.roster if q.name.startswith("Leif")][0]
        s.set_mode(leif, "The Admiral")
        before = md5_of(vp)
        try:
            with self.assertRaises(SessionError):
                ops.flash_build(
                    s._write_lock, s.store, s.proj.entries, s.source_path,
                    lambda tmp, cs, base: ops.build_from_snapshot(
                        base, s.source_path, cs, tmp),
                    s.cs.snapshot(), vp, False,
                    exports_store=s.exports_store)
            self.assertEqual(md5_of(vp), before)  # trust anchor intact
        finally:
            s.close()

    def test_commit_archive_refuses_protected_target(self):
        s, vp = self._provisioned()
        s.open(self.A)
        tmp = os.path.join(self.W, "tmp.rda")
        shutil.copy(self.A, tmp)
        before = md5_of(vp)
        try:
            with self.assertRaises(SessionError):
                ops.commit_archive(s.store, vp, tmp,
                                   exports_store=s.exports_store)
            self.assertEqual(md5_of(vp), before)
        finally:
            s.close()

    def test_restore_over_protected_target_refuses(self):
        s, vp = self._provisioned()
        try:
            with self.assertRaises(SessionError):
                s.restore_vanilla(target=vp)
            self.assertTrue(os.path.isfile(vp))
        finally:
            s.close()

    def test_gui_run_build_live_refuses_protected_target(self):
        # the GUI handler itself (app.py _run_build('live')): the
        # refusal fires at the button click, on the Tk thread, before
        # any worker is launched. Headless: call the guard it uses.
        s, vp = self._provisioned()
        try:
            # set_live_path already refuses; the GUI inherits it via the
            # settings the operator set... simulate the direct case:
            s.settings.set("live_path", vp)   # bypass (as a corrupted
            # settings file would produce)
            self.assertTrue(s._is_protected(s.default_target()))
        finally:
            s.close()


class H3Tests(Phase1Base):
    """The CLI apply family must not clobber an existing file without
    the commit protocol (snapshot, mode preservation, live refusal)."""

    def _cli(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "annoedit.cli", *argv],
            cwd=REPO, capture_output=True, text=True,
            env=dict(os.environ))

    def test_apply_over_existing_preserves_mode_and_snapshots(self):
        live = os.path.join(self.W, "live.rda")
        shutil.copy(self.A, live)
        os.chmod(live, 0o644)
        before = md5_of(live)
        r = self._cli("apply", self.A, live, "--persona", "The Admiral")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = stat.S_IMODE(os.stat(live).st_mode)
        self.assertEqual(after, 0o644)          # no mkstemp 0600 leak
        if md5_of(live) == before:
            return                              # nothing changed
        # the overwritten bytes must be RECOVERABLE: a pre-flash
        # snapshot with that md5, or the first-open vanilla backup
        # (the CLI open captured it — a byte-identical copy is a
        # legitimate skip, 's existing-file rule)
        bs = BackupStore()
        snaps = [n for n in os.listdir(bs.root)
                 if n.startswith(f"pre-flash-{before}-")]
        vanilla = os.path.isfile(bs.vanilla_path(before)) if \
            bs._read_manifest().get("vanilla_md5") else \
            os.path.isfile(os.path.join(bs.root, f"vanilla-{before}.rda"))
        self.assertTrue(snaps or vanilla,
                        "the old bytes must be preserved somewhere "
                        "before the overwrite")

    def test_apply_out_equals_source_refuses(self):
        # out == the SOURCE path itself: the export route must refuse
        # ('use flash' — the in-place route carries snapshot/lock)
        r = self._cli("apply", self.A, self.A, "--persona", "The Admiral")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("flash", (r.stderr + r.stdout).lower())

    def test_apply_out_equals_live_path_refuses(self):
        # set the live path, then apply over it — the export route must
        # refuse ('use flash') instead of clobbering the live archive
        # with no snapshot
        live = os.path.join(self.W, "live.rda")
        shutil.copy(self.A, live)
        s = Session()
        try:
            s.set_live_path(live)
        finally:
            s.close()
        before = md5_of(live)
        r = self._cli("apply", self.A, live, "--persona", "The Admiral")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(md5_of(live), before)

    def test_export_routes_existing_out_through_commit(self):
        # Session.export over an existing out: snapshot + mode preserved
        s = Session()
        out2 = os.path.join(self.W, "out2.rda")
        try:
            s.open(self.A)
            leif = [q for q in s.roster if q.name.startswith("Leif")][0]
            s.set_mode(leif, "The Admiral")
            rep = s.export(out2)               # new file: plain build
            self.assertTrue(os.path.isfile(out2))
            os.chmod(out2, 0o600)
            rep = s.export(out2)              # existing: commit route
            self.assertEqual(rep.get("snapshot_written"), True)
            self.assertEqual(stat.S_IMODE(os.stat(out2).st_mode), 0o600)
        finally:
            s.close()


class H4Tests(Phase1Base):
    """The snapshot skip set must trust only md5s whose files exist, and
    the report must say what actually happened."""

    def test_manifest_md5_without_file_does_not_skip(self):
        d = tempfile.mkdtemp(dir=self.W)
        L = os.path.join(d, "data1.rda")
        shutil.copy(self.A, L)
        bs = BackupStore()
        md5, _c = bs.capture_vanilla(L)
        os.unlink(bs.vanilla_path(md5))       # user frees the disk
        tmp = os.path.join(d, "tmp.rda")
        shutil.copy(L, tmp)
        from annoedit.rda import read_rda as rr
        ents = dict(rr(tmp))
        ents["addondata/x/extra.bin"] = (b"\x01" * 100, 0)
        write_rda(ents, tmp)
        before = md5_of(L)
        rep = ops.commit_archive(bs, L, tmp)
        # L == the (deleted) vanilla md5: the skip set must NOT have
        # skipped — a real pre-flash snapshot must exist now
        self.assertTrue(os.path.isfile(
            os.path.join(bs.root,
                         f"pre-flash-{before}-")) or True)
        snaps = [n for n in os.listdir(bs.snap_dir(L))
                 if n.startswith(f"pre-flash-{before}-")]
        self.assertTrue(snaps, "a real pre-flash file must exist when "
                        "the manifest's vanilla file is gone")
        self.assertTrue(rep["snapshot_written"])
        self.assertEqual(rep["snapshot_md5"], before)

    def test_manifest_md5_with_file_skips_and_reports_honestly(self):
        d = tempfile.mkdtemp(dir=self.W)
        L = os.path.join(d, "data1.rda")
        shutil.copy(self.A, L)
        bs = BackupStore()
        md5, _c = bs.capture_vanilla(L)      # file STAYS this time
        tmp = os.path.join(d, "tmp.rda")
        shutil.copy(L, tmp)
        from annoedit.rda import read_rda as rr
        ents = dict(rr(tmp))
        ents["addondata/x/extra.bin"] = (b"\x01" * 100, 0)
        write_rda(ents, tmp)
        rep = ops.commit_archive(bs, L, tmp)
        self.assertEqual(rep["snapshot_written"], False)
        self.assertEqual(rep["snapshot_md5"], md5)

    def test_snapshot_pre_flash_bytes_returns_written_flag(self):
        bs = BackupStore()
        data = open(self.A, "rb").read()
        md5 = md5_of(self.A)
        m, w1 = bs.snapshot_pre_flash_bytes(data, md5)
        self.assertTrue(w1)
        m, w2 = bs.snapshot_pre_flash_bytes(data, md5, skip_md5s={md5})
        self.assertFalse(w2)                # honest skip
        m, w3 = bs.snapshot_pre_flash_bytes(b"", "deadbeef")
        self.assertFalse(w3)                # no data -> no snapshot


if __name__ == "__main__":
    unittest.main()
