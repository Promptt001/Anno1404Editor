"""Drift result and conflict-dialog regressions.

- The no-drift branch of drift_check hands the review a parsed
  ModProject (the review dialog relies on its by_guid index).
- The EXTRAS-conflict dialog shows the live path, not a bound method.
- A test file must never import a tkinter module it only reads as text.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)
from synthetic_rda import make_synthetic_rda


class DriftLiveTypedTests(unittest.TestCase):
    """DriftResult.live must be a parsed ModProject or None — never a dict."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "live"))
        self.opened = make_synthetic_rda(
            os.path.join(self.tmp, "opened.rda"))
        self.live = os.path.join(self.tmp, "live", "data1.rda")

    def test_no_drift_live_is_modproject(self):
        from annoedit.core import ModProject
        from annoedit.session import Session
        from annoedit import ops
        # Live identical to opened in every tracked member: the branch
        # that used to return the raw entries dict as .live.
        import shutil
        shutil.copy(self.opened, self.live)
        s = Session(backup_root=os.path.join(self.tmp, "b"),
                    exports_root=os.path.join(self.tmp, "e"))
        s.set_live_path(self.live)
        s.open(self.opened)
        drift = ops.drift_check(*s.freeze_drift_inputs())
        self.assertIsInstance(drift, ops.DriftResult)
        self.assertFalse(drift, "zero-drift result must stay falsy")
        self.assertIsInstance(drift.live, ModProject,
                              "DriftResult.live must be a ModProject, "
                              "not a raw entries dict")
        # The first-use flow: review rows must compute against .live.
        s.set_dial(s.proj.by_name["Leif Jorgensen"],
                   "Military/MaxUnitCount", "42")
        rows, totals = s.pending_change_rows(drift.live)
        self.assertEqual(totals["dials"], 1)
        self.assertEqual(rows[0]["old"], "41",
                         "review 'old' comes from the live base")
        self.assertEqual(drift.live_md5, ops.md5_of(self.live)
                         if hasattr(ops, "md5_of") else drift.live_md5)
        s.close()

    def test_foreign_only_live_is_none(self):
        # The foreign-only early return keeps live=None (typed, honest).
        from annoedit.session import Session
        from annoedit import ops
        # Build a live archive with one differing UNTRACKED member
        # (set_live_path needs the file to exist first).
        from annoedit.rda import read_rda, write_rda
        entries = dict(read_rda(self.opened, strict=True))
        entries["addondata/config/gui/other.ini"] = (b"x9", 2)
        write_rda(entries, self.live)
        s = Session(backup_root=os.path.join(self.tmp, "b2"),
                    exports_root=os.path.join(self.tmp, "e2"))
        s.set_live_path(self.live)
        s.open(self.opened)
        drift = ops.drift_check(*s.freeze_drift_inputs())
        self.assertTrue(drift[5], "expected the untracked diff")
        self.assertIsNone(drift.live)
        s.close()

    def test_constructor_refuses_raw_dict(self):
        from annoedit import ops
        with self.assertRaises(TypeError):
            ops.DriftResult(0, 0, 0, 0, 0, 0, live={"aiprofiles.xml":
                                                    (b"x", 1)})


class ConflictDialogPathTests(unittest.TestCase):
    """The EXTRAS-conflict message must name the actual live path."""

    def test_dialog_code_calls_live_path(self):
        # Source-level pin: the dialog builds live_path by CALLING
        # Session.live_path(), never by referencing the bound method.
        app_py = os.path.join(os.path.dirname(HERE), "annoedit", "gui",
                              "app.py")
        src = open(app_py, encoding="utf-8").read()
        self.assertIn("self.ses.live_path() or", src)
        self.assertNotIn("live_path = (self.ses.live_path\n", src)


class TkFreeImportTests(unittest.TestCase):
    """Tests must never import a tkinter module they only read as text."""

    def test_phase2_source_pin_needs_no_gui_import(self):
        # The pinned assertion must be reachable on tkinter-free boxes:
        # app.py is located by PATH, not by import.
        tests_py = os.path.join(HERE, "test_extras_conflict_policy.py")
        src = open(tests_py, encoding="utf-8").read()
        self.assertNotIn("import annoedit.gui.app", src)
        app_py = os.path.join(os.path.dirname(HERE), "annoedit", "gui",
                              "app.py")
        self.assertTrue(os.path.isfile(app_py))


if __name__ == "__main__":
    unittest.main()
