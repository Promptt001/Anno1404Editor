"""Threading model tests.

Workers run the pure annoedit.ops functions on frozen inputs; only the UI
(Tk/main) thread commits (install_open / apply_flash_result /
apply_restore_result). Session._assert_ui_thread enforces this under
ANN0140_STRICT_THREADS=1. These tests pin that edits queued while a
background flash or restore runs are neither lost nor raced.
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synthetic_rda import make_synthetic_rda
from annoedit.appsettings import Settings
from annoedit import ops
from annoedit.session import Session, SessionError

os.environ["ANN0140_STRICT_THREADS"] = "1"     # the threading rule, ON


def _mk_session(tag="p2"):
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


class Phase2Threading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = tempfile.mkdtemp()
        cls.A = make_synthetic_rda(cls.W + "/vanilla.rda")

    def setUp(self):
        os.environ.setdefault("ANN0140_HOME", tempfile.mkdtemp())

    def _open(self, s):
        s.open(self.A)
        return s.proj.by_guid["1645021"]

    # the race as a loop

    def test_race_worker_flash_vs_ui_thread_edits(self):
        """Race scenario: 6 chars' edits pending, a worker thread
        flashes, the UI thread keeps editing a 7th char + reading
        ses.changes. Old design: RuntimeError / dropped edits. New
        design: the worker runs pure ops.flash_build; the commit
        (subtractive clear) happens on THIS thread."""
        errors = []
        for trial in range(20):
            s, _root = _mk_session()
            try:
                target = os.path.join(self.W, f"race{trial}.rda")
                p0 = self._open(s)
                for guid in ("1645021", "1645023", "1645025",
                             "1645020", "1645024", "1645026"):
                    q = s.proj.by_guid[guid]
                    s.set_dial(q, "Military/MaxUnitCount", "55")
                snap = s.cs.snapshot()
                entries = s.proj.entries
                source_path = s.source_path

                results = []

                def worker():
                    # PURE phase only — exactly what _run_bg does; the
                    # commit (apply_flash_result) runs on the main thread
                    # below, like the done() callback on the Tk loop.
                    try:
                        results.append(ops.flash_build(
                            s._write_lock, s.store, entries, source_path,
                            lambda tmp, cs, base: ops.build_from_snapshot(
                                base, source_path, cs, tmp),
                            snap, target, False))
                    except Exception as e:      # noqa: BLE001
                        errors.append(f"worker: {e!r}")

                t = threading.Thread(target=worker)
                t.start()
                # UI thread: keep editing + reading while the build runs
                q7 = s.proj.by_guid["1645022"] \
                    if "1645022" in s.proj.by_guid else s.proj.by_guid[
                        "1645020"]
                while t.is_alive():
                    try:
                        s.set_dial(q7, "Military/MaxUnitCount", "77")
                        _ = s.changes
                    except RuntimeError as e:
                        errors.append(f"ui: {e!r}")
                        break
                    except SessionError:
                        pass
                    time.sleep(0.001)
                t.join(10)
                if t.is_alive():
                    errors.append("worker thread hung")
                self.assertEqual(errors, [])
                # Tk-thread commit (the done() callback equivalent)
                self.assertEqual(len(results), 1)
                s.apply_flash_result(results[0])
                # the 7th char's edits made during the build stay pending
                # (they were NOT in the frozen snapshot)
                self.assertEqual(
                    s.cs.dial_value(q7.guid, "Military/MaxUnitCount"), "77")
            finally:
                s.close()
        self.assertEqual(errors, [])

    # edits during a background restore are NOT dropped

    def test_restore_commit_drops_only_open_archive_reset(self):
        """The old restore_vanilla in a worker did self.cs = ChangeSet()
        off-thread, dropping edits queued during the restore. New: the
        pending reset happens in apply_restore_result, on the UI thread,
        only when the OPEN archive was the target."""
        s, root = _mk_session()
        try:
            p0 = self._open(s)
            # a MODDED live target (a vanilla-identical one is refused —
            # "already IS the stored vanilla"): apply a real dial edit
            live = os.path.join(root, "live.rda")
            from annoedit.core import ModProject
            pp = ModProject(self.A)
            pp.set_dials(pp.by_guid["1645021"],
                         {"Military/MaxUnitCount": "99"})
            pp.build(live)
            s.settings.set("live_path", live)
            # queue an edit on ANOTHER char — the restore targets live,
            # which is NOT the open archive: pending must SURVIVE
            q2 = s.proj.by_guid["1645025"]
            s.set_dial(q2, "Military/MaxUnitCount", "66")
            n_before = len(s.cs.dials)
            res = ops.restore_build(
                s._write_lock, s.store, s.exports_store, live, False,
                s.source_path)
            vmd5 = s.apply_restore_result(res)
            self.assertTrue(vmd5)
            self.assertEqual(len(s.cs.dials), n_before,
                             "edits dropped by a NON-in-place restore")
        finally:
            s.close()

    def test_restore_in_place_resets_pending_on_ui_thread(self):
        s, root = _mk_session()
        try:
            # a MODDED archive (the open archive is the first-open
            # snapshot otherwise, and restoring vanilla over it would be
            # refused as "already IS the stored vanilla")
            modded = os.path.join(self.W, "modded_ip.rda")
            make_synthetic_rda(modded, variant=1)
            # provide the vanilla copy FIRST: the restore source is the
            # provided copy, not the first-open snapshot (which here would
            # be the modded archive itself -> "already IS" refusal)
            s.provide_vanilla(self.A)
            s.open(modded)
            p0 = s.proj.by_guid["1645021"]
            s.set_dial(p0, "Military/MaxUnitCount", "66")
            self.assertTrue(s.cs)
            # The real flow — Session.restore_vanilla
            # freezes the pending snapshot BEFORE the worker runs, so the
            # commit drops exactly the edits that existed at restore time
            # (reverts their targets) and keeps edits made DURING it.
            vmd5 = s.restore_vanilla(s.source_path)
            self.assertTrue(vmd5)
            self.assertFalse(s.cs, "in-place restore must reset pending")
            self.assertEqual(s.source_md5, vmd5)
        finally:
            s.close()

    # the pure phase never mutates the Session

    def test_pure_worker_open_never_touches_session(self):
        s, _root = _mk_session()
        try:
            loaded = ops.load_archive(
                self.A, s.store, s.exports_store, s.settings, False,
                cached_baseline=None, cached_stamp=None)
            # nothing installed yet: the session is still closed
            self.assertIsNone(s.proj)
            self.assertIsNone(s.source_path)
            info = s.install_open(loaded)
            self.assertEqual(info["profiles"], len(s.proj.by_guid))
        finally:
            s.close()

    def test_pure_worker_flash_leaves_session_untouched(self):
        s, root = _mk_session()
        try:
            p0 = self._open(s)
            s.set_dial(p0, "Military/MaxUnitCount", "55")
            snap = s.cs.snapshot()
            n_before = len(s.cs.dials)
            entries = s.proj.entries
            source_path = s.source_path
            target = os.path.join(root, "live.rda")
            res = ops.flash_build(
                s._write_lock, s.store, entries, source_path,
                lambda tmp, cs, base: ops.build_from_snapshot(
                    base, source_path, cs, tmp),
                snap, target, False)
            # not applied yet: pending edits still there, proj unchanged
            self.assertEqual(len(s.cs.dials), n_before)
            rep = s.apply_flash_result(res)
            self.assertEqual(rep["dial_edits"], 1)
            # non-in-place: the snapshot's edits are NOT cleared... but
            # they WERE flashed; the old sync flow cleared only in-place
            # flashes — keep that exact behaviour (regression-guarded)
        finally:
            s.close()

    # the UI-thread assertion

    def test_strict_threads_refuses_off_thread_mutation(self):
        s, _root = _mk_session()
        try:
            self._open(s)
            self.assertTrue(s.strict_threads)
            errs = []

            def off_thread():
                try:
                    q = s.proj.by_guid["1645021"]
                    s.set_dial(q, "Military/MaxUnitCount", "50")
                except RuntimeError as e:
                    errs.append(e)

            t = threading.Thread(target=off_thread)
            t.start()
            t.join(10)
            self.assertEqual(len(errs), 1,
                             "off-thread mutator must raise under strict "
                             "threads")
            self.assertIn("UI thread", str(errs[0]))
        finally:
            s.close()

    def test_strict_threads_allows_main_thread(self):
        s, _root = _mk_session()
        try:
            p0 = self._open(s)
            s.set_dial(p0, "Military/MaxUnitCount", "50")
            self.assertEqual(
                s.cs.dial_value("1645021", "Military/MaxUnitCount"), "50")
        finally:
            s.close()

    def test_sync_wrappers_still_work_without_strict_flag(self):
        """The CLI/tests path: the sync wrappers (open/flash/restore)
        run pure ops + commit inline on the CALLING thread — a Session
        with strict_threads off (the default when the env is unset)
        never asserts. (The fixture sets the env; flip it per-instance.)"""
        s, _root = _mk_session()
        try:
            s.strict_threads = False
            p0 = self._open(s)
            s.set_dial(p0, "Military/MaxUnitCount", "50")
            target = os.path.join(_mk_session()[1], "live9.rda")
            rep = s.flash(target)
            self.assertEqual(rep["dial_edits"], 1)
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
