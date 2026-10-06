"""Baselines and drift.

- Drift is computed against the opened baseline with pending edits
  taken into account, across all four surfaces (dials, relations,
  EXTRAS, fertility).
- Session.baselines names the three baseline sources; Vanilla mode
  reverts relations as well as dials.
- The GUI drift check runs off the Tk thread.

Each session uses its own backup/export roots (two live sessions must
never share a store, or their flocks would collide).
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synthetic_rda import make_synthetic_rda           # noqa: E402

from annoedit.appsettings import Settings              # noqa: E402
from annoedit.session import Session                   # noqa: E402

LEIF = "1645021"


def _make_session(tmp, i, live=None):
    ses = Session(backup_root=os.path.join(tmp, f"b{i}"),
                  exports_root=os.path.join(tmp, f"e{i}"),
                  settings=Settings(os.path.join(tmp, f"c{i}")),
                  persona_dirs=("../annoedit/presets",))
    if live:
        ses.settings.set("live_path", live)
    return ses


class DriftTests(unittest.TestCase):
    """Correct drift on all four surfaces, pending subtracted."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr4_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(os.path.join(self.tmp, "game",
                                                    "data1.rda"))

    def test_no_drift_when_live_equals_baseline(self):
        ses = _make_session(self.tmp, 1, live=self.game)
        ses.open(self.game)
        self.assertFalse(ses.target_drift(), 'falsy-not-None')

    def test_f05_no_false_positive_with_pending_edits(self):
        # live == baseline; pending edits must NOT count as drift (the
        # old check merged pending into the baseline -> (1, 1, 2) on every
        # normal save)
        ses = _make_session(self.tmp, 1, live=self.game)
        ses.open(self.game)
        leif = ses.proj.by_guid[LEIF]
        ses.set_dial(leif, "Military/MaxUnitCount", "60")
        self.assertFalse(ses.target_drift(), 'falsy-not-None')

    def test_f05_pending_edit_already_landed_is_not_drift(self):
        # live carries OUR pending edit -> not drift (subtraction)
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        s1.set_dial(s1.proj.by_guid[LEIF], "Military/MaxUnitCount", "77")
        live = os.path.join(self.tmp, "live1.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        s2.set_dial(s2.proj.by_guid[LEIF], "Military/MaxUnitCount", "77")
        self.assertFalse(s2.target_drift(), 'falsy-not-None')

    def test_f05_foreign_dial_in_live_counts(self):
        # A foreign dial in live with NO pending
        # decision is KEPT by the replay — drift None, and it must
        # SURVIVE a save (the old code counted it as 'will be reverted').
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        s1.set_dial(s1.proj.by_guid[LEIF], "Military/MaxUnitCount", "77")
        live = os.path.join(self.tmp, "live2.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        self.assertFalse(s2.target_drift(), 'falsy-not-None')
        s2.set_dial(s2.proj.by_guid[LEIF], "Military/AttackDelay", "3")
        s2.flash(target=live)   # sync flash defaults to in-place; save to LIVE
        from annoedit.core import ModProject
        lp = ModProject(live)
        self.assertEqual(lp.by_guid[LEIF].dials["Military/MaxUnitCount"],
                         "77", "the foreign live dial must survive")
        self.assertEqual(lp.by_guid[LEIF].dials["Military/AttackDelay"],
                         "3", "our own edit lands on top")

    def test_f05_extras_drift_in_live_counts(self):
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        cat = s1.proj.extras_catalog()
        asset = tag = vals = None
        for section, tags in cat.items():
            for tg, assets in tags.items():
                for a, v in assets.items():
                    if v:
                        asset, tag, vals = a, tg, v
                        break
                if asset:
                    break
            if asset:
                break
        self.assertIsNotNone(asset, "fixture must carry an extras value")
        s1.set_extra(asset, tag, int(vals[0]) + 5)
        live = os.path.join(self.tmp, "live3.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        # The foreign extras leaf is KEPT (drift None) and
        # survives a save
        self.assertFalse(s2.target_drift(), 'falsy-not-None')
        s2.set_dial(s2.proj.by_guid[LEIF], "Military/AttackDelay", "3")
        s2.flash(target=live)   # save to LIVE
        from annoedit.core import ModProject
        lp = ModProject(live)
        self.assertEqual(
            [str(int(vals[0]) + 5)] * len(vals),
            lp.extras_catalog()["production"][tag][asset],
            "the foreign extras edit must survive")

    def test_f05_extras_pending_landed_not_drift(self):
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        cat = s1.proj.extras_catalog()
        asset = tag = vals = None
        for section, tags in cat.items():
            for tg, assets in tags.items():
                for a, v in assets.items():
                    if v:
                        asset, tag, vals = a, tg, v
                        break
                if asset:
                    break
            if asset:
                break
        s1.set_extra(asset, tag, int(vals[0]) + 5)
        live = os.path.join(self.tmp, "live4.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        s2.set_extra(asset, tag, int(vals[0]) + 5)
        self.assertFalse(s2.target_drift(), 'falsy-not-None')

    def test_f05_fertility_drift_in_live_counts(self):
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        row = s1.proj.fertility_catalog()[0]
        s1.set_fertility(row["tier"], row["crop"],
                         (row["north"] + 10) % 100)
        live = os.path.join(self.tmp, "live5.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        # The foreign fertility rate is KEPT (drift None)
        self.assertFalse(s2.target_drift(), 'falsy-not-None')
        s2.set_dial(s2.proj.by_guid[LEIF], "Military/AttackDelay", "3")
        s2.flash(target=live)   # save to LIVE
        from annoedit.core import ModProject
        lp = ModProject(live)
        tier, crop, nn = row["tier"], row["crop"], (row["north"] + 10) % 100
        lrow = [r for r in lp.fertility_catalog()
                if (r["tier"], r["crop"]) == (tier, crop)][0]
        self.assertEqual(lrow["north"], nn, "the foreign fert edit survives")

    def test_f05_fertility_pending_landed_not_drift(self):
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        row = s1.proj.fertility_catalog()[0]
        nn = (row["north"] + 10) % 100
        s1.set_fertility(row["tier"], row["crop"], nn)
        live = os.path.join(self.tmp, "live6.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        # a ONE-SIDED (north-only) pending edit that landed is not drift
        s2.set_fertility(row["tier"], row["crop"], nn)
        self.assertFalse(s2.target_drift(), 'falsy-not-None')

    def test_f05_relations_pending_landed_not_drift(self):
        # live carries OUR pending relations edit -> not drift (the
        # subtraction must be PER SURFACE: relations pending subtracts
        # from n_rel, never from n_dial — a draft mixed the counters)
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        guids = [g for g in s1.proj.by_guid if g != LEIF][:1]
        s1.set_relations(s1.proj.by_guid[LEIF], war=guids)
        live = os.path.join(self.tmp, "liveR.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        s2.set_relations(s2.proj.by_guid[LEIF], war=guids)
        self.assertFalse(s2.target_drift(), 'falsy-not-None')

    def test_f05_relations_drift_counts(self):
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        guids = [g for g in s1.proj.by_guid if g != LEIF][:1]
        s1.set_relations(s1.proj.by_guid[LEIF], war=guids)
        live = os.path.join(self.tmp, "live7.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2, live=live)
        s2.open(self.game)
        # The foreign relations list is KEPT (drift None) and
        # survives a save
        self.assertFalse(s2.target_drift(), 'falsy-not-None')
        s2.set_dial(s2.proj.by_guid[LEIF], "Military/AttackDelay", "3")
        s2.flash(target=live)   # save to LIVE
        from annoedit.core import ModProject
        lp = ModProject(live)
        self.assertEqual(lp.relations(lp.by_guid[LEIF])["War"], guids,
                         "the foreign relations edit must survive")

    def test_in_place_flash_never_reports_drift(self):
        ses = _make_session(self.tmp, 1)
        ses.open(self.game)
        leif = ses.proj.by_guid[LEIF]
        ses.set_dial(leif, "Military/MaxUnitCount", "60")
        self.assertFalse(ses.target_drift(self.game), 'falsy-not-None')


class BaselineTests(unittest.TestCase):
    """The three baseline sources, named."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr4b_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(os.path.join(self.tmp, "game",
                                                    "data1.rda"))

    def test_baselines_naming(self):
        ses = _make_session(self.tmp, 1)
        ses.open(self.game)
        b = ses.baselines()
        self.assertEqual(b["opened"], os.path.abspath(self.game))
        self.assertIsNone(b["reference_vanilla"])   # nothing provided yet
        # no provided copy, but open() captured a first-open snapshot ->
        # the restore source is that snapshot, labelled unverified
        self.assertIn("unverified", b["restore_source"][1])

    def test_reference_vanilla_when_provided(self):
        ses = _make_session(self.tmp, 1)
        ses.provide_vanilla(self.game)
        ses.open(self.game)
        b = ses.baselines()
        self.assertEqual(b["reference_vanilla"],
                         ses.exports_store.vanilla_path)
        self.assertEqual(b["restore_source"][0],
                         ses.exports_store.vanilla_path)
        self.assertIn("provided", b["restore_source"][1])


class VanillaModeTests(unittest.TestCase):
    """Remainder: 'vanilla' mode reverts relations + globals too."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr4v_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(os.path.join(self.tmp, "game",
                                                    "data1.rda"))

    def test_vanilla_mode_reverts_relations(self):
        # live (opened) carries a foreign WAR relation; vanilla mode must
        # queue the revert to the reference's list
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        guids = [g for g in s1.proj.by_guid if g != LEIF][:1]
        s1.set_relations(s1.proj.by_guid[LEIF], war=guids)
        live = os.path.join(self.tmp, "liveV.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2)
        s2.provide_vanilla(self.game)
        s2.open(live)
        leif = s2.proj.by_guid[LEIF]
        self.assertEqual(s2.proj.relations(leif).get("War"), guids)
        s2.set_mode(leif, "vanilla")
        # the pending relations edit reverts War back to the reference
        self.assertEqual(s2.rels.get(LEIF, {}).get("War"), [])

    def test_vanilla_mode_reverts_globals(self):
        # opened archive carries a modded extras value + fertility rate;
        # vanilla mode queues reverts for BOTH global surfaces
        s1 = _make_session(self.tmp, 1)
        s1.open(self.game)
        cat = s1.proj.extras_catalog()
        asset = tag = vals = None
        for section, tags in cat.items():
            for tg, assets in tags.items():
                for a, v in assets.items():
                    if v:
                        asset, tag, vals = a, tg, v
                        break
                if asset:
                    break
            if asset:
                break
        s1.set_extra(asset, tag, int(vals[0]) + 5)
        row = s1.proj.fertility_catalog()[0]
        s1.set_fertility(row["tier"], row["crop"],
                         (row["north"] + 10) % 100)
        live = os.path.join(self.tmp, "liveG.rda")
        s1.export(live)
        s2 = _make_session(self.tmp, 2)
        s2.provide_vanilla(self.game)
        s2.open(live)
        leif = s2.proj.by_guid[LEIF]
        # Set_mode(vanilla) no longer
        # queues GLOBAL extras/fertility reverts (a per-character action
        # must never touch global pending state) — the explicit
        # revert_globals_to_reference() action does that now.
        s2.set_mode(leif, "vanilla")
        self.assertIsNone(s2.cs.extra_value(asset, tag, 0))
        s2.revert_globals_to_reference()
        # extras: a pending edit back to the reference value
        self.assertEqual(s2.cs.extra_value(asset, tag, 0), str(vals[0]))
        # fertility: a pending edit back to the reference north
        e = s2.cs.fert.get((row["tier"], row["crop"]))
        self.assertIsNotNone(e)
        self.assertEqual(e.north, row["north"])
        self.assertEqual(e.south, row["south"])


if __name__ == "__main__":
    unittest.main()
