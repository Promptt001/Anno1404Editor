#!/usr/bin/env python3
"""GUI polish regressions (synthetic archive; GUI classes need tkinter
and a display, e.g. xvfb-run, and skip cleanly otherwise).

- Editing a dial or picking a preset keeps the selected character, and
  switching characters after a preset is clean.
- The editor window never loops on refresh, and a typed value is
  committed to the row it was loaded for.
- The busy state is always cleared after a background job.
- Persistence: vanilla copy, live location and last archive survive a
  relaunch, and the last archive is reopened automatically.
- "Save to live" writes the live file (not the opened baseline) and can
  never overwrite data1.rda_vanilla; Restore prefers the provided copy.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from synthetic_rda import make_synthetic_rda  # noqa: E402
from annoedit.appsettings import Settings  # noqa: E402
from annoedit.backup import md5_of  # noqa: E402
from annoedit.session import Session, SessionError  # noqa: E402

PRESETS = os.path.join(HERE, "..", "annoedit", "presets")
LEIF = "1645021"
HILDEGARD = "1645023"


class _Sandbox(unittest.TestCase):
    """Temp dirs + a synthetic 'game' archive and a 'modded' variant."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="polish_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(
            os.path.join(self.tmp, "game", "addon", "data1.rda"))
        self.vanilla_md5 = md5_of(self.game)
        self.other = make_synthetic_rda(
            os.path.join(self.tmp, "other", "data1.rda"), variant=1)

    def mk(self):
        return Session(backup_root=os.path.join(self.tmp, "backups"),
                       exports_root=os.path.join(self.tmp, "exports"),
                       settings=Settings(os.path.join(self.tmp, "cfg")),
                       persona_dirs=(PRESETS,))


class SessionTargetTests(_Sandbox):
    """flash/restore targets and the stored-vanilla guard (headless)."""

    def test_flash_to_live_keeps_baseline_and_vanilla_copy(self):
        s = self.mk()
        s.provide_vanilla(self.game)
        s.set_live_path(self.game)
        s.open(s.exports_store.vanilla_path)      # edit from the vanilla copy
        self.assertEqual(s.default_target(), self.game)
        s.set_mode(s.proj.by_guid[LEIF], "The Admiral")
        rep = s.flash(s.default_target())
        self.assertEqual(rep["flashed"], self.game)
        self.assertFalse(rep["in_place"])
        self.assertNotEqual(md5_of(self.game), self.vanilla_md5)
        # the stored vanilla copy is untouched, pending edits are kept
        self.assertEqual(md5_of(s.exports_store.vanilla_path),
                         self.vanilla_md5)
        self.assertIn(LEIF, s.changes)
        s.close()

    def test_flash_refuses_stored_vanilla_copy(self):
        s = self.mk()
        s.provide_vanilla(self.game)
        s.open(s.exports_store.vanilla_path)
        s.set_dial(s.proj.by_guid[LEIF], "Military/MaxUnitCount", "60")
        # no live location: the GUI default target must NOT be the copy
        self.assertIsNone(s.default_target())
        with self.assertRaises(SessionError):
            s.flash()                              # in-place onto the copy
        self.assertEqual(md5_of(s.exports_store.vanilla_path),
                         self.vanilla_md5)
        s.close()

    def test_restore_prefers_provided_vanilla_copy(self):
        s = self.mk()
        # first open = a MODDED archive -> the auto-backup captures it
        s.open(self.other)
        s.close()
        s.provide_vanilla(self.game)
        target = os.path.join(self.tmp, "live.rda")
        shutil.copyfile(self.other, target)
        md5 = s.restore_vanilla(target)            # no archive open needed
        self.assertEqual(md5, self.vanilla_md5)
        self.assertEqual(md5_of(target), self.vanilla_md5)
        with self.assertRaises(SessionError):      # already vanilla
            s.restore_vanilla(target)

    def test_last_opened_is_persisted(self):
        s = self.mk()
        s.open(self.game)
        s.close()
        cfg = Settings(os.path.join(self.tmp, "cfg"))
        self.assertEqual(cfg.get("last_opened"), os.path.abspath(self.game))

    def test_custom_mode_alone_is_not_a_pending_change(self):
        s = self.mk()
        s.open(self.game)
        s.set_mode(s.proj.by_guid[LEIF], "custom")
        with self.assertRaises(SessionError):
            s.flash()
        s.close()


