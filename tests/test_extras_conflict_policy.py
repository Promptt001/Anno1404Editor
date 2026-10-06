"""EXTRAS conflict policy and global-revert reporting.

- EXTRAS conflicts are blocking in the drift dialog (the replay guard
  would refuse them at build time anyway).
- "Revert to vanilla (global)" reports the tool's own allow-listed
  inserts as un-revertable instead of silently keeping them.
- A Vanilla click without a vanilla reference only drops pending edits,
  and the mode label says so.
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


class ExtrasConflictPolicyTests(unittest.TestCase):
    """EXTRAS conflicts must be BLOCKING, never 'Continue anyway?'."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.opened = make_synthetic_rda(os.path.join(self.tmp, "opened.rda"))
        self.live = os.path.join(self.tmp, "data1.rda")
        import shutil
        shutil.copy(self.opened, self.live)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_extras_conflict_is_blocking_and_names_live_file(self):
        # another mod changes live Noria/NoriaEndRadius#1 from 8 to 7;
        # the user's pending edit sets #1 to 12 -> true EXTRAS conflict
        from annoedit.session import Session
        s = Session(backup_root=os.path.join(self.tmp, "b1"),
                    exports_root=os.path.join(self.tmp, "e1"))
        s.set_live_path(self.live)
        s.open(self.live)
        s.set_extra("Noria", "NoriaEndRadius", "7", 0)
        s.flash(target=self.live)
        s.close()
        s = Session(backup_root=os.path.join(self.tmp, "b1"),
                    exports_root=os.path.join(self.tmp, "e1"))
        s.set_live_path(self.live)
        s.open(self.opened)
        s.set_extra("Noria", "NoriaEndRadius", "12", 0)
        drift = s.target_drift()
        self.assertEqual(tuple(drift)[:4], (0, 0, 1, 0),
                         "expected exactly one extras conflict")
        # The GUI must refuse: assert the policy marker is present in
        # the dialog logic (the blocking branch exists in app.py).
        # Locate app.py by path, never by import: this test only
        # READS its source, and importing it pulls tkinter on machines
        # without python3-tk (a hard import error, not a clean skip).
        app_py = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "annoedit", "gui", "app.py")
        src = open(app_py, encoding="utf-8").read()
        self.assertIn("EXTRAS conflicts must be resolved first", src)
        self.assertIn("the LIVE file instead", src)
        s.close()

    def test_extras_conflict_build_refuses_with_live_guidance(self):
        from annoedit.session import Session, SessionError
        s = Session(backup_root=os.path.join(self.tmp, "b2"),
                    exports_root=os.path.join(self.tmp, "e2"))
        s.set_live_path(self.live)
        s.open(self.live)
        s.set_extra("Noria", "NoriaEndRadius", "7", 0)
        s.flash(target=self.live)
        s.close()
        s = Session(backup_root=os.path.join(self.tmp, "b2"),
                    exports_root=os.path.join(self.tmp, "e2"))
        s.set_live_path(self.live)
        s.open(self.opened)
        s.set_extra("Noria", "NoriaEndRadius", "12", 0)
        with self.assertRaises(SessionError) as cm:
            s.flash(target=self.live)
        # the refusal must point the user at the LIVE file (the old
        # message said 'reopen the archive' - the wrong file)
        self.assertIn("LIVE", str(cm.exception).upper())
        s.close()


class UnrevertableExtrasTests(unittest.TestCase):
    """A global revert reports the tool's own INSERTS as un-revertable."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def _modded_with_insert(self):
        # insert ProductionTime on PrintingHouse (allow-listed), flash
        import shutil
        live = os.path.join(self.tmp, "live.rda")
        shutil.copy(self.arch, live)
        from annoedit.session import Session
        s = Session(backup_root=os.path.join(self.tmp, "b3"),
                    exports_root=os.path.join(self.tmp, "e3"))
        s.open(live)
        s.set_extra("PrintingHouse", "ProductionTime", "5000")
        s.flash(target=live)
        s.close()
        return live

    def test_insert_surviving_revert_is_reported(self):
        live = self._modded_with_insert()
        from annoedit.session import Session
        s = Session(backup_root=os.path.join(self.tmp, "b3"),
                    exports_root=os.path.join(self.tmp, "e3"))
        s.provide_vanilla(self.arch)
        s.open(live)
        s.revert_globals_to_reference()
        unrev = getattr(s, "_last_unrevertable_extras", [])
        self.assertTrue(any("ProductionTime" in u for u in unrev),
                        f"the tool's own ProductionTime INSERT must be "
                        f"reported un-revertable, got {unrev}")
        s.close()

    def test_clean_archive_has_no_unrevertable_extras(self):
        from annoedit.session import Session
        s = Session()
        s.provide_vanilla(self.arch)
        s.open(self.arch)
        s.revert_globals_to_reference()
        self.assertEqual(s._last_unrevertable_extras, [])
        s.close()


class VanillaNoRefLabelTests(unittest.TestCase):
    """A Vanilla click without a reference drops pending only and the
    mode label must not claim 'vanilla'."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_no_baseline_vanilla_label(self):
        from annoedit.session import Session
        s = Session(backup_root=os.path.join(self.tmp, "bn"),
                    exports_root=os.path.join(self.tmp, "en"))
        s.open(self.arch)   # NO provide_vanilla -> no provided copy
        # the first-open snapshot is a fallback baseline; neutralize
        # it so the no-REFERENCE path is what runs (the label tests
        # the reference, not the snapshot fallback)
        s.vanilla_baseline = None
        q = s.roster[0]
        s.set_dial(q, "Build/BuildSupplyDepot", "1")
        mode_return = s.set_mode(q, "vanilla")
        self.assertEqual(s.modes.get(q.guid), "vanilla_no_ref",
                         "the label must say the click only dropped edits")
        # pending edits for that char were dropped
        self.assertFalse(s.changes.get(q.guid))
        s.close()

    def test_with_baseline_label_is_vanilla(self):
        from annoedit.session import Session
        s = Session(backup_root=os.path.join(self.tmp, "bn"),
                    exports_root=os.path.join(self.tmp, "en"))
        s.provide_vanilla(self.arch)
        s.open(self.arch)
        q = s.roster[0]
        s.set_mode(q, "vanilla")
        self.assertEqual(s.modes.get(q.guid), "vanilla")
        s.close()


if __name__ == "__main__":
    unittest.main()
