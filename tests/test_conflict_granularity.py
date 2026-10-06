#!/usr/bin/env python3
"""Conflict-classification granularity, single-flight jobs, store lock.

- The 3-way extras/fertility conflict classifier compares at the same
  granularity as the key: per occurrence for extras, per side for
  fertility.
- _run_bg is single-flight: a second background job is refused while
  one runs, the exports manager is disabled while busy, and a stale
  result does not reload over a newly opened archive. (GUI parts are
  display-gated; headless parts pin the logic.)
- capture_vanilla runs under the store session lock, so the *.tmp sweep
  only ever sees stale temps.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)

from synthetic_rda import make_synthetic_rda  # noqa: E402

from annoedit import ops  # noqa: E402
from annoedit.backup import BackupStore  # noqa: E402
from annoedit.changeset import ChangeSet  # noqa: E402
from annoedit.core import ModProject  # noqa: E402

T = tempfile.mkdtemp(prefix="p1h_")
V = make_synthetic_rda(os.path.join(T, "vanilla.rda"))
L = make_synthetic_rda(os.path.join(T, "live", "data1.rda"))
os.makedirs(os.path.dirname(L), exist_ok=True)
make_synthetic_rda(L)


def _proj(path):
    return ModProject(path)


class ExtrasConflictGranularityTests(unittest.TestCase):
    """per-occurrence conflict classification (extras)."""

    def _cs_with_noria_occ(self, occ, value):
        cs = ChangeSet()
        cs.add_extra("Noria", "NoriaEndRadius", value, occ=occ)
        return cs

    def test_live_change_at_other_occ_no_conflict(self):
        # opened NoriaEndRadius = ['8','10']; live carries ['8','99'] —
        # only occ #1 differs. A pending edit to occ #0 must NOT be a
        # conflict (the whole-list compare counted it as one and
        # spuriously BLOCKED the save).
        opened = _proj(V)
        live = _proj(L)
        live.set_extra("Noria", "NoriaEndRadius", 99, occ=1)
        cs = self._cs_with_noria_occ(0, "12")
        n, keys, cleared, kept = ops._extras_conflicts(opened, live, cs)
        self.assertEqual(n, 0, f"occ-#0 edit must not conflict: {keys}")
        self.assertEqual(cleared, 0)

    def test_live_change_at_same_occ_conflict(self):
        # live differs at occ #0 only — the pending occ-#0 edit IS a
        # conflict (the replay overwrites an unseen live value).
        opened = _proj(V)
        live = _proj(L)
        live.set_extra("Noria", "NoriaEndRadius", 88, occ=0)
        cs = self._cs_with_noria_occ(0, "12")
        n, keys, cleared, kept = ops._extras_conflicts(opened, live, cs)
        self.assertGreaterEqual(n, 1, "occ-#0 edit must conflict")
        self.assertEqual(cleared, 0)

    def test_pending_equals_live_landed(self):
        # live differs at occ #0; the pending edit carries exactly the
        # live value -> LANDED (the user's own earlier save).
        opened = _proj(V)
        live = _proj(L)
        live.set_extra("Noria", "NoriaEndRadius", 88, occ=0)
        cs = self._cs_with_noria_occ(0, "88")
        n, keys, cleared, kept = ops._extras_conflicts(opened, live, cs)
        self.assertEqual(n, 0)
        # pending == live at the occurrence: a NO-OP for the replay —
        # counted NOWHERE now (the old 'landed' guess bucket is gone;
        # the LEDGER states the fact when the edit is CLEARED, which is
        # the case that actually matters: the save then reverts it)
        self.assertEqual(cleared, 0)

    def test_occ_none_means_first_occ(self):
        # occ=None resolves to the first occurrence: a live change at
        # occ #0 conflicts, at occ #1 alone does not.
        opened = _proj(V)
        live1 = _proj(L)
        live1.set_extra("Noria", "NoriaEndRadius", 99, occ=1)
        cs = ChangeSet()
        cs.add_extra("Noria", "NoriaEndRadius", "12")  # occ None
        n1, _k1, _c1, _kq1 = ops._extras_conflicts(opened, live1, cs)
        self.assertEqual(n1, 0)
        live0 = _proj(L)
        live0.set_extra("Noria", "NoriaEndRadius", 88, occ=0)
        n0, _k0, _c0, _kq0 = ops._extras_conflicts(opened, live0, cs)
        self.assertGreaterEqual(n0, 1)


class FertConflictGranularityTests(unittest.TestCase):
    """per-side conflict classification (fertility)."""

    def _opened_live(self, tier, crop):
        opened = _proj(V)
        live = _proj(L)
        return opened, live

    def test_live_change_other_side_no_conflict(self):
        # Almond (low tier): vanilla N=0 S=60. Live carries N=0 S=99 —
        # only SOUTH differs. A pending NORTH edit must NOT conflict
        # (live NORTH still holds the opened value the user saw).
        opened, live = self._opened_live("low", "Almond")
        live.set_fertility("low", "Almond", south=99)
        cs = ChangeSet()
        cs.add_fert("low", "Almond", north=50)
        n, keys, cleared, kept = ops._fert_conflicts(opened, live, cs)
        self.assertEqual(n, 0, f"north edit must not conflict: {keys}")
        self.assertEqual(cleared, 0)

    def test_live_change_same_side_conflict(self):
        # live differs at NORTH only — a pending NORTH edit IS a
        # conflict.
        opened, live = self._opened_live("low", "Bees")
        live.set_fertility("low", "Bees", north=77)
        cs = ChangeSet()
        cs.add_fert("low", "Bees", north=50)
        n, _keys, _cleared, _kept = ops._fert_conflicts(opened, live, cs)
        self.assertGreaterEqual(n, 1)

    def test_half_landed_half_conflict(self):
        # One pair, both sides pending: north was landed earlier by the
        # user (live N=50, pending 50), south changed in live unseen
        # (opened 60, live 55, pending 99) — conflict for south,
        # LANDED for north, the pair counts in each bucket its own
        # sides belong to.
        opened, live = self._opened_live("low", "Almond")
        live.set_fertility("low", "Almond", north=50, south=55)
        cs = ChangeSet()
        cs.add_fert("low", "Almond", north=50, south=99)
        n, _keys, cleared, _kept = ops._fert_conflicts(opened, live, cs)
        self.assertEqual(n, 1)          # south: 99 vs live 55
        # north: pending == live — a NO-OP for the replay, counted
        # nowhere now (the ledger states the fact when the edit is
        # cleared); the south side stays a conflict
        self.assertEqual(cleared, 0)


class SingleFlightTests(unittest.TestCase):
    """single-flight _run_bg + stale-result guard (logic pins)."""

    def test_run_bg_refuses_while_busy(self):
        # The single-flight refusal is pure logic on _busy_flag — pin it
        # headless via the source: a second _run_bg while _busy_flag is
        # set returns without launching a thread.
        src = _read("annoedit/gui/app.py")
        self.assertIn("if self._busy_flag:", src)
        self.assertIn("A background job is still running", src)

    def test_exports_btn_disabled_while_busy(self):
        src = _read("annoedit/gui/app.py")
        self.assertIn('self.exports_btn.config(state=st(True))', src)

    def test_flashresult_carries_source_path(self):
        # The stale-result guard's data: FlashResult records the
        # archive the session had open when the build was dispatched.
        res = ops.FlashResult({"md5": "0" * 32}, ChangeSet(), True, None,
                              source_path="/x/data1.rda")
        self.assertEqual(res.source_path, "/x/data1.rda")
        res2 = ops.FlashResult({"md5": "0" * 32}, ChangeSet(), False, None)
        self.assertIsNone(res2.source_path)

    def test_flash_build_records_source_path(self):
        # flash_build passes the frozen source_path into the result.
        src = _read("annoedit/ops.py")
        self.assertIn("source_path=source_path", src)


def _read(rel):
    root = os.path.dirname(HERE)
    with open(os.path.join(root, rel), "r", encoding="latin-1") as f:
        return f.read()


class StaleResultGuardSourceTests(unittest.TestCase):
    """the _flash_done guard compares the frozen source_path."""

    def test_guard_present(self):
        # Single-string-literal pins only: GUI messages are split
        # across source lines, a joined-substring assert false-negatives
        # (the recurring gotcha).
        src = _read("annoedit/gui/app.py")
        self.assertIn("res.source_path is not None", src)
        self.assertIn("was opened meanwhile; reopen it to see the result", src)


class StoreLockTests(unittest.TestCase):
    """capture_vanilla under the store session lock."""

    def test_capture_locks_the_store(self):
        src = _read("annoedit/backup.py")
        self.assertIn("with self.session_lock():", src)

    def test_capture_reentrant(self):
        # The lock is re-entrant within ONE store instance (nested
        # session_lock on the same _Flock tracks depth) — a caller
        # already holding it can still capture.
        home = tempfile.mkdtemp(prefix="p1cap_")
        store = BackupStore(root=os.path.join(home, "store"))
        with store.session_lock():
            md5, created = store.capture_vanilla(V)
        self.assertTrue(created)
        self.assertTrue(store.has_vanilla)
        # capture again (unlocked) — write-once, no second copy
        md5_2, created_2 = store.capture_vanilla(V)
        self.assertFalse(created_2)
        self.assertEqual(md5, md5_2)

    def test_capture_after_manual_prune_holds_lock(self):
        # prune_orphans inside the locked body: a second store instance
        # (another process) is refused by the flock — the sweep can
        # only ever run while nobody else is mid-write.
        home = tempfile.mkdtemp(prefix="p1prn_")
        s1 = BackupStore(root=os.path.join(home, "store"))
        s2 = BackupStore(root=os.path.join(home, "store"))
        s1.capture_vanilla(V)
        # hold s1's lock: s2's capture must refuse (another process)
        with s1.session_lock():
            with self.assertRaises(Exception):
                s2.capture_vanilla(V)


if __name__ == "__main__":
    unittest.main()
