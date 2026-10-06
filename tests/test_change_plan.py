"""The change plan (annoedit/plan.py).

Covers: the plan as the single source of truth for review rows, the
build's no-op drop and display counts; drift classification; the
plan-hash consent anchor (the build refuses when the recomputed plan
differs from the reviewed one); pending counts; the always-confirmed
reset click.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from synthetic_rda import make_synthetic_rda  # noqa: E402

from annoedit import ops  # noqa: E402
from annoedit import plan as plan_mod  # noqa: E402
from annoedit.changeset import ChangeSetError  # noqa: E402
from annoedit.session import Session, SessionError  # noqa: E402

T = tempfile.mkdtemp(prefix="p4_")
V = make_synthetic_rda(os.path.join(T, "vanilla.rda"))
M = make_synthetic_rda(os.path.join(T, "modded.rda"), variant=1)
L = os.path.join(T, "live", "data1.rda")
os.makedirs(os.path.dirname(L), exist_ok=True)
make_synthetic_rda(L)


def mk(home):
    return Session(backup_root=os.path.join(home, "b"),
                   exports_root=os.path.join(home, "e"),
                   settings=None)


class PlanTests(unittest.TestCase):
    """plan(cs, base): one source of truth for rows, drops, counts."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="p4h_")
        os.environ.pop("ANN0140_EXPORTS_DIR", None)
        self.ses = mk(self.home)
        self.ses.provide_vanilla(V)
        self.ses.open(M)

    def tearDown(self):
        self.ses.close()

    def _leif(self, ses=None):
        ses = ses or self.ses
        return ses.proj.by_name["Leif Jorgensen"]

    def test_rows_match_build_counts_against_opened(self):
        # The plan's totals ARE what the build writes (no separate row
        # arithmetic): rows count == build's per-surface counts.
        self.ses.set_dial(self._leif(), "Build/BuildingSpeed", "150")
        rows, totals = self.ses.pending_change_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(totals["dials"], 1)
        self.assertEqual(rows[0]["dial"], "Build/BuildingSpeed")
        self.assertEqual(rows[0]["old"], self.ses.effective(
            self._leif(), "Build/BuildingSpeed")[0])

    def test_rule_noop_rows_dropped_vs_base(self):
        # A Vanilla reset queues EVERY key; only REAL changes survive
        # into the plan rows (the no-op rule rows drop HERE).
        self.ses.set_mode(self._leif(), "vanilla")
        rows, totals = self.ses.pending_change_rows(self.ses.proj)
        self.assertEqual(totals["dials"],
                         len(self.ses.changes[self._leif().guid])
                         - sum(1 for p, e in self.ses.cs.dials.items()
                               if e.rule and plan_mod.plan_dial_noop(
                                   e, self.ses.proj.by_guid.get(p[0]),
                                   self.ses.proj, p[1])))

    def test_counts_honest_no_inflation(self):
        # A revert-globals on an UNMODIFIED archive queues every extras
        # leaf + fert row, but 0 of them are real changes: the honest
        # count says 0, while the raw record count would say 11/48.
        # Opened = the unmodified vanilla here.
        s2 = mk(tempfile.mkdtemp(prefix="p4m_"))
        s2.provide_vanilla(V)
        s2.open(V)
        s2.revert_globals_to_reference()
        raw = {"extras": len(s2.cs.extras), "fertility": len(s2.cs.fert)}
        honest = s2.pending_counts()
        self.assertGreater(raw["extras"], 0)
        self.assertGreater(raw["fertility"], 0)
        self.assertEqual(honest["extras"], 0)
        self.assertEqual(honest["fertility"], 0)
        s2.close()
        return

    def test_counts_honest_on_modded_opened(self):
        # On a MODDED opened archive, revert-globals' real count is the
        # number of leaves that actually differ (1 in the synthetic
        # variant-1) — honest, not 0 and not the raw 11.
        self.ses.revert_globals_to_reference()
        raw = {"extras": len(self.ses.cs.extras),
               "fertility": len(self.ses.cs.fert)}
        honest = self.ses.pending_counts()
        self.assertGreater(raw["extras"], honest["extras"])
        self.assertGreater(raw["fertility"], honest["fertility"])
        self.assertEqual(honest["extras"], 1)

    def test_plan_hash_stable_and_sensitive(self):
        self.ses.set_dial(self._leif(), "Build/BuildingSpeed", "150")
        r1, _t = self.ses.change_plan()
        h1 = plan_mod.plan_hash(r1)
        self.assertEqual(h1, plan_mod.plan_hash(self.ses.change_plan()[0]))
        self.ses.set_dial(self._leif(), "Build/BuildingSpeed", "151")
        r2, _t = self.ses.change_plan()
        self.assertNotEqual(h1, plan_mod.plan_hash(r2))


