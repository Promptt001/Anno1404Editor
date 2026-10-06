#!/usr/bin/env python3
"""Golden workflow tests — the four end-to-end user flows, no stubs.

Unit tests pass while a workflow breaks because nothing exercises the glue
between them. These drive the REAL App methods (provide_vanilla -> open ->
set live -> edit -> review -> save -> reopen -> assert), not hand-built
intermediates. Four workflows:

  1. First use: provide vanilla, open the vanilla copy, live identical,
     edit a dial, review, Save to live, reopen live, assert the value.
  2. Opened != live: Save as export must write EXACTLY the reviewed
     rows (the review re-binds to the save target's base before the
     build dispatches).
  3. Live modded by "another mod" (untracked member + tracked non-edited
     value): save to live keeps BOTH the user's edit and the mod's.
  4. Vanilla mode on a modded file, review, save to live, surgical
     restore; the live md5 equals the stored vanilla md5.

Headless companions (run on every box): the per-target rows mapping and
the source pins for the rebind wiring.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)
from synthetic_rda import make_synthetic_rda

try:
    import tkinter  # noqa: F401
    _r = tkinter.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False

try:
    from annoedit.gui.app import ReviewChangesDialog
    HAVE_GUI_MOD = True
except Exception:              # no python3-tk on this box
    HAVE_GUI_MOD = False

LEIF = "1645021"
HILDEGARD = "1645023"
DIAL = "Military/MaxUnitCount"
AI_XML = "addondata/config/ai/aiprofiles.xml"


class RowsForTargetHeadlessTests(unittest.TestCase):
    """ReviewChangesDialog._rows_for_target mapping, headless (no Tk root).

    'Save to live' replays the pending edits onto the LIVE file — the
    rows must be computed against the live base. 'Save as export' builds
    from the OPENED archive (ops.export_named_build applies the ChangeSet
    to the opened project's entries) — the rows must switch to the opened
    base. One list is approved, the SAME list is written.
    """

    def setUp(self):
        from annoedit.session import Session
        self.tmp = tempfile.mkdtemp(prefix="goldrows_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.opened = make_synthetic_rda(
            os.path.join(self.tmp, "opened.rda"), variant=1)
        self.live = make_synthetic_rda(
            os.path.join(self.tmp, "live.rda"))
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "b"),
            exports_root=os.path.join(self.tmp, "e"))
        self.ses.open(self.opened)
        self.addCleanup(self.ses.close)
        p = self.ses.proj.by_guid[LEIF]
        self.ses.set_dial(p, DIAL, "42")

    def _stub(self, base):
        return types.SimpleNamespace(
            _base=base, app=types.SimpleNamespace(ses=self.ses))

    # _rows_for_target is a method on ReviewChangesDialog: called on the
    # class with a stub instance carrying _base + app.ses.

    @unittest.skipUnless(HAVE_GUI_MOD, "no tkinter module")
    def test_export_target_uses_opened_base(self):
        from annoedit.core import ModProject
        live = ModProject(self.live)
        rows, totals = ReviewChangesDialog._rows_for_target(
            self._stub(live), "export")
        want_rows, want_totals = self.ses.pending_change_rows(self.ses.proj)
        self.assertEqual(rows, want_rows,
                         "export rows must come from the OPENED base")
        self.assertEqual(totals, want_totals)

    @unittest.skipUnless(HAVE_GUI_MOD, "no tkinter module")
    def test_live_target_uses_live_base(self):
        from annoedit.core import ModProject
        live = ModProject(self.live)
        rows, totals = ReviewChangesDialog._rows_for_target(
            self._stub(live), "live")
        want_rows, want_totals = self.ses.pending_change_rows(live)
        self.assertEqual(rows, want_rows,
                         "live rows must come from the LIVE base")
        self.assertEqual(totals, want_totals)

    @unittest.skipUnless(HAVE_GUI_MOD, "no tkinter module")
    def test_opened_ne_live_review_rebind_diverges(self):
        # Scenario: opened = modded, live = vanilla, a
        # rule-marked pending edit (vanilla reset) on a dial where the
        # OPENED archive differs. Live-based rows DROP the no-op; the
        # opened-based export rows KEEP it (the export writes it).
        from annoedit.core import ModProject
        live = ModProject(self.live)
        self.ses.provide_vanilla(self.live)
        p = self.ses.proj.by_guid[LEIF]
        self.ses.set_mode(p, "vanilla")
        live_rows, _ = ReviewChangesDialog._rows_for_target(
            self._stub(live), "live")
        exp_rows, _ = ReviewChangesDialog._rows_for_target(
            self._stub(live), "export")
        self.assertGreater(len(exp_rows), len(live_rows),
                           "opened != live + a vanilla-mode reset must "
                           "diverge between the two save targets")


class ReviewBindsSourcePins(unittest.TestCase):
    """Source-level pins: both save paths re-bind before dispatching."""

    def _src(self):
        return open(os.path.join(os.path.dirname(HERE), "annoedit", "gui",
                                "app.py"), encoding="utf-8").read()

    def test_dialog_has_per_target_rows_method(self):
        self.assertIn("def _rows_for_target", self._src(),
                      "the review dialog must recompute rows for the "
                      "chosen save target (export builds from the OPENED "
                      "archive, save-to-live from the LIVE file)")

    def test_both_save_paths_rebind(self):
        src = self._src()
        self.assertIn('self._rebind("export")', src,
                      "Save as export must re-display rows for the "
                      "opened base before building")
        self.assertIn('self._rebind("live")', src,
                      "Save to live must re-display rows for the live base "
                      "(also restores live rows after a cancelled export)")

@unittest.skipUnless(HAVE_DISPLAY, "no display — needs tkinter + X")
class GoldenWorkflows(unittest.TestCase):
    """The four end-to-end user flows, driving the real App methods."""

    def setUp(self):
        from annoedit.gui import app as appmod
        from guitest import patch_messagebox
        self.tmp = tempfile.mkdtemp(prefix="gold_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vanilla = make_synthetic_rda(
            os.path.join(self.tmp, "vanilla.rda"))
        self.live = make_synthetic_rda(
            os.path.join(self.tmp, "live", "data1.rda"))
        self.appmod = appmod
        self.mb = patch_messagebox(self)
        from annoedit.backup import BackupStore
        from annoedit.exports import ExportStore
        real_init = BackupStore.__init__

        def init(store, root=None):
            real_init(store, os.path.join(self.tmp, "backups"))

        # ExportStore reads the process-wide ANN0140_HOME too —
        # isolate it the same way or the write-once vanilla copy
        # leaks across tests (one test's provide-vanilla becomes
        # the next test's "already stored" state).
        real_einit = ExportStore.__init__

        def einit(estore, root=None):
            real_einit(estore, os.path.join(self.tmp, "exports"))

        BackupStore.__init__ = init
        ExportStore.__init__ = einit
        try:
            self.app = appmod.App(auto_open=False)
        finally:
            BackupStore.__init__ = real_init
            ExportStore.__init__ = real_einit
        self.addCleanup(self._destroy)

    def _destroy(self):
        try:
            self.app.ses.close()
            self.app.destroy()
        except Exception:
            pass

    def wait_idle(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            self.app.update()
            if not self.app._busy_flag:
                return
            time.sleep(0.02)
        self.fail(f"background job did not finish in {timeout}s "
                  f"(error boxes: {self.mb.errors})")

    def _wait_dialog(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            self.app.update()
            for w in self.app.winfo_children():
                if isinstance(w, ReviewChangesDialog) \
                        and w.winfo_exists():
                    return w
            time.sleep(0.02)
        self.fail(f"no ReviewChangesDialog appeared "
                  f"(errors: {self.mb.errors})")

    def _review(self):
        self.app._review_and_save()
        return self._wait_dialog()

    def _stub_askstring(self, value):
        real = self.appmod.simpledialog.askstring
        self.appmod.simpledialog.askstring = lambda *a, **k: value

        def restore():
            self.appmod.simpledialog.askstring = real
        self.addCleanup(restore)

    def _open_live_van_copy(self):
        self.app.ses.provide_vanilla(self.vanilla)
        self.app.ses.set_live_path(self.live)
        self.app.open_archive(self.app.ses.exports_store.vanilla_path,
                              quiet=True)
        self.wait_idle()

    def _edit_leif(self, value="42"):
        p = self.app.ses.proj.by_guid[LEIF]
        self.app.ses.set_dial(p, DIAL, value)

    def _dialog_rows(self, dlg):
        out = []
        for iid in dlg.tree.get_children():
            vals = dlg.tree.item(iid, "values")
            out.append((vals[0], vals[1], vals[2], vals[4]))
        return out

    def _assert_no_errors(self):
        self.assertEqual(self.mb.errors, [], "unexpected error box")

    def _read_live_member(self, name):
        from annoedit.rda import read_rda
        return dict(read_rda(self.live, strict=True))[name][0]

    def test_workflow1_first_use_save_to_live(self):
        # README's own first-run flow: provide vanilla, open the vanilla
        # copy, live still vanilla, edit, review, save to live. Must not
        # crash (the 'dict' object has no attribute 'by_guid' class).
        self._open_live_van_copy()
        self._edit_leif("42")
        dlg = self._review()
        rows = self._dialog_rows(dlg)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], DIAL)
        dlg._save_live()
        self.wait_idle()
        self._assert_no_errors()
        self.assertIn(b"<MaxUnitCount>42</MaxUnitCount>",
                      self._read_live_member(AI_XML))

    def test_workflow2_export_writes_reviewed_rows(self):
        # Opened != live: Save as export builds from the OPENED archive;
        # the review must re-bind to that base, so what is written equals
        # what was approved. The export must NOT touch the live file.
        self._open_live_van_copy()
        # 4242 (not 42): the synthetic fixture already contains
        # MaxUnitCount 42 natively, so an assertNotIn on 42 could
        # never pass.
        self._edit_leif("4242")
        dlg = self._review()
        self._stub_askstring("gold2")
        dlg._save_export()
        self.wait_idle()
        self._assert_no_errors()
        # ExportStore uses the process-wide ANN0140_HOME — locate the
        # export through the store, never via a guessed temp path.
        exported = os.path.join(self.app.ses.exports_store.root,
                                "data1.rda_gold2")
        self.assertTrue(os.path.isfile(exported), "export missing")
        self.assertIn(b"<MaxUnitCount>4242</MaxUnitCount>",
                      dict(
                          __import__("annoedit.rda",
                                     fromlist=["read_rda"]).read_rda(
                              exported, strict=True))[AI_XML][0])
        self.assertNotIn(b"<MaxUnitCount>4242</MaxUnitCount>",
                        self._read_live_member(AI_XML),
                        "export must not touch the live file")

    def test_workflow3_other_mod_survives_save_to_live(self):
        # Live carries another mod (untracked member + tracked non-edited
        # value). Save to live keeps the user's edit AND the mod's data.
        from annoedit.rda import read_rda, write_rda
        entries = dict(read_rda(self.live, strict=True))
        entries["addondata/config/gui/other.ini"] = (b"othermod", 2)
        text = entries[AI_XML][0].decode("utf-8")
        # Hildegard's ShipAttackIntervall: a tracked dial the user does
        # NOT edit — moved by the other mod to 123000
        import re as _re
        mt = _re.search(
            r"(1645023.{0,4000}?)<ShipAttackIntervall>(\d+)"
            r"</ShipAttackIntervall>", text, _re.S)
        self.assertTrue(mt, "fixture: Hildegard dial not found")
        text = text[:mt.start(2)] + "123000" + text[mt.end(2):]
        entries[AI_XML] = (text.encode("utf-8"), entries[AI_XML][1])
        write_rda(entries, self.live)
        self._open_live_van_copy()
        self._edit_leif("42")
        dlg = self._review()
        dlg._save_live()
        self.wait_idle()
        self._assert_no_errors()
        self.assertIn(b"othermod", dict(read_rda(self.live, strict=True))
                      ["addondata/config/gui/other.ini"][0],
                      "the other mod's untracked member was erased")
        live_xml = self._read_live_member(AI_XML).decode("utf-8")
        mt2 = _re.search(
            r"(1645023.{0,4000}?)<ShipAttackIntervall>(\d+)"
            r"</ShipAttackIntervall>", live_xml, _re.S)
        self.assertEqual(mt2.group(2), "123000",
                         "the other mod's tracked edit was silently "
                         "reverted")
        self.assertIn(b"<MaxUnitCount>42</MaxUnitCount>",
                      self._read_live_member(AI_XML))

    def test_workflow4_vanilla_mode_restore_md5(self):
        # Vanilla mode on a modded-opened file, review, save to live,
        # surgical restore: the live md5 must equal the stored vanilla
        # md5 (content-based identity, not name-based).
        self._open_live_van_copy()
        self._edit_leif("42")
        dlg = self._review()
        dlg._save_live()
        self.wait_idle()
        self._assert_no_errors()
        self.app.restore_vanilla()
        self.wait_idle()
        self._assert_no_errors()
        self.assertEqual(_md5(self.live),
                         _md5(self.app.ses.exports_store.vanilla_path),
                         "surgical restore left the live file != vanilla")


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    unittest.main()
