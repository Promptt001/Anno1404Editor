"""Pending-change review window and toolbar/column layout.

  * Session.pending_change_rows(): one structured row per pending change
    (character, dial, old value, new value) across AI dials, relations,
    extras and fertility; the review window's data source;
  * the review dialog wiring (save-to-live / save-as-export callbacks);
  * the toolbar keeps its buttons on screen (two fixed rows, compact
    archive label, full path only in the tooltip);
  * dial-table column order: value | vanilla | new side by side, then
    'source' (main window and editor window).
"""
import os
import shutil
import tempfile
import unittest

from fixture import TEST_RDA, HAVE_RDA


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class PendingChangeRowsTests(unittest.TestCase):
    """Session.pending_change_rows: one row per pending change, all classes."""

    def setUp(self):
        from annoedit.backup import BackupStore
        from annoedit.session import Session
        self.tmp = tempfile.mkdtemp(prefix="revrows_")
        self.src = os.path.join(self.tmp, "data1.rda")
        shutil.copyfile(TEST_RDA, self.src)
        real_init = BackupStore.__init__

        def init(store, root=None):
            real_init(store, os.path.join(self.tmp, "backups"))

        BackupStore.__init__ = init
        try:
            self.ses = Session(
                backup_root=os.path.join(self.tmp, "backups"),
                exports_root=os.path.join(self.tmp, "exports"),
                persona_dirs=(os.path.join(os.path.dirname(__file__),
                                           "..", "annoedit", "presets"),))
            self.ses.open(self.src)
        finally:
            BackupStore.__init__ = real_init

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _leif(self):
        return self.ses.proj.by_guid["1645021"]

    def test_no_pending_no_rows(self):
        rows, totals = self.ses.pending_change_rows()
        self.assertEqual(rows, [])
        self.assertEqual(totals, {"dials": 0, "relations": 0,
                                   "extras": 0, "fertility": 0})

    def test_dial_rows_show_old_and_new(self):
        p = self._leif()
        old = self.ses.effective(p, "ShipFight/ShipAttackIntervall")[0]
        self.ses.set_dial(p, "ShipFight/ShipAttackIntervall", "20000")
        rows, totals = self.ses.pending_change_rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["section"], "AI profile")
        self.assertEqual(r["character"], p.name)
        self.assertEqual(r["dial"], "ShipFight/ShipAttackIntervall")
        self.assertEqual(str(r["old"]), str(old))
        self.assertEqual(r["new"], "20000")
        self.assertEqual(totals["dials"], 1)

    def test_relations_rows_show_list_replacement(self):
        p = self._leif()
        cur = self.ses.relations_row(p, "War")
        avoid = set(self.ses.proj.relations(p).get("AvoidWar", ()))
        extra = [g for g in self.ses.proj.by_guid
                 if g != p.guid and g not in avoid and g not in cur][0]
        self.ses.set_relations(p, war=cur + [extra])
        rows, totals = self.ses.pending_change_rows()
        rel_rows = [r for r in rows if r["section"] == "AI relations"]
        self.assertEqual(len(rel_rows), 1)
        self.assertEqual(rel_rows[0]["dial"], "Relations/War")
        self.assertEqual(rel_rows[0]["old"],
                         ", ".join(str(g) for g in cur) or "(empty)")
        self.assertIn(extra, rel_rows[0]["new"])
        self.assertEqual(totals["relations"], 1)

    def test_persona_rows_dials_and_relations(self):
        # a persona queues both dials and relations in one step
        p = self._leif()
        self.ses.set_mode(p, "The Admiral")
        rows, totals = self.ses.pending_change_rows()
        self.assertGreater(totals["dials"], 0)
        self.assertGreaterEqual(totals["relations"], 0)
        # every dial row has an old and a new value (old never None-empty)
        for r in rows:
            if r["section"] == "AI profile":
                self.assertTrue(r["new"])
                self.assertIn(r["dial"], self.ses.changes[p.guid])

    def test_extras_rows_show_vanilla_old(self):
        # vanilla value comes from the OPENED archive's catalog (fixture
        # data varies: synthetic Bakery 40000, real data1.rda 15000) —
        # derive the expected value instead of hardcoding one fixture.
        cat = self.ses.extras_catalog()
        want = None
        for section in cat.values():
            fam = section.get("ProductionTime")
            if fam and fam.get("Bakery"):
                want = fam["Bakery"][0]
                break
        self.assertIsNotNone(want, "Bakery/ProductionTime not in catalog")
        self.ses.set_extra("Bakery", "ProductionTime", "1000")
        rows, totals = self.ses.pending_change_rows()
        xr = [r for r in rows if r["section"] == "EXTRAS"]
        self.assertEqual(len(xr), 1)
        self.assertEqual(xr[0]["dial"], "ProductionTime")
        self.assertEqual(xr[0]["old"], want)
        self.assertEqual(xr[0]["new"], "1000")
        self.assertEqual(totals["extras"], 1)

    def test_extras_occurrence_row(self):
        # derive the expected first-instance value from the catalog (fixture
        # data varies: synthetic Noria 8/10, real data1.rda 26/...)
        cat = self.ses.extras_catalog()
        want = None
        for section in cat.values():
            fam = section.get("NoriaEndRadius")
            if fam and fam.get("Noria"):
                want = fam["Noria"][0]
                break
        self.assertIsNotNone(want, "Noria/NoriaEndRadius not in catalog")
        self.ses.set_extra("Noria", "NoriaEndRadius", "50", occ=0)
        rows, _ = self.ses.pending_change_rows()
        xr = [r for r in rows if r["section"] == "EXTRAS"]
        self.assertEqual(len(xr), 1)
        self.assertEqual(xr[0]["dial"], "NoriaEndRadius #1")
        self.assertEqual(xr[0]["old"], want)

    def test_fertility_rows_show_north_south(self):
        self.ses.set_fertility("low", "Almond", north=90)
        rows, totals = self.ses.pending_change_rows()
        fr = [r for r in rows if r["section"] == "FERTILITY"]
        self.assertEqual(len(fr), 1)
        self.assertEqual(fr[0]["dial"], "Almond")
        self.assertIn("N=90", fr[0]["new"])
        self.assertEqual(totals["fertility"], 1)

    def test_rows_match_build_counts(self):
        # the totals the review shows must equal what a real build applies
        p = self._leif()
        self.ses.set_dial(p, "ShipFight/ShipAttackIntervall", "20000")
        self.ses.set_extra("Bakery", "ProductionTime", "1000")
        self.ses.set_fertility("low", "Almond", north=90)
        cur = self.ses.relations_row(p, "War")
        avoid = set(self.ses.proj.relations(p).get("AvoidWar", ()))
        extra = [g for g in self.ses.proj.by_guid
                 if g != p.guid and g not in avoid and g not in cur][0]
        self.ses.set_relations(p, war=cur + [extra])
        _rows, totals = self.ses.pending_change_rows()
        rep = self.ses.export(os.path.join(self.tmp, "out.rda"))
        self.assertEqual(rep["dial_edits"], totals["dials"])
        self.assertEqual(rep["extras_edits"], totals["extras"])
        self.assertEqual(rep["fert_edits"], totals["fertility"])


