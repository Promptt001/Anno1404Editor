#!/usr/bin/env python3
"""Absolute queueing, consent anchor and replay guards.

Scenario: the vanilla copy is opened while the live file carries the
Admiral persona. Vanilla / Hardened / revert-globals queue a value for
every key in scope, and no-ops are dropped against the base actually
written, so saving to live really resets the live values.

- The drift result carries live/live_md5 as the consent anchor; a save
  with expected_md5=drift.live_md5 refuses when live changed after the
  review.
- pending_change_rows(base) reports 'old' from the base (live) value.
- An INSERT extras edit carries occ_count=0, so live gaining the tag
  after queueing is refused by the replay guard.
- An unmodelled-only DriftResult is truthy; an anchored persona INSERT
  replay is not misreported as unmodelled; a foreign residual is.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

from tests.synthetic_rda import make_synthetic_rda      # noqa: E402

LEIF = "1645021"


def _mk_session(tag="t"):
    from annoedit.appsettings import Settings
    from annoedit.session import Session
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


def _reload(path):
    """A fresh ModProject over a written archive."""
    from annoedit.core import ModProject
    return ModProject(path)


class Phase2Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = tempfile.mkdtemp(prefix="p26_")

    def setUp(self):
        os.environ.setdefault("ANN0140_HOME", tempfile.mkdtemp())
        os.environ.pop("ANN0140_EXPORTS_DIR", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.W, ignore_errors=True)


class TestH1VanillaAbsolute(Phase2Base):
    """A.2 shape: opened = the vanilla copy, live modded."""

    def _setup(self, variant=1):
        V = make_synthetic_rda(self.W + "/v.rda")
        L = self.W + "/live.rda"
        make_synthetic_rda(L, variant=variant)
        s, _ = _mk_session("p26a")
        s.provide_vanilla(V)
        s.open(V)          # opened == the vanilla reference
        return s, V, L

    def test_h1_vanilla_resets_live(self):
        # live (variant=1) differs from vanilla in ~every dial; a Vanilla
        # click + save-to-live must RESET live to vanilla — the old
        # delta-queueing queued nothing (opened == vanilla) and live kept
        # every mod.
        s, V, L = self._setup()
        leif = s.proj.by_guid[LEIF]
        s.set_mode(leif, "vanilla")
        s.flash(target=L)
        lp = _reload(L)
        vprof = _reload(V).by_guid[LEIF]
        lprof = lp.by_guid[LEIF]
        self.assertEqual(lprof.dials, vprof.dials)
        s.close()

    def test_h1_vanilla_resets_live_relations(self):
        # the vanilla reference's relations ride along absolutely: a
        # live-only War list the opened archive lacks is CLEARED.
        s, V, L = self._setup()
        leif = s.proj.by_guid[LEIF]
        s.set_mode(leif, "vanilla")
        s.flash(target=L)
        lp = _reload(L)
        vprof = _reload(V).by_guid[LEIF]
        lprof = lp.by_guid[LEIF]
        self.assertEqual(lp.relations(lprof), _reload(V).relations(vprof))
        s.close()

    def test_h1_review_drops_noops_against_live(self):
        # honest review: on the live base, the rule='reset' rows whose
        # live value already equals the reference DROP from the rows.
        s, V, L = self._setup()
        leif = s.proj.by_guid[LEIF]
        s.set_mode(leif, "vanilla")
        base = _reload(L)
        rows, totals = s.pending_change_rows(base)
        self.assertTrue(totals["dials"] > 0)   # variant=1 truly differs
        live_prof = base.by_guid[LEIF]
        for r in rows:
            if r["section"] != "AI profile":
                continue
            # every shown dial row is a REAL change vs the live base
            cur = live_prof.dials.get(r["dial"])
            self.assertNotEqual(str(cur), str(r["new"]),
                                f"row {r['dial']} is a no-op vs live")
        s.close()

    def test_h1_hardened_raises_live_value(self):
        # NEVER-EASIER vs the BASE: live lower than the opened value must
        # still be hardened (the old skip was evaluated against OPENED).
        # Build a live archive with Leif Military/MaxUnitCount LOWER.
        from annoedit.core import ModProject
        s, V, L = self._setup()
        p = ModProject(L)
        leif = p.by_guid[LEIF]
        low = str(int(str(leif.dials["Military/MaxUnitCount"])) - 3)
        p.set_dials(leif, {"Military/MaxUnitCount": low})
        p.build(L)
        s2 = s   # same session, opened archive is the vanilla copy
        s2.set_mode(s2.proj.by_guid[LEIF], "hardened")
        s2.flash(target=L)
        lp = _reload(L)
        lmax = int(lp.by_guid[LEIF].dials["Military/MaxUnitCount"])
        # NEVER-EASIER evaluated against the BASE (live): the lowered
        # live value must rise to AT LEAST the hardened target (the max
        # over the vanilla baseline's hard profiles + schema default).
        from annoedit.presets import HARD_GUIDS
        hard_max = max(
            int(q.dials["Military/MaxUnitCount"])
            for fk in s.vanilla_baseline.profiles.values()
            for q in fk if q.guid in HARD_GUIDS
            and "Military/MaxUnitCount" in q.dials)
        self.assertGreaterEqual(lmax, hard_max)
        self.assertGreater(lmax, int(low))   # the lowered base rose
        s.close()

    def test_h1_revert_globals_resets_live(self):
        # revert-globals queues EVERY reference leaf absolutely: a
        # live-only extras mod the opened archive lacks is reverted.
        s, V, L = self._setup()
        s.revert_globals_to_reference()
        s.flash(target=L)
        lp = _reload(L)
        self.assertEqual(lp.extras_catalog(),
                         _reload(V).extras_catalog())
        self.assertEqual(lp.fertility_catalog(),
                         _reload(V).fertility_catalog())
        s.close()


class TestM2ConsentAnchor(Phase2Base):
    def test_m2_drift_result_carries_live_and_md5(self):
        V = make_synthetic_rda(self.W + "/v2.rda")
        L = self.W + "/live2.rda"
        make_synthetic_rda(L, variant=1)
        s, _ = _mk_session("p26m2")
        s.open(V)
        leif = s.proj.by_guid[LEIF]
        s.set_dial(leif, "Build/BuildingSpeed", "77")
        frozen = s.freeze_drift_inputs(target=L)
        from annoedit import ops
        drift = ops.drift_check(*frozen)
        self.assertIsNotNone(drift)
        self.assertIsNotNone(drift.live)
        self.assertIsNotNone(drift.live_md5)
        # the md5 describes the live blob actually read
        from annoedit.rda import read_rda_with_md5
        _e, md5 = read_rda_with_md5(L, strict=True)
        self.assertEqual(drift.live_md5, md5)
        s.close()

    def test_m2_expected_md5_refuses_changed_live(self):
        # save with expected_md5=drift.live_md5 after live changed ->
        # REFUSED (the old save used the rebase read's own md5 — unbound
        # to the reviewed version). The GUI worker path runs exactly
        # ops.flash_build with expected_md5=drift.live_md5; a changed
        # live file must make the commit refuse.
        from annoedit import ops
        from annoedit.session import SessionError
        V = make_synthetic_rda(self.W + "/v3.rda")
        L = self.W + "/live3.rda"
        make_synthetic_rda(L, variant=1)
        s, _ = _mk_session("p26m2b")
        s.open(V)
        leif = s.proj.by_guid[LEIF]
        s.set_dial(leif, "Build/BuildingSpeed", "77")
        drift = ops.drift_check(*s.freeze_drift_inputs(target=L))
        self.assertTrue(drift)
        # mutate live behind the review's back
        from annoedit.core import ModProject
        p = ModProject(L)
        p.set_dials(p.by_guid[LEIF], {"Build/BuildingSpeed": "10"})
        p.build(L)
        with self.assertRaises(SessionError):
            ops.flash_build(
                s._write_lock, s.store, s.proj.entries, s.source_path,
                lambda tmp, cs, base: ops.build_from_snapshot(
                    base, s.source_path, cs, tmp),
                s.cs.snapshot(), L, False,
                expected_md5=drift.live_md5)
        s.close()


class TestM3RowsFromBase(Phase2Base):
    def test_m3_row_old_is_base_value(self):
        # A.2's shape: opened = vanilla, live modded — the dial row's
        # 'old' must be the LIVE value the edit actually replaces, not
        # the opened archive's.
        V = make_synthetic_rda(self.W + "/v4.rda")
        L = self.W + "/live4.rda"
        make_synthetic_rda(L, variant=1)
        s, _ = _mk_session("p26m3")
        s.provide_vanilla(V)
        s.open(V)
        leif = s.proj.by_guid[LEIF]
        s.set_mode(leif, "vanilla")
        base = _reload(L)
        rows, _t = s.pending_change_rows(base)
        base_prof = base.by_guid[LEIF]
        hits = 0
        for r in rows:
            if r["section"] == "AI profile" and \
                    r["character"] == base_prof.name:
                cur = base_prof.dials.get(r["dial"])
                self.assertEqual(str(cur), str(r["old"]),
                                 f"{r['dial']}: old must be the live value")
                hits += 1
        self.assertGreater(hits, 0)
        s.close()

    def test_m3_noop_reset_rows_dropped(self):
        # rows on a base already carrying the reference values drop
        V = make_synthetic_rda(self.W + "/v5.rda")
        s, _ = _mk_session("p26m3b")
        s.provide_vanilla(V)
        s.open(V)
        leif = s.proj.by_guid[LEIF]
        s.set_mode(leif, "vanilla")   # absolute queueing: every key
        self.assertTrue(s.changes.get(LEIF))
        rows, totals = s.pending_change_rows(s.proj)   # base == opened
        self.assertEqual(totals["dials"], 0)   # all no-ops vs the base
        s.close()


class TestM12InsertReplayGuard(Phase2Base):
    def test_m12_insert_gained_tag_refused(self):
        # queue an INSERT (absent tag) on the opened archive, then let
        # live GAIN the tag — the replay must refuse (occ_count=0 now
        # recorded; the old None skipped the guard).
        V = make_synthetic_rda(self.W + "/v6.rda")
        L = self.W + "/live6.rda"
        make_synthetic_rda(L, variant=0)
        s, _ = _mk_session("p26m12")
        s.open(V)
        # an allow-listed INSERT target: the synthetic Papermill asset
        # (GUID 1003 — the plain name is ambiguous, use the display form)
        s.set_extra("PrintingHouse", "ProductionTime", "1000")
        # live GAINS the tag after queueing (the replay must refuse)
        from annoedit.core import ModProject
        p = ModProject(L)
        p.set_extra("PrintingHouse", "ProductionTime", "44444", None)
        p.build(L)
        from annoedit.session import SessionError
        with self.assertRaises(SessionError):
            s.flash(target=L)
        s.close()

    def test_m12_occ_count_zero_recorded(self):
        # an INSERT records occ_count=0, never None (the [] falsy bug)
        V = make_synthetic_rda(self.W + "/v7.rda")
        s, _ = _mk_session("p26m12b")
        s.open(V)
        s.set_extra("PrintingHouse", "ProductionTime", "1000")
        e = s.cs.extras[("PrintingHouse", "ProductionTime", None)]
        self.assertEqual(e.occ_count, 0)
        self.assertIsNone(e.expected_old)
        s.close()


class TestH2UnmodelledAndAnchors(Phase2Base):
    def test_h2_unmodelled_only_truthy(self):
        from annoedit.ops import DriftResult
        d = DriftResult(0, 0, 0, 0, 0, 0, unmodelled=("aiprofiles.xml",))
        self.assertTrue(bool(d))   # unmodelled-only is visible

    def test_h2_anchored_insert_replay_not_unmodelled(self):
        # a persona-anchored mid-list INSERT in B must NOT false-flag
        # unmodelled (B-derived anchors) — build B by a scratch
        # set_dials WITH insert_after, then residual-compare A->B.
        from annoedit.core import ModProject
        from annoedit.model import apply_changes
        V = make_synthetic_rda(self.W + "/v8.rda")
        pa = ModProject(V)
        prof = pa.by_guid[LEIF]
        # a mid-list insert after an EXISTING sibling (not first-child)
        changes = {"Build/BuildingSpeed":
                   (str(int(prof.dials["Build/BuildingSpeed"]) + 9),
                    "TowersPerLevel")}
        # (Build/BuildingSpeed exists — use a MISSING leaf to exercise
        # the anchored INSERT path instead)
        missing = "Build/NewKnob"
        changes = {missing: ("55", "TowersPerLevel")}
        _t, _applied, errs = apply_changes(
            pa.filetexts[prof.filekey], prof, changes)
        self.assertFalse(errs, errs)
        pa.filetexts[prof.filekey] = _t
        pa.build(self.W + "/b8.rda")
        pb = ModProject(self.W + "/b8.rda")
        from annoedit.ops import _modeled_member_diff
        from annoedit.core import PROFILE_FILES
        fk = [fk for fk, rel in PROFILE_FILES.items()
              if LEIF in {q.guid for q in pb.profiles[fk]}][0]
        self.assertFalse(
            _modeled_member_diff(pa, pb, fk),
            "an anchored mid-list insert must replay byte-exactly")

    def test_h2_foreign_text_residual_still_flags(self):
        from annoedit.core import ModProject, ASSETS_FILE
        V = make_synthetic_rda(self.W + "/v9.rda")
        pa = ModProject(V)
        # a foreign, unmodelled edit inside assets.xml
        pa.assets_text = pa.assets_text.replace(
            "<PassiveTradeSlots>", "<!--x--><PassiveTradeSlots>", 1)
        pa.build(self.W + "/b9.rda")
        pb = ModProject(self.W + "/b9.rda")
        from annoedit.ops import _modeled_member_diff
        self.assertTrue(_modeled_member_diff(pa, pb, ASSETS_FILE))


if __name__ == "__main__":
    unittest.main()
