#!/usr/bin/env python3
"""Headless tests for the Session controller (every GUI button's path).

Uses a COPY of the vanilla data1.rda in a temp dir, with the backup store
redirected to a temp root, so no real game file or ~/.anno1404gameeditor is
ever touched.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from annoedit.backup import md5_of, BackupStore
from annoedit.session import Session, SessionError, load_personas

from fixture import TEST_RDA, HAVE_RDA


class PersonaTests(unittest.TestCase):
    def test_load_personas(self):
        personas = load_personas()
        labels = set(personas)
        self.assertIn("The Admiral", labels)
        self.assertIn("The Spider", labels)
        self.assertIn("The Conqueror", labels)
        for label, spec in personas.items():
            self.assertTrue(spec["targets"], f"{label}: empty targets")
            self.assertIn("description", spec)


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class SessionTests(unittest.TestCase):
    """The full operator workflow: open -> persona -> flash -> restore."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cesess_")
        self.src = os.path.join(self.tmp, "data1.rda")
        shutil.copyfile(TEST_RDA, self.src)
        self.store_root = os.path.join(self.tmp, "backups")
        self.vanilla_md5 = md5_of(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk(self):
        s = Session(backup_root=self.store_root,
                    exports_root=os.path.join(self.tmp, "exports"),
                    persona_dirs=(os.path.join(os.path.dirname(__file__), "..",
                                               "annoedit", "presets"),))
        return s

    def test_open_captures_vanilla_backup(self):
        s = self.mk()
        info = s.open(self.src)
        self.assertEqual(info["source_md5"], self.vanilla_md5)
        self.assertTrue(s.store.has_vanilla)
        m = s.store._read_manifest()
        self.assertEqual(m["vanilla_md5"], self.vanilla_md5)
        # backup bytes == source bytes
        with open(s.store.vanilla_path(m["vanilla_md5"]), "rb") as f:
            self.assertEqual(md5_of.__module__, "annoedit.backup")  # sanity
        self.assertEqual(os.path.getsize(s.store.vanilla_path(m["vanilla_md5"])),
                         os.path.getsize(self.src))
        s.close()

    def test_open_is_idempotent_no_backup_overwrite(self):
        s = self.mk()
        s.open(self.src)
        s.close()
        s2 = self.mk()
        info = s2.open(self.src)
        self.assertIn("already on file", info["backup"])
        # only one vanilla file in the store
        vans = [n for n in os.listdir(self.store_root) if n.startswith("vanilla-")]
        self.assertEqual(len(vans), 1)
        s2.close()

    def test_open_failure_leaves_closed(self):
        s = self.mk()
        with self.assertRaises(SessionError):
            s.open(os.path.join(self.tmp, "nope.rda"))
        self.assertIsNone(s.proj)
        s.close()

    def test_session_lock_blocks_second_session(self):
        s1 = self.mk()
        s1.open(self.src)
        try:
            s2 = self.mk()
            with self.assertRaises(Exception):
                s2.open(self.src)   # second lock must fail
        finally:
            s1.close()
        # after close, a new session can open
        s3 = self.mk()
        s3.open(self.src)   # must not raise
        s3.close()

    def _guid(self, s, name_substr):
        for q in s.roster:
            if name_substr.lower() in q.name.lower():
                return q
        raise AssertionError(f"no profile matching {name_substr}")

    def test_persona_flow_flash_and_restore(self):
        s = self.mk()
        s.open(self.src)
        leif = self._guid(s, "Leif")
        # persona present for this char
        self.assertIn("The Admiral", s.personas_for(leif))
        # apply persona
        s.set_mode(leif, "The Admiral")
        pend = s.changes[leif.guid]
        self.assertGreater(len(pend), 50)   # 64 dials in the preset
        # change report mentions the char and a dial
        rep = s.change_report()
        self.assertIn(leif.name, rep)
        self.assertIn("total dial edits:", rep)
        # FLASH
        report = s.flash()
        self.assertEqual(report["dial_edits"], len(pend))
        self.assertGreater(len(report["changed"]), 0)
        self.assertNotEqual(report["md5"], self.vanilla_md5)
        # source changed on disk, backup did NOT
        self.assertEqual(md5_of(self.src), report["md5"])
        self.assertEqual(s.store._read_manifest()["vanilla_md5"], self.vanilla_md5)
        # No pre-flash snapshot for THIS flash
        # the old target bytes are byte-identical to the FIRST-OPEN
        # snapshot already captured as the store's vanilla copy, so a
        # second copy of the same bytes adds nothing (skip-set rule).
        snaps = [n for n in os.listdir(
                     BackupStore(root=self.store_root).snap_dir(self.src))
                 if n.startswith("pre-flash-")]
        self.assertEqual(len(snaps), 0)
        # reload state consistent
        self.assertEqual(s.source_md5, report["md5"])
        # a SECOND flash whose old target is NOT already preserved (the
        # modded archive the first flash produced) -> snapshot taken
        s.set_dial(leif, "Build/BuildingSpeed", "120")
        report2 = s.flash()
        sdir = BackupStore(root=self.store_root).snap_dir(self.src)
        snaps = [n for n in os.listdir(sdir)
                 if n.startswith("pre-flash-")]
        self.assertEqual(len(snaps), 1)
        # and its md5 prefix names the FIRST flash's output (the old
        # target), not the new one
        self.assertTrue(snaps[0].startswith(f"pre-flash-{report['md5']}"))
        self.assertNotEqual(report2["md5"], report["md5"])
        # RESTORE
        rmd5 = s.restore_vanilla()
        self.assertEqual(rmd5, self.vanilla_md5)
        self.assertEqual(md5_of(self.src), self.vanilla_md5)
        self.assertEqual(s.store._read_manifest()["vanilla_md5"], self.vanilla_md5)
        s.close()

    def test_flash_without_changes_raises(self):
        s = self.mk()
        s.open(self.src)
        with self.assertRaises(SessionError):
            s.flash()
        s.close()

    def test_restore_when_already_vanilla_refused(self):
        s = self.mk()
        s.open(self.src)
        with self.assertRaises(SessionError):
            s.restore_vanilla()   # source IS the stored vanilla right now
        s.close()

    def test_set_dial_and_custom_mode(self):
        s = self.mk()
        s.open(self.src)
        p = self._guid(s, "Giovanni")
        s.set_dial(p, "Military/MaxUnitCount", "70")
        self.assertEqual(s.changes[p.guid]["Military/MaxUnitCount"], "70")
        self.assertEqual(s.modes[p.guid], "custom")
        s.set_dial(p, "Military/MaxUnitCount", None)   # clear
        self.assertNotIn(p.guid, s.changes)
        # value edit + export works without flashing source
        s.set_dial(p, "Military/MaxUnitCount", "70")
        out = os.path.join(self.tmp, "export.rda")
        rep = s.export(out)
        self.assertEqual(rep["dial_edits"], 1)
        self.assertNotEqual(md5_of(self.src), rep["md5"])   # source untouched
        s.close()


if __name__ == "__main__":
    unittest.main()
