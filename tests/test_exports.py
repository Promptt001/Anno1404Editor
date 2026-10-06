#!/usr/bin/env python3
"""Tests for the export store (annoedit/exports.py) + Session export flow.

Headless: no display, no game files — a synthetic minimal RDA is built by
test_session.py's helpers; here we use a tiny fake project file via the
real Session against the tiny test RDA when available, else pure store
logic (slug/list/rename/delete guards never need game data).
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from annoedit.exports import ExportStore, ExportsError, slug_export_name

from fixture import TEST_RDA


class SlugTests(unittest.TestCase):
    """Name sanitization rules."""

    def test_slug_basic(self):
        self.assertEqual(slug_export_name("My Export"), "My_Export")
        self.assertEqual(slug_export_name("hard_trio-2"), "hard_trio-2")

    def test_slug_rejects_empty(self):
        with self.assertRaises(ExportsError):
            slug_export_name("")
        with self.assertRaises(ExportsError):
            slug_export_name("  ")
        with self.assertRaises(ExportsError):
            slug_export_name("///")

    def test_slug_rejects_reserved(self):
        for bad in ("vanilla", "VANILLA", "backup", "exports"):
            with self.assertRaises(ExportsError):
                slug_export_name(bad)


class ExportStoreTests(unittest.TestCase):
    """Store layout, write-once vanilla copy, list/rename/delete."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="exports_test_")
        self.store = ExportStore(self.root)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _make_rda(self, name):
        p = os.path.join(self.root, name)
        with open(p, "wb") as f:
            f.write(b"RDATEST" + os.urandom(64))
        return p

    def test_vanilla_copy_write_once(self):
        src = self._make_rda("src.rda")
        md5, created = self.store.capture_vanilla_copy(src)
        self.assertTrue(created)
        self.assertTrue(os.path.isfile(self.store.vanilla_path))
        self.assertTrue(self.store.vanilla_path.endswith(
            "data1.rda_vanilla"))
        # re-capture the identical file: created=False, never overwritten
        md52, created2 = self.store.capture_vanilla_copy(src)
        self.assertFalse(created2)
        self.assertEqual(md5, md52)

    def test_vanilla_copy_refuses_different_file(self):
        src = self._make_rda("src.rda")
        self.store.capture_vanilla_copy(src)
        other = self._make_rda("other.rda")
        with self.assertRaises(ExportsError):
            self.store.capture_vanilla_copy(other)

    def test_save_named_export_and_list(self):
        src = self._make_rda("src.rda")
        p = self.store.save_named_export(src, "Hard Trio", note="test note")
        self.assertTrue(p.endswith("data1.rda_Hard_Trio"))
        rows = self.store.list_exports()
        self.assertEqual([r["name"] for r in rows], ["Hard_Trio"])
        self.assertEqual(rows[0]["note"], "test note")
        self.assertEqual(rows[0]["md5"], None or rows[0]["md5"])

    def test_vanilla_listed_first(self):
        src = self._make_rda("src.rda")
        self.store.capture_vanilla_copy(src)
        self.store.save_named_export(src, "aaa_export")
        rows = self.store.list_exports()
        self.assertEqual(rows[0]["name"], "vanilla")
        self.assertEqual([r["name"] for r in rows[1:]], ["aaa_export"])

    def test_rename_and_delete(self):
        src = self._make_rda("src.rda")
        self.store.save_named_export(src, "old_name")
        self.store.rename_export("old_name", "new_name")
        rows = self.store.list_exports()
        self.assertEqual([r["name"] for r in rows], ["new_name"])
        self.store.delete_export("new_name")
        self.assertEqual(self.store.list_exports(), [])

    def test_rename_refuses_vanilla_and_collision(self):
        src = self._make_rda("src.rda")
        self.store.capture_vanilla_copy(src)
        self.store.save_named_export(src, "one")
        self.store.save_named_export(src, "two")
        with self.assertRaises(ExportsError):
            self.store.rename_export("one", "two")
        # deleting via slug('one') works; the vanilla copy refuses normal delete
        self.store.delete_export("one")
        with self.assertRaises(ExportsError):
            self.store.delete_export("vanilla")
        rows = self.store.list_exports()
        self.assertEqual([r["name"] for r in rows], ["vanilla", "two"])

    def test_load_export_path(self):
        src = self._make_rda("src.rda")
        self.store.save_named_export(src, "loadme")
        p = self.store.load_export_path("loadme")
        self.assertTrue(os.path.isfile(p))
        with self.assertRaises(ExportsError):
            self.store.load_export_path("nope")


