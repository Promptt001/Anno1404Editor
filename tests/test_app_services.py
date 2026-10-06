#!/usr/bin/env python3
"""App services: i18n, activity log, settings, picker, banners.

Covers the English translations of all German dial descriptions (with a
safe fallback), the app log (append, rotate, env override), the settings
store (persist, env override), the picker's filetypes order, and the
first-run banner logic (no vanilla copy / live path unset).
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fixture import TEST_RDA, HAVE_RDA, real_rda


class I18nTests(unittest.TestCase):
    """The German->English dial-description display translations."""

    @real_rda
    def test_translate_known_string(self):
        # use a REAL schema string from the actual archive (hand-typed
        # strings never byte-match the game's exact German)
        from annoedit.core import ModProject
        from annoedit.i18n import EN_TRANSLATIONS, translate
        self.assertGreaterEqual(len(EN_TRANSLATIONS), 367)
        proj = ModProject(TEST_RDA)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(proj.schema_text)
        s = None
        for vd in root.iter("ValueDefinition"):
            d = vd.find("Description")
            if d is not None and d.text and d.text.strip() and \
                    any(c in d.text for c in "äöüß"):
                s = d.text.strip()
                break
        self.assertIsNotNone(s, "no German description found in schema")
        self.assertNotEqual(translate(s), s,
                            f"German string left untranslated: {s!r}")

    def test_translate_falls_back_to_original(self):
        from annoedit.i18n import translate
        s = "definitely not a known schema string"
        self.assertEqual(translate(s), s)
        self.assertEqual(translate(""), "")

    def test_no_german_umlaute_in_translations(self):
        from annoedit.i18n import EN_TRANSLATIONS
        bad = [v for v in EN_TRANSLATIONS.values()
               if any(c in v for c in "äöüßÄÖÜ")]
        self.assertEqual(bad, [])

    @unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
    def test_parse_schema_yields_english_docs(self):
        from annoedit.core import ModProject
        from annoedit.model import parse_schema
        proj = ModProject(TEST_RDA)
        docs, _defaults = parse_schema(proj.schema_text)
        german = sum(1 for cat in docs.values() for e in cat.values()
                     if any(c in e.get("desc", "") for c in "äöüß"))
        self.assertEqual(german, 0)


class AppLogTests(unittest.TestCase):
    """The append-only activity log (~/.anno1404gameeditor/annoedit.log)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="applog_")
        self.logfile = os.path.join(self.tmp, "annoedit.log")
        os.environ["ANN0140_LOG_FILE"] = self.logfile
        self.addCleanup(os.environ.pop, "ANN0140_LOG_FILE", None)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        from annoedit import applog
        applog._CACHE = None  # not used, but reset any state
        import importlib
        importlib.reload(applog)

    def test_log_writes_timestamped_lines(self):
        from annoedit.applog import log, tail
        log("startup", pid=123)
        log("open", path="/x/data1.rda", md5="aa4546d0d9f4")
        lines = tail(10)
        self.assertEqual(len(lines), 2)
        self.assertIn("startup", lines[0])
        self.assertIn("pid=123", lines[0])
        self.assertIn("open", lines[1])
        self.assertIn("path=/x/data1.rda", lines[1])

    def test_log_rotates_when_huge(self):
        from annoedit.applog import log, MAX_BYTES
        with open(self.logfile, "a", encoding="utf-8") as f:
            f.write("x" * (MAX_BYTES + 10))
        log("after_huge")
        self.assertTrue(os.path.isfile(self.logfile + ".1"))
        self.assertTrue(os.path.getsize(self.logfile) < MAX_BYTES + 200)
        self.assertTrue(any("after_huge" in l for l in open(self.logfile)))

    def test_log_never_raises(self):
        from annoedit.applog import log
        os.environ["ANN0140_LOG_FILE"] = "/proc/nonexistent_dir/x.log"
        log("must_not_raise")
        os.environ["ANN0140_LOG_FILE"] = self.logfile