try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:          # no python3-tk or no display
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter + a display (xvfb-run)")
class GuiPolishTests(_Sandbox):
    """Main window + editor window behaviour on the synthetic archive."""

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.tmp,
            "ANN0140_SETTINGS_DIR": os.path.join(self.tmp, "cfg"),
            "ANN0140_EXPORTS_DIR": os.path.join(self.tmp, "exports"),
            "ANN0140_LOG_FILE": os.path.join(self.tmp, "log"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        from annoedit.gui import app as appmod
        self.appmod = appmod
        # modal messageboxes are patched (recorded, auto
        # answered) so a failing background job FAILS the test instead of
        # hanging it (that is how shipped green under xvfb)
        from guitest import patch_messagebox
        self.mb = patch_messagebox(self)
        self.app = appmod.App(auto_open=False)
        self.addCleanup(self._destroy)
        self.app.open_archive(self.game)
        self.pump()

    def _destroy(self):
        try:
            self.app.ses.close()
            self.app.destroy()
        except Exception:
            pass

    def pump(self, n=5):
        for _ in range(n):
            self.app.update()

    def wait_idle(self, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            self.app.update()
            if not self.app._busy_flag:
                return
            time.sleep(0.02)
        self.fail(f"background job did not finish in {timeout}s "
                  f"(error boxes shown: {self.mb.errors})")

    def select_char(self, guid):
        idx = [q.guid for q in self.app.ses.roster].index(guid)
        self.app.roster.selection_clear(0, "end")
        self.app.roster.selection_set(idx)
        self.app.on_select_char()
        self.pump()
        return idx

    def test_dial_edit_keeps_character_selected(self):
        idx = self.select_char(LEIF)
        path = "Military/MaxUnitCount"
        self.app.tree.selection_set(path)
        self.pump()
        self.app.dials.entry.delete(0, "end")
        self.app.dials.entry.insert(0, "77")
        self.app.dials._commit()
        self.pump()
        self.assertEqual(self.app.ses.changes[LEIF][path], "77")
        self.assertEqual(self.app.roster.curselection(), (idx,))
        self.assertGreater(len(self.app.tree.get_children()), 0)
        self.assertEqual(self.app.tree.selection(), (path,))
        self.assertEqual(self.app.tree.set(path, "new"), "77")
        self.assertIn("1 pending", self.app.roster.get(idx))

    def test_preset_then_switch_character(self):
        idx = self.select_char(LEIF)
        self.app.preset_var.set("The Admiral")
        self.app.on_preset()
        self.pump()
        self.assertEqual(self.app.roster.curselection(), (idx,))
        self.assertEqual(self.app._cur_guid, LEIF)
        self.assertGreater(len(self.app.tree.get_children()), 60)
        # switch: the box follows the new character, nothing is applied
        self.select_char(HILDEGARD)
        # 'Unchanged' since the label change (a
        # modded/other archive with no pending edits on this char).
        self.assertEqual(self.app.preset_var.get(), "Unchanged")
        self.assertIn("The Spider", self.app.preset_box.cget("values"))
        self.assertNotIn(HILDEGARD, self.app.ses.changes)
        # and back again: still The Admiral
        self.select_char(LEIF)
        self.assertEqual(self.app.preset_var.get(), "The Admiral")

    def test_editor_window_does_not_loop_and_syncs(self):
        self.select_char(LEIF)
        self.app.on_open_editor()
        ed = self.app._editors[LEIF]
        calls = {"n": 0}
        real = ed.refresh

        def counting(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        ed.refresh = counting
        for _ in range(15):
            self.app.update()
            time.sleep(0.01)
        self.assertEqual(calls["n"], 0, "editor refreshes while idle")
        # value typed then focus moved away: lands on the LOADED row
        rows = ed.tree.get_children()
        ed.tree.selection_set(rows[0])
        self.pump()
        loaded = ed.table._editing_path
        ed.table.entry.delete(0, "end")
        ed.table.entry.insert(0, "42")
        ed.tree.selection_set(rows[1])
        ed.table._on_entry_focus_out()
        self.pump()
        self.assertEqual(self.app.ses.changes[LEIF][loaded], "42")
        self.assertNotIn(rows[1], self.app.ses.changes[LEIF])
        # main window shows it too, character still selected
        self.assertEqual(self.app.tree.set(loaded, "new"), "42")
        self.assertEqual(self.app._cur_guid, LEIF)

    def test_busy_cleared_after_export(self):
        self.select_char(LEIF)
        self.app.ses.set_dial(self.app._current_profile(),
                              "Military/MaxUnitCount", "50")
        self.app._run_build("export", "polish_test")
        self.wait_idle()
        self.assertEqual(str(self.app.open_btn["state"]), "normal")
        self.assertEqual(str(self.app.flash_btn["state"]), "normal")
        self.assertTrue(os.path.isfile(os.path.join(
            self.tmp, "exports", "data1.rda_polish_test")))

    def _click_and_find_review(self, button):
        """Invoke a toolbar button inside the REAL event loop; -> dialog."""
        found = {}

        def look():
            for w in self.app.winfo_children():
                if isinstance(w, self.appmod.ReviewChangesDialog):
                    found["dlg"] = w
                    found["mapped"] = bool(w.winfo_ismapped())
            self.app.quit()

        self.app.after(50, button.invoke)
        self.app.after(800, look)
        self.app.mainloop()
        return found

    def test_apply_and_save_button_shows_review_window(self):
        # the modal grab waited for visibility from an
        # idle callback, which blocked the dialog from ever being mapped
        self.select_char(LEIF)
        self.app.ses.set_dial(self.app._current_profile(),
                              "Military/MaxUnitCount", "50")
        for button in (self.app.flash_btn, self.app.export_btn):
            found = self._click_and_find_review(button)
            self.assertIn("dlg", found, "review window not created")
            self.assertTrue(found["mapped"], "review window never shown")
            found["dlg"].destroy()
            self.pump()

    def test_relaunch_reopens_last_archive(self):
        self.app.ses.close()
        self.app.destroy()
        app2 = self.appmod.App()         # auto_open=True
        try:
            end = time.time() + 20
            while time.time() < end and (app2.ses.proj is None or
                                         app2._busy_flag):
                app2.update()
                time.sleep(0.02)
            self.assertEqual(app2.ses.source_path, os.path.abspath(self.game))
            self.assertGreater(app2.roster.size(), 0)
        finally:
            app2.ses.close()
            app2.destroy()


if __name__ == "__main__":
    unittest.main()