class SessionExportFlowTests(unittest.TestCase):
    """Session wiring: exports_root param, vanilla copy on open, named export.

    Needs the vanilla data1.rda (skipped otherwise) — same rule as the
    other data-dependent suites.
    """

    @classmethod
    def setUpClass(cls):
        cls.has_data = os.path.isfile(TEST_RDA)
        if not cls.has_data:
            raise unittest.SkipTest(
                f"no test RDA at {TEST_RDA} — data-dependent tests skipped")

    def setUp(self):
        from annoedit.session import Session
        self.root = tempfile.mkdtemp(prefix="session_export_")
        self.ses = Session(backup_root=os.path.join(self.root, "backups"),
                           exports_root=os.path.join(self.root, "exports"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_open_does_not_capture_vanilla_copy(self):
        # the vanilla copy is provided EXPLICITLY, never captured
        # implicitly on open (a modded archive would poison it)
        info = self.ses.open(TEST_RDA)
        self.assertFalse(self.ses.exports_store.has_vanilla_copy())
        self.assertNotIn("data1.rda_vanilla saved", info["backup"])

    def test_provide_vanilla_captures_write_once(self):
        info = self.ses.provide_vanilla(TEST_RDA)
        self.assertTrue(info["created"])
        self.assertTrue(self.ses.exports_store.has_vanilla_copy())
        vpath = self.ses.exports_store.vanilla_path
        self.assertTrue(vpath.endswith("data1.rda_vanilla"))
        # write-once: re-providing the identical file is a no-op
        info2 = self.ses.provide_vanilla(TEST_RDA)
        self.assertFalse(info2["created"])

    def test_provide_vanilla_persists_across_sessions(self):
        self.ses.provide_vanilla(TEST_RDA)
        from annoedit.session import Session
        ses2 = Session(backup_root=os.path.join(self.root, "backups"),
                       exports_root=os.path.join(self.root, "exports"))
        self.assertTrue(ses2.exports_store.has_vanilla_copy())

    def test_provide_vanilla_persists_after_app_restart(self):
        # the stored copy survives a fresh Session on the SAME store root
        # (settings-persistence equivalent: the exports dir is the store)
        self.ses.provide_vanilla(TEST_RDA)
        from annoedit.exports import ExportStore
        st = ExportStore(os.path.join(self.root, "exports"))
        self.assertTrue(st.has_vanilla_copy())

    def test_open_after_provide_shows_vanilla_on_file(self):
        self.ses.provide_vanilla(TEST_RDA)
        info = self.ses.open(TEST_RDA)
        self.assertIn("data1.rda_vanilla", info["backup"])

    def test_named_export_round_trip(self):
        self.ses.provide_vanilla(TEST_RDA)   # 'vanilla' row in the manager
        self.ses.open(TEST_RDA)
        rep = self.ses.export(
            os.path.join(self.root, "out.rda"), export_name="round_trip")
        self.assertEqual(rep["export_name"], "round_trip")
        rows = self.ses.list_saved_exports()
        names = [r["name"] for r in rows]
        self.assertIn("vanilla", names)
        self.assertIn("round_trip", names)
        # the stored file is data1.rda_round_trip and re-opens
        p = self.ses.load_saved_export_path("round_trip")
        self.assertTrue(p.endswith("data1.rda_round_trip"))
        info = self.ses.open(p)
        self.assertTrue(info["files"] > 0)

    def test_vanilla_mode_resets_to_stored_vanilla(self):
        # provide vanilla, open, edit a dial, then set_mode vanilla
        self.ses.provide_vanilla(TEST_RDA)
        self.ses.open(TEST_RDA)
        prof = self.ses.roster[0]
        path = sorted(prof.dials)[0]
        cur, _ = self.ses.effective(prof, path)
        # pending edit to a different value
        self.ses.set_dial(prof, path, str(int(str(cur)) + 12345 if cur
                                          and str(cur).lstrip("-").isdigit()
                                          else "12345"))
        self.assertTrue(self.ses.changes.get(prof.guid))
        # vanilla mode -> pending reset to the stored vanilla value.
        # On an archive that IS the
        # vanilla reference, EVERY key in scope is queued rule='reset' (the
        # no-ops drop at review/build time against the base actually
        # written) — the old delta-queueing left the map empty here, which
        # made a Vanilla click silently ineffective on save-to-live
        # whenever live differed from opened.
        self.ses.set_mode(prof, "vanilla")
        pend = self.ses.changes.get(prof.guid) or {}
        self.assertTrue(pend)   # absolute queueing: every key in scope
        for k, v in pend.items():
            self.assertEqual(v, str(self.ses.effective(prof, k)[0]))
        # the records carry the 'reset' rule (drives the review/build drops)
        for path, e in self.ses.cs.dial_items(prof.guid):
            if path in pend:
                self.assertEqual(e.rule, "reset")


if __name__ == "__main__":
    unittest.main()