class SettingsTests(unittest.TestCase):
    """The persistent settings store (live_path etc.)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="appset_")
        os.environ["ANN0140_SETTINGS_DIR"] = self.tmp
        self.addCleanup(os.environ.pop, "ANN0140_SETTINGS_DIR", None)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_set_get_persist_and_delete(self):
        from annoedit.appsettings import Settings
        s = Settings()
        self.assertIsNone(s.get("live_path"))
        s.set("live_path", "/game/addon/data1.rda")
        s2 = Settings()   # fresh instance reads the same file
        self.assertEqual(s2.get("live_path"), "/game/addon/data1.rda")
        s2.delete("live_path")
        self.assertIsNone(Settings().get("live_path"))

    def test_unsupported_value_rejected(self):
        from annoedit.appsettings import Settings, SettingsError
        s = Settings()
        with self.assertRaises(SettingsError):
            s.set("x", {"not": "serializable"})

    def test_corrupt_file_falls_back_to_empty(self):
        from annoedit.appsettings import Settings
        with open(os.path.join(self.tmp, "settings.json"), "w") as f:
            f.write("{not json")
        s = Settings()
        self.assertEqual(s.as_dict(), {})


try:
    import tkinter  # noqa
    _HAVE_TK = True
except ImportError:
    _HAVE_TK = False


@unittest.skipUnless(_HAVE_TK, "python3-tk not installed")
class PickerFiletypesTests(unittest.TestCase):
    """The tkinter filetypes-order live-test bug (filter matched nothing)."""

    def test_picker_system_dialog_filetypes_label_first(self):
        # Tkinter filetypes are (LABEL, pattern) — the old
        # (pattern, label) tuples in picker.py's system-dialog fallback and
        # the unused app.PICKER constant were inverted. PICKER is deleted;
        # the fallback's tuples are verified here.
        import re as _re
        import annoedit.gui.picker as pickmod
        src = open(pickmod.__file__, encoding="utf-8").read()
        m = _re.search(r"filetypes=\[(.*?)\]", src, _re.S)
        self.assertTrue(m, "filetypes= not found in picker.py")
        # first tuple element must be a LABEL (a word, not a glob)
        # a tuple with a GLOB first element is the (pattern, label) bug
        self.assertNotIn('("*', m.group(1),
                        'filetypes tuples must be (label, pattern) — '
                        'a glob first is the inverted order')
        self.assertIn('("RDA archive"', m.group(1))

    def test_picker_module_imports_headless(self):
        import annoedit.gui.picker as p
        self.assertTrue(callable(p.ask_path))


class BannerStateTests(unittest.TestCase):
    """Banner logic: vanilla copy unset -> red banner; live path unset."""

    @unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
    def test_session_banner_inputs(self):
        from annoedit.appsettings import Settings
        from annoedit.session import Session
        tmp = tempfile.mkdtemp(prefix="banner_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ses = Session(backup_root=os.path.join(tmp, "bk"),
                      exports_root=os.path.join(tmp, "ex"),
                      settings=Settings(os.path.join(tmp, "cf")))
        # neither vanilla copy nor live path -> both banners required
        self.assertFalse(ses.exports_store.has_vanilla_copy())
        self.assertIsNone(ses.live_path())
        ses.provide_vanilla(TEST_RDA)
        self.assertTrue(ses.exports_store.has_vanilla_copy())
        # live path still unset -> second banner still required
        self.assertIsNone(ses.live_path())
        ses.set_live_path(TEST_RDA)
        self.assertEqual(ses.live_path(), os.path.abspath(TEST_RDA))
        # persisted across a fresh Session with the same settings root
        ses2 = Session(backup_root=os.path.join(tmp, "bk"),
                       exports_root=os.path.join(tmp, "ex"),
                       settings=Settings(os.path.join(tmp, "cf")))
        self.assertEqual(ses2.live_path(), os.path.abspath(TEST_RDA))
        ses.close()
        ses2.close()


if __name__ == "__main__":
    unittest.main()
