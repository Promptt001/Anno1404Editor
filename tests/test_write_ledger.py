#!/usr/bin/env python3
"""Write ledger tests: exact revert of cleared edits, drift facts,
replay-guard inheritance, plan-driven builds, ledger lifecycle.

Three end-to-end workflows:
  1. save -> clear -> save         (the cleared edit reverts exactly)
  2. save -> other mod, same key   (mine-but-changed = real conflict)
  3. restore after ledger          (ledger cleared, no ghost reverts)
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LEIF = "1645021"
DIAL = "Build/BuildingSpeed"


class LedgerWorkflowTests(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        from synthetic_rda import make_synthetic_rda
        self.W = tempfile.mkdtemp(prefix="ledger_")
        self.van = os.path.join(self.W, "van.rda")
        make_synthetic_rda(self.van)
        self.live = os.path.join(self.W, "live.rda")
        shutil.copy(self.van, self.live)
        self.ses = self._session()

    def tearDown(self):
        try:
            self.ses.close()
        except Exception:
            pass
        import shutil
        shutil.rmtree(self.W, ignore_errors=True)

    def _session(self):
        from annoedit.session import Session
        return Session(backup_root=os.path.join(self.W, "backups"),
                       exports_root=os.path.join(self.W, "exports"))

    def _prof(self):
        return next(q for q in self.ses.roster if q.guid == LEIF)

    def _live_val(self):
        from annoedit.core import ModProject
        from annoedit.model import effective_value
        p = ModProject(self.live)
        q = p.by_guid[LEIF]
        v, _s = effective_value(q.dials, p.defaults, DIAL)
        return v

    def _van_val(self):
        from annoedit.core import ModProject
        from annoedit.model import effective_value
        p = ModProject(self.van)
        q = p.by_guid[LEIF]
        v, _s = effective_value(q.dials, p.defaults, DIAL)
        return v

    def test_save_clear_save_reverts_exactly(self):
        """Golden workflow: a cleared edit reverts to the
        base value the write replaced — not silently kept forever."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        van_val = self._van_val()
        assert van_val is not None

        # save #1: 77
        self.ses.set_dial(self._prof(), DIAL, "77")
        rep = self.ses.flash(target=self.live)
        self.assertEqual(rep["dial_edits"], 1)
        self.assertEqual(str(self._live_val()), "77")
        led_len = len(rep.get("ledger") or {})
        self.assertEqual(led_len, 1)

        # clear the edit
        self.ses.set_dial(self._prof(), DIAL, None)
        self.assertFalse(dict(self.ses.changes).get(LEIF))

        # save #2: the revert row queues automatically
        rep2 = self.ses.flash(target=self.live)
        self.assertEqual(str(self._live_val()), str(van_val),
                         "cleared edit must revert to the recorded base")
        self.assertFalse(rep2.get("ledger") or {},
                         "a revert drops its ledger key")

    def test_save_clear_save_visible_in_review(self):
        """The revert row appears in the review rows + honest counts
        (what the operator approves is what the build writes)."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.live)
        self.ses.set_dial(self._prof(), DIAL, None)
        # The GUI queues the ledger reverts at review entry — mirror it
        n_rev, _unrev = self.ses.apply_ledger_reverts(self.live)
        self.assertEqual(n_rev, 1)
        # rows against the LIVE base (the base the save writes — the
        # GUI review passes drift.live; against the OPENED base a
        # revert row would drop as a no-op)
        from annoedit.core import ModProject
        live_proj = ModProject(self.live)
        rows, totals = self.ses.pending_change_rows(live_proj)
        revert_rows = [r for r in rows
                       if r["section"] == "AI profile"
                       and r["character"] == self._prof().name
                       and r["dial"] == DIAL]
        self.assertEqual(len(revert_rows), 1,
                         "the cleared edit must show as a revert row")
        self.assertEqual(totals["dials"], 1)

    def test_other_mod_same_key_is_real_conflict(self):
        """Save 77; a foreign editor then writes 99 over it; the next
        save's drift must classify the key MINE-BUT-CHANGED (a real
        conflict), never 'kept' — the ledger states the fact."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.live)

        # a foreign editor writes 99 at the SAME key
        from annoedit.core import ModProject
        p = ModProject(self.live)
        q = p.by_guid[LEIF]
        p.set_dials(q, {DIAL: "99"})
        p.build(self.live)

        self.ses.set_dial(self._prof(), DIAL, None)
        drift = self.ses.target_drift(self.live)
        self.assertTrue(drift, "mine-but-changed must be drift")
        n_dial, _r, _e, _f, _c, _foreign = drift
        self.assertEqual(n_dial, 1,
                         "a ledger key whose live != written is a real "
                         "conflict, never silently 'kept'")

    def test_foreign_key_not_in_ledger_is_kept(self):
        """A live difference the tool never wrote is FOREIGN: kept,
        never counted as conflict/mine."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.live)
        # (ledger now records the 77 write)

        # a foreign editor writes 99 at a DIFFERENT key
        from annoedit.core import ModProject
        p = ModProject(self.live)
        q = p.by_guid[LEIF]
        p.set_dials(q, {"Build/TowersPerLevel": "9"})
        p.build(self.live)

        self.ses.set_dial(self._prof(), DIAL, None)
        self.ses.apply_ledger_reverts(self.live)
        drift = self.ses.target_drift(self.live)
        # A kept-only result is FALSY by design (the replay keeps it) —
        # assert the classification facts directly:
        n_dial, _r, _e, _f, _c, _foreign = drift
        # TowersPerLevel is not in the ledger: kept, never a conflict.
        self.assertEqual(n_dial, 0,
                         "a foreign live change with no pending edit is "
                         "kept, not a blocking conflict")
        self.assertEqual(drift.kept_dials, 1,
                         "the foreign key must be reported as kept")

    def test_pending_reedit_of_saved_key_is_normal_replay(self):
        """A saved key the user RE-EDITS: the pending row is the plan's
        word (the ledger defers) — save writes the new value."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.live)
        self.ses.set_dial(self._prof(), DIAL, "88")
        rep = self.ses.flash(target=self.live)
        self.assertEqual(str(self._live_val()), "88")
        led = rep.get("ledger") or {}
        self.assertEqual(
            led.get(("AI profile", (LEIF, DIAL))).get("written"), "88")

    def test_restore_clears_the_ledger(self):
        """Restore returns the target to vanilla — the ledger's write
        records no longer describe it and are cleared (no ghost
        reverts on the next save)."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.live)
        # a vanilla copy to restore from
        import shutil
        shutil.copy(self.van, os.path.join(self.W, "data1.rda_vanilla"))
        self.ses.provide_vanilla(
            os.path.join(self.W, "data1.rda_vanilla"))
        self.ses.restore_vanilla(target=self.live)
        from annoedit import ledger as L
        self.assertEqual(L.load(self.ses.store, self.live), {},
                         "restore must clear the target's ledger")

    def test_in_place_save_does_not_revert(self):
        """After an IN-PLACE save the session reloads the written file:
        the opened value == written, NOT the recorded base — no revert
        is queued on the next save (the write is the working
        baseline), and the ledger keeps recording it."""
        self.ses.open(self.van)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.van)
        from annoedit.core import ModProject
        from annoedit.model import effective_value
        p = ModProject(self.van)
        v, _s = effective_value(p.by_guid[LEIF].dials, p.defaults, DIAL)
        self.assertEqual(str(v), "77")
        # pending was subtractively cleared; save again with a fresh
        # pending edit — the 77 write must NOT revert to 71.
        self.ses.set_dial(self._prof(), "Build/TowersPerLevel", "5")
        rep2 = self.ses.flash(target=self.van)
        p2 = ModProject(self.van)
        v2, _s2 = effective_value(p2.by_guid[LEIF].dials,
                                  p2.defaults, DIAL)
        self.assertEqual(str(v2), "77",
                         "an in-place reload makes the write the baseline — "
                         "the next save must not revert it")
        led = rep2.get("ledger") or {}
        self.assertEqual(
            led.get(("AI profile", (LEIF, DIAL))).get("written"), "77")

    def test_ledger_persists_across_session(self):
        """The ledger is ON DISK per target: a fresh session (new
        open) still classifies a cleared edit correctly."""
        self.ses.open(self.van)
        self.ses.set_live_path(self.live)
        self.ses.set_dial(self._prof(), DIAL, "77")
        self.ses.flash(target=self.live)
        self.ses.close()

        ses2 = self._session()
        try:
            ses2.open(self.van)
            ses2.set_live_path(self.live)
            # no pending edits: the classifier sees the persisted fact
            # (a mine-cleared-only DriftResult is FALSY by design — the
            # GUI's review entry queues the reverts BEFORE the drift
            # check runs, so the dialog flow never relies on drift
            # truthiness here).
            from annoedit import ledger as L
            led = L.load(ses2.store, self.live)
            cleared, _unrev = L.cleared_keys(led, ses2.cs, ses2.proj,
                                             list(ses2.roster))
            self.assertIn(("AI profile", (LEIF, DIAL)), cleared,
                          "a fresh session classifies the persisted "
                          "ledger entry as mine-cleared")
            # queue a dummy pending edit, then save: reverts ride along
            ses2.set_dial(next(q for q in ses2.roster if q.guid == LEIF),
                          "Build/TowersPerLevel", "3")
            ses2.flash(target=self.live)
            self.assertEqual(str(self._live_val()),
                            str(self._van_val()),
                            "the second session's save reverts the first "
                            "session's cleared edit (persisted facts)")
        finally:
            ses2.close()


class LedgerUnitTests(unittest.TestCase):
    """Unit-level: ledger load/update round-trip, cleared_keys
    endorsement rules, replay-guard inheritance, plan drops."""

    def setUp(self):
        import tempfile
        from annoedit.backup import BackupStore
        self.W = tempfile.mkdtemp(prefix="ledger_unit_")
        self.store = BackupStore(root=os.path.join(self.W, "store"))
        self.target = os.path.join(self.W, "t.rda")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.W, ignore_errors=True)

    def _row(self, kind, key, old, new, rule=None):
        from annoedit.plan import ResolvedChange
        return ResolvedChange(kind, key, "name", old, new, rule)

    def test_load_missing_is_empty(self):
        from annoedit.ledger import load
        self.assertEqual(load(self.store, self.target), {})

    def test_update_roundtrip(self):
        from annoedit.ledger import load, update
        rows = [self._row("AI profile", ("1", "Build/BuildingSpeed"),
                          "71", "77")]
        led = update(self.store, self.target, rows)
        self.assertEqual(led, {("AI profile", ("1", "Build/BuildingSpeed")):
                               {"base": "71", "written": "77"}})
        self.assertEqual(load(self.store, self.target), led)

    def test_update_drops_revert_keys(self):
        from annoedit.ledger import load, update
        update(self.store, self.target,
               [self._row("AI profile", ("1", "Build/BuildingSpeed"),
                          "71", "77")])
        led = update(self.store, self.target,
                     [self._row("AI profile", ("1", "Build/BuildingSpeed"),
                                "77", "71", rule="revert")])
        self.assertEqual(led, {})
        self.assertEqual(load(self.store, self.target), {})

    def test_update_clear(self):
        from annoedit.ledger import load, update
        update(self.store, self.target,
               [self._row("AI profile", ("1", "Build/BuildingSpeed"),
                          "71", "77")])
        led = update(self.store, self.target, [], clear=True)
        self.assertEqual(led, {})
        self.assertEqual(load(self.store, self.target), {})

    def test_normalize_base_relations_and_fert(self):
        from annoedit.ledger import normalize_base
        self.assertEqual(normalize_base("AI relations", "a, b"), ["a", "b"])
        self.assertEqual(normalize_base("FERTILITY", "N=10 S=20"),
                         {"north": 10, "south": 20})
        self.assertEqual(normalize_base("AI relations", "(empty)"), [])
        self.assertEqual(normalize_base("EXTRAS", "42"), "42")

    def test_f11_reset_clears_stale_expected_old(self):
        """A reset queued over a prior manual edit inherits NOTHING:
        the reset replaces whatever is there (expected_old cleared)."""
        from annoedit.changeset import ChangeSet
        cs = ChangeSet()
        cs.add_extra("Warehouse01 [1001]", "PassiveTradeSlots", "5",
                     occ=0, expected_old="4", occ_count=1)
        self.assertEqual(
            cs.extras[("Warehouse01 [1001]", "PassiveTradeSlots", 0)]
            .expected_old, "4")
        # a reset over the same key: stale records must NOT inherit
        cs.add_extra("Warehouse01 [1001]", "PassiveTradeSlots", "4",
                     occ=0, rule="reset")
        e = cs.extras[("Warehouse01 [1001]", "PassiveTradeSlots", 0)]
        self.assertIsNone(e.expected_old,
                          "F-11: a reset must clear the stale expected_old")
        self.assertIsNone(e.occ_count,
                          "F-11: a reset must clear the stale occ_count")
        # same-rule re-queue KEEPS the records
        cs.add_extra("Warehouse01 [1001]", "PassiveTradeSlots", "6",
                     occ=0, expected_old="4", occ_count=1)
        cs.add_extra("Warehouse01 [1001]", "PassiveTradeSlots", "7",
                     occ=0, expected_old="4", occ_count=1)
        e2 = cs.extras[("Warehouse01 [1001]", "PassiveTradeSlots", 0)]
        self.assertEqual(e2.expected_old, "4")

    def test_f12_absent_asset_rule_row_dropped_in_plan(self):
        """A revert/reset row whose asset is ABSENT from the base
        catalog is dropped by the plan (the build used to refuse the
        whole save at find_asset)."""
        import sys as _s
        _s.path.insert(0, _HERE)
        from annoedit.changeset import ChangeSet
        from annoedit.plan import plan_extras
        cs = ChangeSet()
        cs.add_extra("PrintingHouse [999]", "ProductionTime", "1000",
                     occ=None, rule="reset")
        # empty base catalog: everything is '(absent)'
        rows = plan_extras(cs, {})
        self.assertEqual(rows, [],
                         "a rule row with an absent base value must drop")


if __name__ == "__main__":
    unittest.main()
