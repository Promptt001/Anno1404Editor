#!/usr/bin/env python3
"""Export and persona-loading regressions.

- GUI "Save as export" builds into the exports store through
  Session.export_named, never by constructing a store path.
- One malformed persona JSON does not stop the app from starting; the
  failure is collected in preset_load_errors.
- Saved named presets (presets/) can never shadow personas: user
  personas live in their own dir (personas/).
- A user persona whose name collides with a shipped one is skipped.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixture import TEST_RDA, HAVE_RDA  # noqa: E402


def _tmp_settings(root):
    from annoedit.appsettings import Settings
    return Settings(os.path.join(root, "cfg"))


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class ExportNamedTests(unittest.TestCase):
    """The GUI export path (headless — the GUI button calls this)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p0f01_")
        shutil.copyfile(TEST_RDA, os.path.join(self.tmp, "data1.rda"))
        from annoedit.session import Session
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=_tmp_settings(self.tmp))
        self.ses.open(os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        self.ses.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_named_builds_into_store(self):
        p = self.ses.proj.by_guid["1645021"]
        self.ses.set_dial(p, "Military/MaxUnitCount", "50")
        rep = self.ses.export_named("mine")
        dest = rep["export_stored_path"]
        self.assertTrue(os.path.isfile(dest))
        # exactly data1.rda_mine in the store + its meta, listed by name
        names = [e["name"] for e in self.ses.list_saved_exports()]
        self.assertIn("mine", names)
        meta = json.load(open(dest + ".meta.json"))
        self.assertEqual(meta["name"], "mine")
        self.assertEqual(meta["md5"], rep["md5"])
        # no .tmp leftovers on the success path
        self.assertEqual([f for f in os.listdir(os.path.dirname(dest))
                          if f.endswith(".tmp")], [])

    def test_export_named_bad_name_refused_and_leaves_no_tmp(self):
        with self.assertRaises(Exception):
            self.ses.export_named("!!")
        root = self.ses.exports_store.root
        self.assertEqual([f for f in os.listdir(root) if f.endswith(".tmp")],
                         [])

    def test_old_gui_path_is_still_refused(self):
        """The ORIGINAL broken GUI call (build straight into the store)
        must still be refused by _guard_write — the protection stays."""
        from annoedit.session import SessionError
        out = os.path.join(self.ses.exports_store.root, "data1.rda_mine")
        with self.assertRaises(SessionError):
            self.ses.export(out)


class PresetLoadingTests(unittest.TestCase):
    """Guarded persona loading + the personas/presets store split."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p0f04_")
        # shipped personas = the repo's presets/ dir
        repo_presets = os.path.join(os.path.dirname(__file__), "..", "annoedit", "presets")
        self.persona_dir = os.path.join(self.tmp, "personas")   # user personas
        self.preset_dir = os.path.join(self.tmp, "presets")     # named presets
        os.makedirs(self.persona_dir)
        os.makedirs(self.preset_dir)
        self.dirs = (repo_presets, self.persona_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mk_session(self):
        from annoedit.session import Session
        return Session(backup_root=os.path.join(self.tmp, "b"),
                       exports_root=os.path.join(self.tmp, "e"),
                       settings=_tmp_settings(self.tmp),
                       persona_dirs=self.dirs)

    def test_malformed_persona_file_does_not_stop_startup(self):
        # an unknown relations kind used to propagate out of
        # Session.__init__ and kill every CLI command + the GUI
        bad = {"name": "oops", "characters": {
            "Leif Jorgensen": {"dials": {"Military/MaxUnitCount": "77"},
                               "relations": {"Enemies": [1]}}}}
        with open(os.path.join(self.persona_dir, "bad.json"), "w") as f:
            json.dump(bad, f)
        s = self._mk_session()          # must NOT raise
        self.assertTrue(s.preset_load_errors)
        self.assertNotIn("oops", s.personas)
        self.assertIn("The Admiral", s.personas)   # shipped ones still load

    def test_dials_as_list_does_not_stop_startup(self):
        bad = {"name": "oops2", "characters": {
            "Leif Jorgensen": {"dials": ["a", "b"]}}}
        with open(os.path.join(self.persona_dir, "bad2.json"), "w") as f:
            json.dump(bad, f)
        s = self._mk_session()          # must NOT raise
        self.assertTrue(s.preset_load_errors)
        self.assertNotIn("oops2", s.personas)

    def test_named_presets_never_become_personas(self):
        # a named preset saved into presets/ (the OLD shared dir)
        # must NOT hijack the persona list even if it carries a persona
        # name — 'presets' is named-preset territory only
        hijack = {"name": "The Admiral", "description": "fake",
                  "characters": {"Leif Jorgensen": {"dials": {"x": "1"}}}}
        with open(os.path.join(self.preset_dir, "hijack.json"), "w") as f:
            json.dump(hijack, f)
        # The default persona search path must NOT include the named-
        # preset dir (otherwise this hijack file could shadow a shipped
        # persona)
        from annoedit.session import _persona_dirs
        from annoedit.homevar import user_personas_dir, user_presets_dir
        for d in _persona_dirs():
            self.assertNotEqual(os.path.normpath(d),
                                os.path.normpath(self.preset_dir))
            self.assertNotEqual(os.path.normpath(d),
                                os.path.normpath(user_presets_dir()))
        # and the user persona dir IS in it
        self.assertIn(os.path.normpath(user_personas_dir()),
                      [os.path.normpath(d) for d in _persona_dirs()])

    def test_user_persona_in_personas_dir_loads(self):
        good = {"name": "My Persona", "description": "user-authored",
                "characters": {"Leif Jorgensen": {
                    "dials": {"Military/MaxUnitCount": "60"}}}}
        with open(os.path.join(self.persona_dir, "mine.json"), "w") as f:
            json.dump(good, f)
        s = self._mk_session()
        self.assertIn("My Persona", s.personas)
        self.assertEqual(s.preset_load_errors, [])

    def test_shipped_persona_name_cannot_be_hijacked(self):
        # a user file named like a shipped persona is skipped
        fake = {"name": "The Admiral", "description": "fake",
                "characters": {"Leif Jorgensen": {
                    "dials": {"Military/MaxUnitCount": "1"}}}}
        with open(os.path.join(self.persona_dir, "fake.json"), "w") as f:
            json.dump(fake, f)
        s = self._mk_session()
        self.assertIn("The Admiral", s.personas)
        # the shipped one won: its Leif target has the real dial count
        leif = s.personas["The Admiral"]["targets"]["Leif Jorgensen"]
        self.assertGreater(len(leif["dials"]), 1)
        self.assertTrue(any("already defined by an earlier dir" in e
                            for e in s.preset_load_errors))


if __name__ == "__main__":
    unittest.main()
