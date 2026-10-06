#!/usr/bin/env python3
"""Headless tests for features: named presets + editor-equivalent actions.

The editor window's every action maps onto a Session method, so testing the
Session covers the window. EditorWindow itself is tkinter-only and is
compile/import-checked separately (no display needed).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from annoedit.session import Session, SessionError

from fixture import TEST_RDA, HAVE_RDA


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class NamedPresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cepreset_")
        self.src = os.path.join(self.tmp, "data1.rda")
        import shutil
        shutil.copyfile(TEST_RDA, self.src)
        # redirect the user preset dir to the temp dir
        self._patch = mock.patch("annoedit.session.USER_PRESETS",
                                  os.path.join(self.tmp, "presets"))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk(self):
        return Session(backup_root=os.path.join(self.tmp, "backups"),
                         exports_root=os.path.join(self.tmp, "exports"))

    def _guid(self, s, name_substr):
        for q in s.roster:
            if name_substr.lower() in q.name.lower():
                return q
        raise AssertionError(f"no profile matching {name_substr}")

    def test_named_preset_roundtrip(self):
        s = self.mk()
        s.open(self.src)
        p = self._guid(s, "Giovanni")
        s.set_dial(p, "Military/MaxUnitCount", "70")
        s.set_dial(p, "ShipFight/ShipAttackIntervall", "30000")
        path = s.save_named_preset(p, "My Giovanni Build")
        self.assertTrue(os.path.isfile(path))
        # fresh session, same profile: clear then reload the preset
        s.set_mode(p, "vanilla")
        self.assertNotIn(p.guid, s.changes)
        dials = s.load_named_preset(p, "My Giovanni Build")
        self.assertEqual(dials["Military/MaxUnitCount"], "70")
        self.assertEqual(dials["ShipFight/ShipAttackIntervall"], "30000")
        self.assertEqual(s.changes[p.guid]["Military/MaxUnitCount"], "70")
        self.assertEqual(s.modes[p.guid], "custom")
        # listed under its saved name
        self.assertIn("My Giovanni Build", s.named_presets())
        s.close()

    def test_save_requires_pending(self):
        s = self.mk()
        s.open(self.src)
        p = self._guid(s, "Giovanni")
        with self.assertRaises(SessionError):
            s.save_named_preset(p, "empty")
        s.close()

    def test_load_rejects_foreign_character(self):
        s = self.mk()
        s.open(self.src)
        p = self._guid(s, "Giovanni")
        s.set_dial(p, "Military/MaxUnitCount", "70")
        s.save_named_preset(p, "gio only")
        other = self._guid(s, "Leif")
        with self.assertRaises(SessionError):
            s.load_named_preset(other, "gio only")
        s.close()

    def test_editor_action_set_equivalence(self):
        """The exact action sequence the editor window performs."""
        s = self.mk()
        s.open(self.src)
        p = self._guid(s, "Hildegard")
        # 1. apply persona via editor's Load preset picker
        dials = s.set_mode(p, "The Spider")
        self.assertGreater(len(dials), 50)
        # 2. per-dial edits on top (set -> override; clear -> persona value)
        persona_val = dials["Espionage/SpyDetectValue"]
        s.set_dial(p, "Espionage/SpyDetectValue", "60")
        self.assertEqual(s.changes[p.guid]["Espionage/SpyDetectValue"], "60")
        s.set_dial(p, "Espionage/SpyDetectValue", None)
        # clearing a manual override restores the persona value, not a loss
        self.assertEqual(s.changes[p.guid]["Espionage/SpyDetectValue"],
                         persona_val)
        # 3. save the tuned state as a named preset, clear, reload
        s.save_named_preset(p, "spider tuned")
        s.set_mode(p, "vanilla")
        loaded = s.load_named_preset(p, "spider tuned")
        self.assertEqual(loaded["Espionage/SpyDetectValue"], persona_val)
        s.close()


if __name__ == "__main__":
    unittest.main()
