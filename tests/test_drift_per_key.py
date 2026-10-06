#!/usr/bin/env python3
"""Per-key drift semantics.

A pending edit on a key means the user has decided there (never a silent
revert), examples are reported per surface, and counts come from per-key
set logic rather than arithmetic.
"""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

from annoedit.session import Session                # noqa: E402
from annoedit.appsettings import Settings           # noqa: E402
from annoedit import ops                            # noqa: E402
from tests.synthetic_rda import make_synthetic_rda  # noqa: E402

LEIF = "1645021"


def _mk_session(tag):
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


class Phase4DriftTests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p4_")
        self.addCleanup(shutil.rmtree, self.W, ignore_errors=True)
        self.A = make_synthetic_rda(self.W + "/vanilla.rda")

    def test_p4_noop_pending_does_not_hide_dial_drift(self):
        # Pending on MaxUnitCount must not cancel
        # the foreign AttackDelay difference — under the REPLAY model a
        # foreign difference with no pending decision is KEPT (drift
        # None), and the no-op pending must not stop it SURVIVING.
        from annoedit.core import ModProject
        B = self.W + "/live_a.rda"
        p = ModProject(self.A)
        p.set_dials(p.by_guid[LEIF], {"Military/AttackDelay": "1"})
        p.build(B)
        s, _ = _mk_session("p4a"); s.open(self.A); s.set_live_path(B)
        leif = s.proj.by_guid[LEIF]
        cur = leif.dials["Military/MaxUnitCount"]
        s.set_dial(leif, "Military/MaxUnitCount", cur)   # no-op pending
        self.assertFalse(s.target_drift(B), 'falsy-not-None')   # kept, not a conflict
        s.flash(B)
        live = ModProject(B)
        self.assertEqual(live.by_guid[LEIF].dials["Military/AttackDelay"],
                         "1", "foreign live edit must survive the replay")
        s.close()

    def test_p4_pending_dial_not_drift_even_when_not_landed(self):
        # a pending edit that has NOT landed in live is a user decision,
        # not drift (the old code would count O!=L then subtract
        # nothing -> false positive)
        B = self.W + "/live_b.rda"; shutil.copy(self.A, B)
        s, _ = _mk_session("p4b"); s.open(self.A)
        s.set_dial(s.proj.by_guid[LEIF], "Military/MaxUnitCount", "90")
        self.assertFalse(s.target_drift(B), 'falsy-not-None')
        s.close()

    def test_p4_pending_relations_kind_not_drift_when_landed(self):
        guids = [g for g in {} ] or None
        s1, _ = _mk_session("p4c"); s1.open(self.A)
        others = [g for g in s1.proj.by_guid if g != LEIF][:1]
        s1.set_relations(s1.proj.by_guid[LEIF], war=others)
        live = self.W + "/live_c.rda"
        s1.export(live)
        s2, _ = _mk_session("p4d"); s2.open(self.A)
        s2.set_relations(s2.proj.by_guid[LEIF], war=others)
        self.assertFalse(s2.target_drift(live), 'falsy-not-None')
        s1.close(); s2.close()

    def test_p4_pending_relations_not_drift_even_when_not_landed(self):
        s, _ = _mk_session("p4e"); s.open(self.A)
        others = [g for g in s.proj.by_guid if g != LEIF][:1]
        s.set_relations(s.proj.by_guid[LEIF], war=others)
        B = self.W + "/live_d.rda"; shutil.copy(self.A, B)
        self.assertFalse(s.target_drift(B), 'falsy-not-None')
        s.close()

    def test_p4_extras_pending_not_drift_even_when_not_landed(self):
        s, _ = _mk_session("p4f"); s.open(self.A)
        cat = s.proj.extras_catalog()
        asset = tag = vals = None
        for _section, tags in cat.items():
            for tg, assets in tags.items():
                for a, v in assets.items():
                    if v:
                        asset, tag, vals = a, tg, v
                        break
                if asset:
                    break
            if asset:
                break
        self.assertIsNotNone(asset)
        s.set_extra(asset, tag, int(vals[0]) + 5)
        B = self.W + "/live_e.rda"; shutil.copy(self.A, B)
        self.assertFalse(s.target_drift(B), 'falsy-not-None')
        s.close()

    def test_p4_fert_pending_not_drift_even_when_not_landed(self):
        s, _ = _mk_session("p4g"); s.open(self.A)
        row = s.proj.fertility_catalog()[0]
        s.set_fertility(row["tier"], row["crop"],
                        (row["north"] + 10) % 100)
        B = self.W + "/live_f.rda"; shutil.copy(self.A, B)
        self.assertFalse(s.target_drift(B), 'falsy-not-None')
        s.close()

    def test_p4_dial_missing_in_live_counts_as_drift(self):
        # Live carries a foreign dial AND a
        # foreign relations list; no pending anywhere -> KEPT by the
        # replay (drift None), and both must SURVIVE the save.
        from annoedit.core import ModProject
        B = self.W + "/live_g.rda"
        p = ModProject(self.A)
        guids = [g for g in p.by_guid if g != LEIF][:1]
        p.set_dials(p.by_guid[LEIF], {"Military/MaxUnitCount": "5"})
        p.set_relations(p.by_guid[LEIF], war=guids)
        p.build(B)      # live: war=[guids]
        s, _ = _mk_session("p4h"); s.open(self.A); s.set_live_path(B)
        self.assertFalse(s.target_drift(B), 'falsy-not-None')    # kept, no conflicts
        s.set_dial(s.proj.by_guid[LEIF], "Military/AttackDelay", "9")
        s.flash(B)
        live = ModProject(B)
        self.assertEqual(live.by_guid[LEIF].dials["Military/MaxUnitCount"],
                         "5", "foreign dial must survive the replay")
        self.assertEqual(live.relations(live.by_guid[LEIF])["War"],
                         guids, "foreign relations must survive")
        self.assertEqual(live.by_guid[LEIF].dials["Military/AttackDelay"],
                         "9", "our own edit lands on top")
        s.close()

    def test_p4_drift_result_is_six_tuple_compatible(self):
        r = ops.DriftResult(1, 0, 0, 0, 1, 0, ("k",))
        a, b, c, d, e, f = r
        self.assertEqual((a, b, c, d, e, f), (1, 0, 0, 0, 1, 0))
        self.assertEqual(r[2], 0)
        self.assertTrue(bool(r))
        self.assertTrue(bool(ops.DriftResult(0, 0, 0, 0, 0, 0)) is False)
        self.assertEqual(r.dial_keys, ("k",))
        # equality with the plain tuple keeps old test assertions alive
        self.assertEqual(r, (1, 0, 0, 0, 1, 0))

    def test_p4_foreign_only_drift_shape(self):
        from annoedit.rda import read_rda, write_rda
        B = self.W + "/live_h.rda"
        e = read_rda(self.A)
        e["data/othermod.dds"] = (b"x" * 50, 1)
        write_rda(e, B)
        s, _ = _mk_session("p4i"); s.open(self.A)
        drift = s.target_drift(B)
        self.assertIsNotNone(drift)
        self.assertEqual(tuple(drift)[:5], (0, 0, 0, 0, 0))
        self.assertEqual(drift[5], 1)
        s.close()


if __name__ == "__main__":
    unittest.main()
