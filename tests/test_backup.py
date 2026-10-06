"""Tests for the safety subsystem (annoedit.backup)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from annoedit.backup import (BackupError, BackupStore,
                                     atomic_write_bytes, format_change_report,
                                     md5_of)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_creates_and_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            atomic_write_bytes(p, b"one")
            atomic_write_bytes(p, b"two")
            with open(p, "rb") as f:
                self.assertEqual(f.read(), b"two")
            # no stray temp files left behind
            self.assertEqual([n for n in os.listdir(d) if n.startswith(".flash_")], [])


class BackupStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.game_rda = os.path.join(self._tmp.name, "game", "data1.rda")
        os.makedirs(os.path.dirname(self.game_rda), exist_ok=True)
        with open(self.game_rda, "wb") as f:
            f.write(b"VANILLA-BYTES")
        self.store = BackupStore(root=os.path.join(self._tmp.name, "store"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_capture_vanilla_write_once(self):
        md5, created = self.store.capture_vanilla(self.game_rda)
        self.assertTrue(created)
        self.assertTrue(self.store.has_vanilla)
        # second capture of the SAME file: exists, not overwritten
        md52, created2 = self.store.capture_vanilla(self.game_rda)
        self.assertEqual(md5, md52)
        self.assertFalse(created2)

    def test_vanilla_never_overwritten_even_after_mod(self):
        self.store.capture_vanilla(self.game_rda)
        vmd5 = self.store._read_manifest()["vanilla_md5"]
        # game file gets modded (flash)
        with open(self.game_rda, "wb") as f:
            f.write(b"MODDED-BYTES")
        # re-capture must NOT overwrite the stored vanilla
        self.store.capture_vanilla(self.game_rda)
        m = self.store._read_manifest()
        self.assertEqual(m["vanilla_md5"], vmd5)
        with open(self.store.vanilla_path(vmd5), "rb") as f:
            self.assertEqual(f.read(), b"VANILLA-BYTES")

    def test_restore_vanilla(self):
        self.store.capture_vanilla(self.game_rda)
        with open(self.game_rda, "wb") as f:
            f.write(b"MODDED-BYTES")
        got = self.store.restore_vanilla(self.game_rda)
        with open(self.game_rda, "rb") as f:
            self.assertEqual(f.read(), b"VANILLA-BYTES")
        self.assertEqual(got, md5_of(self.game_rda))

    def test_restore_without_capture_raises(self):
        with self.assertRaises(BackupError):
            self.store.restore_vanilla(self.game_rda)

    def test_restore_keeps_vanilla_backup_intact(self):
        self.store.capture_vanilla(self.game_rda)
        vmd5 = self.store._read_manifest()["vanilla_md5"]
        vpath = self.store.vanilla_path(vmd5)
        before = md5_of(vpath)
        self.store.restore_vanilla(self.game_rda)
        self.assertEqual(md5_of(vpath), before)

    def test_pre_flash_snapshot_pruning(self):
        # Per-target rotation: KEEP_SNAPSHOTS per TARGET pool
        # (pre-flash/<sha1(target)[:12]>/), so another target's saves
        # can never evict this target's snapshots.
        self.store.KEEP_SNAPSHOTS = 3
        for i in range(6):
            with open(self.game_rda, "wb") as f:
                f.write(b"state-%d" % i)
            self.store.snapshot_pre_flash(self.game_rda)
        sdir = self.store.snap_dir(self.game_rda)
        snaps = [n for n in os.listdir(sdir)
                 if n.startswith("pre-flash-") and n.endswith(".rda")]
        self.assertEqual(len(snaps), 3)

    def test_session_lock_exclusive(self):
        with self.store.session_lock():
            store2 = BackupStore(root=self.store.root)
            with self.assertRaises(BackupError):
                with store2.session_lock():
                    pass


class ChangeReportTests(unittest.TestCase):
    def test_report_lists_files_and_dials(self):
        report = {"md5": "abc", "files": 4474, "changed": ["aiprofiles.xml"]}
        applied = {"Willem (1645025)": {"Military/MaxUnitCount": "80"}}
        txt = format_change_report(report, applied)
        self.assertIn("Pre-flash", txt)
        self.assertIn("aiprofiles.xml", txt)
        self.assertIn("MaxUnitCount", txt)
        self.assertIn("-> 80", txt)
        # The claim is DATA-identical, not
        # byte-identical (write_rda repacks every block)
        self.assertIn("exact data", txt)
        self.assertIn("not bit-for-bit identical", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
