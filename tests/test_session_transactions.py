#!/usr/bin/env python3
"""Session transactions and write locking.

- set_mode / load_named_preset are transactional: a persona or preset
  whose second value fails validation leaves pending edits and the mode
  label untouched.
- A failed open preserves the current archive and its pending edits.
- Every write takes the store flock: a second, unopened Session cannot
  restore while another instance holds the lock; an opened session's
  own writes still work (the flock is re-entrant per store).
- flash(snapshot=...): edits queued while a build runs are neither in
  the build nor dropped; they stay pending.
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


def _settings(root):
    from annoedit.appsettings import Settings
    return Settings(os.path.join(root, "cfg"))


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class TransactionalSetModeTests(unittest.TestCase):
    """Set_mode on a candidate ChangeSet — all-or-nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2f06_")
        shutil.copyfile(TEST_RDA, os.path.join(self.tmp, "data1.rda"))
        # a persona file whose SECOND dial fails validation
        self.pdir = os.path.join(self.tmp, "personas")
        os.makedirs(self.pdir, exist_ok=True)
        with open(os.path.join(self.pdir, "bad.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"name": "Bad", "characters": {"Leif Jorgensen": {
                "dials": {"Military/MaxUnitCount": "77",
                          "Military/AttackDelay": "fast"}}}}, f,
                ensure_ascii=False)
        from annoedit.session import Session
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=_settings(self.tmp),
            persona_dirs=(self.pdir,))
        self.ses.open(os.path.join(self.tmp, "data1.rda"))
        self.L = self.ses.proj.by_guid["1645021"]

    def tearDown(self):
        self.ses.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bad_persona_rolls_back_user_edit(self):
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        from annoedit.session import SessionError
        with self.assertRaises(SessionError):
            self.ses.set_mode(self.L, "Bad")
        # the user's edit survived; NOTHING of the persona half-applied
        self.assertEqual(self.ses.changes[self.L.guid],
                         {"Build/BuildingSpeed": "150"})
        # the mode is not 'Bad' — the manual edit's 'custom' stands
        self.assertEqual(self.ses.modes.get(self.L.guid), "custom")

    def test_good_persona_replaces_profile_edits(self):
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        # normalized persona shape (as load_personas produces): targets
        # keyed by character name, dials as {path: value}
        self.ses.personas["Good"] = {
            "targets": {"Leif Jorgensen": {
                "dials": {"Military/MaxUnitCount": "77",
                          "Build/BuildingSpeed": "80"},
                "relations": {}}}}
        self.ses.set_mode(self.L, "Good")
        self.assertEqual(self.ses.changes[self.L.guid]["Build/BuildingSpeed"],
                         "80")
        self.assertEqual(self.ses.modes.get(self.L.guid), "Good")

    def test_named_preset_failure_rolls_back(self):
        # save a good preset, then hand-load a BROKEN one by the same name
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        self.ses.save_named_preset(self.L, "mine")
        p = self.ses.named_preset_path("mine")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"name": "mine", "characters": {"Leif Jorgensen": {
                "dials": {"Build/BuildingSpeed": "70",
                          "Military/AttackDelay": "fast"}}}}, f,
                ensure_ascii=False)
        from annoedit.session import SessionError
        with self.assertRaises(SessionError):
            self.ses.load_named_preset(self.L, "mine")
        self.assertEqual(self.ses.changes[self.L.guid],
                         {"Build/BuildingSpeed": "150"})


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class FailedOpenPreservesSessionTests(unittest.TestCase):
    """A failed open leaves the previous archive + pending intact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2f11_")
        shutil.copyfile(TEST_RDA, os.path.join(self.tmp, "data1.rda"))
        from annoedit.session import Session
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=_settings(self.tmp))
        self.ses.open(os.path.join(self.tmp, "data1.rda"))
        self.L = self.ses.proj.by_guid["1645021"]

    def tearDown(self):
        self.ses.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_corrupt_open_preserves_state(self):
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        bad = os.path.join(self.tmp, "bad.rda")
        with open(bad, "wb") as f:
            f.write(b"\x00" * 5000)
        old_proj, old_src = self.ses.proj, self.ses.source_path
        with self.assertRaises(Exception):
            self.ses.open(bad)
        self.assertIs(self.ses.proj, old_proj)
        self.assertEqual(self.ses.source_path, old_src)
        self.assertEqual(self.ses.changes[self.L.guid],
                         {"Build/BuildingSpeed": "150"})

    def test_missing_file_open_preserves_state(self):
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        old_proj = self.ses.proj
        from annoedit.session import SessionError
        with self.assertRaises(SessionError):
            self.ses.open(os.path.join(self.tmp, "nope.rda"))
        self.assertIs(self.ses.proj, old_proj)
        self.assertIn("Build/BuildingSpeed", self.ses.changes[self.L.guid])

    def test_successful_open_swaps_state(self):
        # the happy path still resets pending state on a real open
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        other = os.path.join(self.tmp, "other.rda")
        shutil.copyfile(TEST_RDA, other)
        self.ses.open(other)
        self.assertEqual(self.ses.source_path, os.path.abspath(other))
        self.assertEqual(self.ses.cs.counts()["dials"], 0)


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class WriteLockTests(unittest.TestCase):
    """Every write op takes the store flock."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2f12_")
        shutil.copyfile(TEST_RDA, os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mk(self, root):
        from annoedit.session import Session
        return Session(backup_root=os.path.join(self.tmp, root),
                       exports_root=os.path.join(self.tmp, "exports"),
                       settings=_settings(self.tmp))

    def test_restore_refused_while_other_instance_holds_lock(self):
        s1 = self._mk("b1")
        s1.open(os.path.join(self.tmp, "data1.rda"))
        # A second session that never opened
        # anything must not be able to restore_vanilla past the lock
        s2 = self._mk("b1")     # SAME store root, different _Flock handle
        live = os.path.join(self.tmp, "live.rda")
        shutil.copyfile(TEST_RDA, live)
        with self.assertRaises(Exception) as cm:
            s2.restore_vanilla(live)
        self.assertIn("lock", str(cm.exception).lower())
        s1.close()

    def test_opened_session_writes_still_work(self):
        # re-entrancy: an OPENED session's own flash/export/restore all
        # pass through _write_lock while it already holds the flock
        s1 = self._mk("b2")
        s1.open(os.path.join(self.tmp, "data1.rda"))
        L = s1.proj.by_guid["1645021"]
        s1.set_dial(L, "Build/BuildingSpeed", "150")
        live = os.path.join(self.tmp, "live2.rda")
        rep = s1.flash(live)            # must NOT BackupError
        self.assertTrue(os.path.isfile(live))
        self.assertGreater(rep["dial_edits"], 0)
        s1.close()

    def test_lock_released_after_close(self):
        s1 = self._mk("b3")
        s1.open(os.path.join(self.tmp, "data1.rda"))
        L = s1.proj.by_guid["1645021"]
        s1.set_dial(L, "Build/BuildingSpeed", "150")
        s1.flash(os.path.join(self.tmp, "live3.rda"))
        s1.close()
        # a fresh session over the SAME store root can now open
        s2 = self._mk("b3")
        s2.open(os.path.join(self.tmp, "data1.rda"))
        s2.close()


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class ConcurrentFlashTests(unittest.TestCase):
    """Edits made during a background build are never lost."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2f13_")
        shutil.copyfile(TEST_RDA, os.path.join(self.tmp, "data1.rda"))
        from annoedit.session import Session
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=_settings(self.tmp))
        self.ses.open(os.path.join(self.tmp, "data1.rda"))
        self.L = self.ses.proj.by_guid["1645021"]
        self.H = self.ses.proj.by_guid["1645023"]

    def tearDown(self):
        self.ses.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_edit_survives_in_place_flash(self):
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        # the GUI pattern: freeze on the Tk thread, build on a worker
        snap = self.ses.cs.snapshot()
        self.ses.set_dial(self.H, "Build/BuildingSpeed", "99")  # during build
        self.ses.flash(snapshot=snap)
        # the snapshot's edit was applied and CLEARED (subtractive)…
        self.assertNotIn("Build/BuildingSpeed",
                          self.ses.changes.get(self.L.guid, {}))
        # …the concurrent edit was NOT in the build and stays PENDING
        self.assertEqual(
            self.ses.changes.get(self.H.guid, {}).get("Build/BuildingSpeed"),
            "99")
        # and the flashed archive carries the BUILT edit only
        from annoedit.core import ModProject
        p = ModProject(os.path.join(self.tmp, "data1.rda"))
        got_L = p.by_guid["1645021"].dials.get("Build/BuildingSpeed")
        got_H = p.by_guid["1645023"].dials.get("Build/BuildingSpeed")
        self.assertEqual(got_L, "150")
        self.assertNotEqual(got_H, "99")   # vanilla value, not the pending

    def test_flash_without_snapshot_keeps_legacy_behaviour(self):
        # CLI path: flash() without a snapshot applies everything pending
        self.ses.set_dial(self.L, "Build/BuildingSpeed", "150")
        self.ses.set_dial(self.H, "Build/BuildingSpeed", "99")
        self.ses.flash()                   # in-place, no snapshot arg
        self.assertEqual(self.ses.cs.counts()["dials"], 0)
        from annoedit.core import ModProject
        p = ModProject(os.path.join(self.tmp, "data1.rda"))
        self.assertEqual(p.by_guid["1645021"].dials.get("Build/BuildingSpeed"),
                         "150")
        self.assertEqual(p.by_guid["1645023"].dials.get("Build/BuildingSpeed"),
                         "99")


if __name__ == "__main__":
    unittest.main(verbosity=2)