class DriftBucketsTests(unittest.TestCase):
    """Drift: conflict / landed / kept — three buckets, all surfaces."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="p4d_")
        os.environ.pop("ANN0140_EXPORTS_DIR", None)
        self.ses = mk(self.home)
        self.ses.provide_vanilla(V)
        self.ses.open(V)                      # opened == live == vanilla
        self.ses.set_live_path(L)

    def tearDown(self):
        self.ses.close()

    def test_landed_edit_not_counted_as_kept(self):
        # The user's own edit saved to live earlier: live == pending
        # there -> a NO-OP for the replay, counted NOWHERE (the old
        # 'landed' guess bucket is gone: it could not tell the tool's
        # own writes from a coincidence. The LEDGER now states the
        # fact — and when the edit is CLEARED the save reverts it).
        g = self.ses.proj.by_name["Leif Jorgensen"]
        self.ses.set_dial(g, "Military/MaxUnitCount", "42")
        self.ses.flash(target=L)
        dr = ops.drift_check(*self.ses.freeze_drift_inputs())
        self.assertEqual(dr.kept_dials, 0)
        self.assertEqual(dr[0], 0)             # no conflict
        self.assertFalse(dr)                   # nothing to ask about
        # the write is ON THE LEDGER: clearing the edit reverts it
        from annoedit import ledger as ledger_mod
        led = ledger_mod.load(self.ses.store, L)
        self.assertIn(("AI profile", (g.guid, "Military/MaxUnitCount")),
                      led)
        self.ses.set_dial(g, "Military/MaxUnitCount", None)
        cleared, _unrev = ledger_mod.cleared_keys(
            led, self.ses.cs, self.ses.proj, list(self.ses.roster))
        self.assertIn(("AI profile", (g.guid, "Military/MaxUnitCount")),
                      cleared, "the cleared edit is a fact, not a guess")

    def test_three_buckets(self):
        # opened = modded, live = vanilla: every differing key with a
        # pending decision is a CONFLICT (the replay overwrites an
        # unseen live value); differing keys without pending are KEPT.
        s2 = mk(tempfile.mkdtemp(prefix="p4e_"))
        s2.provide_vanilla(V)
        s2.open(M)
        s2.set_live_path(L)
        g = s2.proj.by_name["Leif Jorgensen"]
        s2.set_dial(g, "Build/BuildingSpeed", "175")
        dr = ops.drift_check(*s2.freeze_drift_inputs())
        self.assertGreaterEqual(dr[0], 1)      # at least the conflict
        self.assertGreaterEqual(dr.kept_dials, 1)  # foreign, no pending
        self.assertEqual(dr.mine_cleared_dials, 0)
        s2.close()


class ConsentAnchorTests(unittest.TestCase):
    """The plan-hash half of the consent anchor: the build refuses when
    the recomputed plan differs from the one the review approved."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="p4c_")
        os.environ.pop("ANN0140_EXPORTS_DIR", None)
        self.ses = mk(self.home)
        self.ses.provide_vanilla(V)
        self.ses.open(M)
        self.ses.set_live_path(L)

    def tearDown(self):
        self.ses.close()

    def test_build_refuses_on_plan_mismatch(self):
        g = self.ses.proj.by_name["Leif Jorgensen"]
        self.ses.set_dial(g, "Military/MaxUnitCount", "42")
        # The plan the review approved:
        approved = plan_mod.plan_hash(
            self.ses.change_plan(self.ses.proj)[0])
        # A different plan (one more dial queued after the review):
        self.ses.set_dial(g, "Build/BuildingSpeed", "175")
        with self.assertRaises(SessionError):
            ops.build_from_snapshot(
                self.ses.proj.entries, self.ses.source_path,
                self.ses.cs.snapshot(), os.path.join(T, "p4x.rda"),
                roster=list(self.ses.roster), expected_plan=approved)

    def test_build_accepts_matching_plan(self):
        g = self.ses.proj.by_name["Leif Jorgensen"]
        self.ses.set_dial(g, "Military/MaxUnitCount", "42")
        # Hash the plan against the base the build writes (the opened
        # archive — export/in-place shape).
        approved = plan_mod.plan_hash(
            self.ses.change_plan(self.ses.proj)[0])
        out = os.path.join(T, "p4y.rda")
        rep = ops.build_from_snapshot(
            self.ses.proj.entries, self.ses.source_path,
            self.ses.cs.snapshot(), out,
            roster=list(self.ses.roster), expected_plan=approved)
        self.assertEqual(rep["dial_edits"], 1)

    def test_vanilla_reset_drops_noops_in_build(self):
        # rule rows dropped by the plan are dropped by the BUILD too
        # (one source of truth): a full vanilla reset on an archive
        # whose live/opened values already equal the reference builds
        # 0 dial edits.
        s2 = mk(tempfile.mkdtemp(prefix="p4v_"))
        s2.provide_vanilla(V)
        s2.open(V)
        g = s2.proj.by_name["Leif Jorgensen"]
        s2.set_mode(g, "vanilla")
        # Plan against the base the build writes (the opened archive):
        prows, ptot = s2.change_plan(s2.proj)
        self.assertEqual(ptot["dials"], 0)
        out = os.path.join(T, "p4z.rda")
        rep = ops.build_from_snapshot(
            s2.proj.entries, s2.source_path, s2.cs.snapshot(), out,
            roster=list(s2.roster))
        self.assertEqual(rep["dial_edits"], 0)
        s2.close()


class ResetConfirmTests(unittest.TestCase):
    """The reset click always confirms (even with nothing pending)."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="p4r_")
        os.environ.pop("ANN0140_EXPORTS_DIR", None)
        self.ses = mk(self.home)
        self.ses.provide_vanilla(V)
        self.ses.open(M)

    def tearDown(self):
        self.ses.close()

    def test_counts_by_guid_honest(self):
        self.ses.set_dial(self.ses.proj.by_name["Leif Jorgensen"],
                          "Build/BuildingSpeed", "150")
        c = self.ses.pending_counts()
        self.assertEqual(c["_by_guid"]["1645021"]["dials"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