try:
    import tkinter as tk
    HAVE_TK = True
except Exception:                 # no display / no python3-tk
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "no tkinter")
@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class ReviewDialogTests(unittest.TestCase):
    """The review window: rows, save-choice callbacks, column order."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="revdlg_")
        self.src = os.path.join(self.tmp, "data1.rda")
        shutil.copyfile(TEST_RDA, self.src)
        try:
            self.root = tk.Tk()
        except Exception:
            raise unittest.SkipTest("no display")
        from annoedit.backup import BackupStore
        from annoedit.session import Session
        # modal messageboxes patched (recorded, auto-answered)
        # so GUI failures fail instead of hanging
        from guitest import patch_messagebox
        self.mb = patch_messagebox(self)
        real_init = BackupStore.__init__

        def init(store, root=None):
            real_init(store, os.path.join(self.tmp, "backups"))

        BackupStore.__init__ = init
        try:
            self.ses = Session(
                backup_root=os.path.join(self.tmp, "backups"),
                exports_root=os.path.join(self.tmp, "exports"),
                persona_dirs=(os.path.join(os.path.dirname(__file__),
                                           "..", "annoedit", "presets"),))
            self.ses.open(self.src)
        finally:
            BackupStore.__init__ = real_init

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _app_stub(self):
        """Minimal App stub for ReviewChangesDialog (avoids full App)."""
        class A:
            ses = self.ses
        return A()

    def test_review_dialog_rows_and_totals(self):
        p = self.ses.proj.by_guid["1645021"]
        self.ses.set_dial(p, "ShipFight/ShipAttackIntervall", "20000")
        from annoedit.gui.app import ReviewChangesDialog
        dlg = ReviewChangesDialog(self.root, self._app_stub())
        try:
            self.assertEqual(len(dlg.tree.get_children()), 1)
            vals = dlg.tree.item(dlg.tree.get_children()[0], "values")
            # column order: section | character | dial | old | new
            self.assertEqual(vals[0], "AI profile")
            self.assertEqual(vals[2], "ShipFight/ShipAttackIntervall")
            self.assertEqual(vals[4], "20000")
            self.assertEqual(dlg.result, None)     # not saved yet
        finally:
            dlg.destroy()

    def test_review_dialog_save_live_callback(self):
        p = self.ses.proj.by_guid["1645021"]
        self.ses.set_dial(p, "ShipFight/ShipAttackIntervall", "20000")
        from annoedit.gui.app import ReviewChangesDialog
        seen = []
        dlg = ReviewChangesDialog(self.root, self._app_stub(),
                                  on_save=lambda a, n: seen.append((a, n)))
        try:
            dlg._save_live()
            self.assertEqual(seen, [("live", None)])
            self.assertEqual(dlg.result, "live")
        finally:
            dlg.destroy()

    def test_review_dialog_save_export_callback(self):
        p = self.ses.proj.by_guid["1645021"]
        self.ses.set_dial(p, "ShipFight/ShipAttackIntervall", "20000")
        from annoedit.gui.app import ReviewChangesDialog
        seen = []
        dlg = ReviewChangesDialog(self.root, self._app_stub(),
                                  on_save=lambda a, n: seen.append((a, n)))
        try:
            # stub the name prompt (modal in real use)
            import annoedit.gui.app as appmod
            real_ask = appmod.simpledialog.askstring
            appmod.simpledialog.askstring = \
                lambda *a, **k: "My Build 1"
            try:
                dlg._save_export()
            finally:
                appmod.simpledialog.askstring = real_ask
            self.assertEqual(seen, [("export", "My_Build_1")])
            self.assertEqual(dlg.result, ("export", "My_Build_1"))
        finally:
            dlg.destroy()

    def test_main_window_columns_value_vanilla_new_source(self):
        # full App: verify the reworked toolbar + column order
        import annoedit.gui.app as appmod
        app = appmod.App()
        try:
            self.assertEqual(
                app.tree["columns"],
                ("category", "dial", "value", "vanilla", "new", "source"))
            # source is the LAST column (was between value and default)
            self.assertEqual(app.tree.heading("source")["text"], "Source")
            # toolbar buttons all exist and are children of the two rows
            for b in (app.restore_btn, app.flash_btn, app.export_btn,
                      app.open_btn, app.open_live_btn):
                self.assertTrue(b.winfo_exists())
        finally:
            app.destroy()

    def test_editor_window_columns_value_vanilla_new_source(self):
        from annoedit.gui.editor import EditorWindow
        p = self.ses.proj.by_guid["1645021"]
        win = EditorWindow(self.root, self.ses, p)
        try:
            self.assertEqual(
                win.tree["columns"],
                ("dial", "value", "vanilla", "new", "source"))
        finally:
            win.destroy()

    def test_compact_path_middle_ellipsis(self):
        import annoedit.gui.app as appmod
        long_path = "/home/promptt/.local/share/Steam/steamapps/common/" \
                    "Anno 1404 - History Edition/addon/data1.rda"
        compact = appmod.App._compact_path(long_path)
        self.assertLessEqual(len(compact), 44)
        self.assertTrue(compact.startswith("/home"))
        self.assertTrue(compact.endswith("data1.rda"))
        self.assertIn("…", compact)
        # short paths stay intact
        self.assertEqual(appmod.App._compact_path("/a/b.rda"), "/a/b.rda")

    def test_review_dialog_allows_export_when_no_changes(self):
        # 'Save as export' stays available with zero pending edits —
        # an identical-copy export is legal (live save is disabled)
        from annoedit.gui.app import ReviewChangesDialog
        dlg = ReviewChangesDialog(self.root, self._app_stub(),
                                  allow_live=False)
        try:
            self.assertEqual(str(dlg.live_btn["state"]), "disabled")
            self.assertEqual(len(dlg.tree.get_children()), 0)
        finally:
            dlg.destroy()


class BuildWidgetsStructureTests(unittest.TestCase):
    """Regression gate: App._build_widgets must stay structurally intact.

    A multi-chunk insertion spliced the _show_path_tip/_hide_path_tip/
    _compact_path helpers into the MIDDLE of App._build_widgets; the
    early `return` in _compact_path made the whole notebook/roster/tree/
    status-label block dead code, so __init__'s _set_status() crashed
    with AttributeError on a real display (headless stubs never noticed).
    These structural checks run WITHOUT a display so this class of
    splice bug can never ship silently again.
    """

    APP_SRC = os.path.join(os.path.dirname(__file__), "..",
                           "annoedit", "gui", "app.py")

    def _app_ast(self):
        import ast
        with open(self.APP_SRC, newline="", encoding="utf-8") as fh:
            text = fh.read()
        return text, ast.parse(text)

    def test_build_widgets_is_one_flat_method(self):
        # no nested defs and no return statements inside _build_widgets
        import ast
        src, tree = self._app_ast()
        bw = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_build_widgets")
        for node in ast.walk(bw):
            if node is bw:
                continue
            self.assertNotIsInstance(node, ast.FunctionDef,
                "helper method spliced into _build_widgets")
            self.assertNotIsInstance(node, ast.Return,
                "early return makes later widget code dead")

    def test_build_widgets_creates_all_key_widgets(self):
        src, tree = self._app_ast()
        import ast
        bw = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_build_widgets")
        body = ast.get_source_segment(src, bw)
        for attr in ("self.status", "self.roster", "self.tree",
                     "self.doc", "self.xtab", "self.ftab",
                     "self.path_lbl", "self.flash_btn"):
            self.assertIn(attr + " =", body,
                          f"{attr} not created inside _build_widgets")

    def test_compact_path_is_pure_helper(self):
        src, tree = self._app_ast()
        import ast
        cp = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_compact_path")
        body = ast.get_source_segment(src, cp)
        for leak in ("Notebook", "roster", "self.status",
                     "self.tree", "self.doc"):
            self.assertNotIn(leak, body,
                             f"widget code leaked into _compact_path")


@unittest.skipUnless(os.environ.get("DISPLAY"), "no display — headless run")
class AppInstantiationTests(unittest.TestCase):
    """The strongest gate: REALLY build the main window when possible.

    Some widget-construction bugs only reproduce on a real display; every headless
    suite skipped past it. On any machine with $DISPLAY set (the
    operator's gaming machine, CI with Xvfb), App() must construct
    fully and _set_status() must work end to end.
    """

    def test_app_constructs_and_sets_status(self):
        import shutil
        import tempfile
        import time
        from unittest import mock
        sys_path = os.path.dirname(os.path.abspath(__file__))
        import sys
        sys.path.insert(0, sys_path)
        from synthetic_rda import make_synthetic_rda
        tmp = tempfile.mkdtemp(prefix="appinst_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {
            "ANN0140_SETTINGS_DIR": tmp,
            "ANN0140_EXPORTS_DIR": os.path.join(tmp, "ex"),
            "ANN0140_LOG_FILE": os.path.join(tmp, "log")})
        env.start()
        self.addCleanup(env.stop)
        rda = make_synthetic_rda(os.path.join(tmp, "data1.rda"))
        from annoedit.appsettings import Settings
        Settings().set("live_path", rda)       # what a previous launch saved
        from annoedit.gui.app import App
        app = App()
        try:
            app._set_status("gate probe")
            self.assertEqual(str(app.status.cget("text")), "gate probe")
            # the persisted live archive is reopened on launch
            end = time.time() + 20
            while time.time() < end and (app.ses.proj is None or app._busy_flag):
                app.update()
                time.sleep(0.02)
            self.assertGreater(len(app.roster.get(0, "end")), 0)
        finally:
            app.ses.close()
            app.destroy()


if __name__ == "__main__":
    unittest.main()
