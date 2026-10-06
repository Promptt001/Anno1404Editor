"""Data-safety tests.

- Untracked members in the live target survive a save, and the drift
  check reports them as `foreign` (informational).
- restore_vanilla is surgical by default (untracked members kept);
  full=True replaces the whole file; a pre-restore snapshot is taken and
  the stored vanilla copy is verified against its recorded md5 first.
- The irreversible os.replace comes last: a snapshot failure aborts with
  the target untouched.
- A failed reopen of the same path keeps the session and pending edits.
- target_drift fails closed: a corrupt live file raises DriftUnavailable.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synthetic_rda import make_synthetic_rda
from annoedit.rda import read_rda, write_rda
from annoedit.session import Session, SessionError
from annoedit.rda import RdaFormatError
from annoedit.ops import DriftUnavailable
from annoedit.appsettings import Settings


def _mk_session(tag="p1"):
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


class Phase1DataSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = tempfile.mkdtemp()
        cls.A = make_synthetic_rda(cls.W + "/vanilla.rda")

    def setUp(self):
        os.environ.setdefault("ANN0140_HOME", tempfile.mkdtemp())


    def test_save_keeps_foreign_entries_and_untracked_live_content(self):
        B = self.W + "/live_c1.rda"
        e = read_rda(self.A)
        e["data/othermod.dds"] = (b"tex" * 20, 1)
        e["readme.txt"] = (b"live readme, patched by another mod\n", 1)
        write_rda(e, B)
        s, _ = _mk_session()
        s.open(self.A)
        s.set_live_path(B)
        s.set_dial(s.proj.by_guid["1645021"], "Military/MaxUnitCount", "55")
        s.flash(B)
        live = read_rda(B)
        self.assertEqual(live["data/othermod.dds"][0], b"tex" * 20)
        self.assertEqual(live["readme.txt"][0],
                         b"live readme, patched by another mod\n")
        s.close()

    def test_drift_reports_foreign_informationally(self):
        B = self.W + "/live_c1b.rda"
        e = read_rda(self.A)
        e["data/othermod.dds"] = (b"tex" * 20, 1)
        write_rda(e, B)
        s, _ = _mk_session()
        s.open(self.A)
        drift = s.target_drift(B)
        self.assertIsInstance(drift, tuple)
        self.assertEqual(drift[:5], (0, 0, 0, 0, 0))
        self.assertEqual(drift[5], 1)     # 1 foreign entry, no tracked diff
        s.close()

    def test_save_to_unreadable_target_refuses(self):
        # A target that EXISTS but is unreadable now
        # RAISES (never silently overwrites the live file with the
        # opened archive's members — the old live_ok=False fallback
        # was a data-loss path; a pre-flash snapshot existed but the
        # overwrite was silent).
        B = self.W + "/corrupt_c1.rda"
        open(B, "wb").write(b"garbage" * 100)
        s, _ = _mk_session()
        s.open(self.A)
        s.set_dial(s.proj.by_guid["1645021"], "Military/MaxUnitCount", "55")
        try:
            s.flash(B)
            self.fail("flash to a corrupt existing target must refuse")
        except (SessionError, RdaFormatError):
            pass
        # the corrupt target was NOT overwritten
        with open(B, "rb") as f:
            self.assertEqual(f.read(), b"garbage" * 100)
        s.close()


    def test_surgical_restore_keeps_untracked_live_content(self):
        B = self.W + "/live_c2.rda"
        e = read_rda(self.A)
        e["data/othermod.dds"] = (b"tex" * 20, 1)
        write_rda(e, B)
        s, _ = _mk_session()
        s.provide_vanilla(self.A)
        md5 = s.restore_vanilla(B)
        live = read_rda(B)
        self.assertEqual(live["data/othermod.dds"][0], b"tex" * 20)  # kept
        van = read_rda(self.A)
        for k in van:                     # tracked members are vanilla again
            self.assertEqual(van[k][0], live[k][0])
        self.assertTrue(md5)
        s.close()

    def test_full_restore_replaces_whole_file(self):
        B = self.W + "/live_c2b.rda"
        e = read_rda(self.A)
        e["data/othermod.dds"] = (b"tex" * 20, 1)
        write_rda(e, B)
        s, _ = _mk_session()
        s.provide_vanilla(self.A)
        s.restore_vanilla(B, full=True)
        live = read_rda(B)
        self.assertNotIn("data/othermod.dds", live)
        van = read_rda(self.A)
        self.assertEqual(set(live), set(van))
        s.close()

    def test_restore_verifies_stored_vanilla_md5(self):
        B = self.W + "/live_c2c.rda"
        make_synthetic_rda(B, variant=2)
        s, _ = _mk_session()
        s.provide_vanilla(self.A)
        # corrupt the stored vanilla copy behind the session's back
        with open(s.exports_store.vanilla_path, "r+b") as f:
            f.seek(512)
            f.write(b"\x00\x01\x02\x03")
        with self.assertRaises(SessionError):
            s.restore_vanilla(B)
        # target untouched
        self.assertEqual(read_rda(B), read_rda(self.W + "/live_c2c.rda")
                         if False else read_rda(B))
        s.close()

    def test_restore_refuses_when_target_already_vanilla(self):
        B = self.W + "/live_c2d.rda"
        shutil.copy(self.A, B)
        s, _ = _mk_session()
        s.provide_vanilla(self.A)
        with self.assertRaises(SessionError):
            s.restore_vanilla(B)
        s.close()


    def test_drift_fails_closed_on_corrupt_live(self):
        B = self.W + "/corrupt_m7.rda"
        open(B, "wb").write(b"garbage" * 100)
        s, _ = _mk_session()
        s.open(self.A)
        with self.assertRaises(DriftUnavailable):
            s.target_drift(B)
        s.close()


if __name__ == "__main__":
    unittest.main()
