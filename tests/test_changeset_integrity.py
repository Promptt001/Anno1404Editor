"""ChangeSet integrity.

Stage-validate-swap on every mutator, hard int32 bounds, relations
dedupe/self-war/cross-kind conflict, fertility normalization to int,
negative occ refused, per-GUID dry-run scoping, cached views.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synthetic_rda import make_synthetic_rda


def _mk_session(tag="p3"):
    from annoedit.session import Session
    from annoedit.appsettings import Settings
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


class P3Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = tempfile.mkdtemp()
        cls.A = make_synthetic_rda(cls.W + "/vanilla.rda")

    def setUp(self):
        os.environ.setdefault("ANN0140_HOME", tempfile.mkdtemp())


class ValidationTests(P3Base):
    """Hard validation at the ChangeSet boundary."""

    def test_int32_bounds_refused(self):
        from annoedit.changeset import ChangeSet, ChangeSetError
        cs = ChangeSet()
        for bad in ("99999999999999", str(2 ** 31), str(-2 ** 31 - 1)):
            with self.assertRaises(ChangeSetError):
                cs.add_dial("g", "Military/MaxUnitCount", bad)
        # in-range extremes queue fine
        cs.add_dial("g", "Military/MaxUnitCount", str(2 ** 31 - 1))
        self.assertEqual(cs.dials[("g", "Military/MaxUnitCount")].value,
                         str(2 ** 31 - 1))

    def test_relations_dedupe_keeps_first_order(self):
        from annoedit.changeset import ChangeSet
        cs = ChangeSet()
        e = cs.add_rel("1645021", "War", ["1645020", "1645024", "1645020"])
        self.assertEqual(e.guids, ("1645020", "1645024"))

    def test_relations_self_war_refused(self):
        from annoedit.changeset import ChangeSet, ChangeSetError
        cs = ChangeSet()
        with self.assertRaises(ChangeSetError):
            cs.add_rel("1645021", "War", ["1645021"])

    def test_relations_cross_kind_conflict_refused_both_directions(self):
        # The exclusive pair is
        # War/Ally vs AVOIDWAR only — War∩Ally is TOLERATED by the game
        # (the in-game-confirmed playtested trio carries 1645006 in BOTH
        # War and Ally for Hildegard), and Trade may overlap anything
        # (vanilla Giovanni trades with war targets).
        from annoedit.changeset import ChangeSet, ChangeSetError
        cs = ChangeSet()
        cs.add_rel("1645021", "War", ["1645024"])
        with self.assertRaises(ChangeSetError):
            cs.add_rel("1645021", "AvoidWar", ["1645024"])
        cs2 = ChangeSet()
        cs2.add_rel("1645021", "AvoidWar", ["1645023"])
        with self.assertRaises(ChangeSetError):
            cs2.add_rel("1645021", "Ally", ["1645023"])
        # War∩Ally pending is TOLERATED (playtested trio, in-game confirmed)
        cs3 = ChangeSet()
        cs3.add_rel("1645021", "War", ["1645020"])
        cs3.add_rel("1645021", "Ally", ["1645020"])
        # Trade may overlap War (vanilla Giovanni trades with war targets)
        cs.add_rel("1645021", "Trade", ["1645024"])

    def test_relations_refusal_rolls_back_pending(self):
        # A refused set_relations leaves prior pending edits intact.
        # The refusal trigger is the AvoidWar conflict
        # (War/Ally vs AvoidWar — the empirically exclusive pair).
        from annoedit.session import SessionError
        s, _ = _mk_session()
        s.open(self.A)
        p = s.proj.by_guid["1645021"]
        s.set_relations(p, war=["1645024"])
        with self.assertRaises(SessionError):
            s.set_relations(p, avoidwar=["1645024"])
        # the earlier pending War edit survived
        self.assertEqual(s.rels[p.guid]["War"], ["1645024"])
        s.close()

    def test_fert_normalized_to_int(self):
        s, _ = _mk_session()
        s.open(self.A)
        s.set_fertility("low", "Dates", "40", None)   # GUI passes strings
        e = s.cs.fert[("low", "Dates")]
        self.assertIsInstance(e.north, int)
        self.assertEqual(e.north, 40)
        # out-of-range refuses BEFORE the engine runs
        from annoedit.session import SessionError
        with self.assertRaises(SessionError):
            s.set_fertility("low", "Dates", "101", None)
        s.close()

    def test_negative_occ_refused_session_level(self):
        from annoedit.session import SessionError
        s, _ = _mk_session()
        s.open(self.A)
        with self.assertRaises(SessionError):
            s.set_extra("Noria", "NoriaEndRadius", "99", occ=-1)
        self.assertEqual(s.cs.extras, {})
        s.close()


class TransactionTests(P3Base):
    """Stage -> validate -> swap on EVERY mutator."""

    def test_refused_dial_never_poisons_later_edits(self):
        from annoedit.session import SessionError
        s, _ = _mk_session()
        s.open(self.A)
        leif = s.proj.by_guid["1645021"]
        s.set_dial(leif, "Military/MaxUnitCount", "50")
        with self.assertRaises(SessionError):
            s.set_dial(leif, "Military", "5")     # container path
        self.assertNotIn(("1645021", "Military"), s.cs.dials)
        # the earlier VALID pending edit survived the refusal
        self.assertEqual(s.changes[leif.guid]["Military/MaxUnitCount"], "50")
        # later edits on ANY character still succeed
        s.set_dial(s.proj.by_guid["1645025"], "Military/MaxUnitCount", "60")
        s.close()

    def test_extras_refusal_keeps_pending(self):
        from annoedit.session import SessionError
        s, _ = _mk_session()
        s.open(self.A)
        s.set_extra("Bakery", "ProductionTime", "12000")
        with self.assertRaises(SessionError):
            s.set_extra("No Such Asset", "ProductionTime", "1")
        self.assertIn(("Bakery", "ProductionTime", 0), s.cs.extras)
        s.close()


class ViewAndIndexTests(P3Base):
    """Cached views + per-GUID index."""

    def test_views_cached_until_change(self):
        s, _ = _mk_session()
        s.open(self.A)
        leif = s.proj.by_guid["1645021"]
        s.set_dial(leif, "Military/MaxUnitCount", "50")
        v1 = s.changes
        self.assertIs(v1, s.changes)             # cached: same object
        s.set_dial(leif, "Build/BuildingSpeed", "150")
        self.assertIsNot(v1, s.changes)          # invalidated by the edit
        self.assertEqual(s.changes[leif.guid],
                         {"Military/MaxUnitCount": "50",
                          "Build/BuildingSpeed": "150"})
        # clear path bumps too
        s.cs.drop_profile(leif.guid)
        self.assertEqual(s.changes, {})
        s.close()

    def test_dial_index_order_and_requeue(self):
        from annoedit.changeset import ChangeSet
        cs = ChangeSet()
        cs.add_dial("g1", "A/B", "1")
        cs.add_dial("g1", "C/D", "2")
        cs.add_dial("g1", "A/B", "3")            # re-queue keeps position
        self.assertEqual(list(cs.dial_map("g1")), ["A/B", "C/D"])
        self.assertEqual(cs.dial_map("g1"), {"A/B": "3", "C/D": "2"})
        cs.add_dial("g2", "A/B", "9")
        self.assertEqual(cs.dial_guids(), ["g1", "g2"])
        snap = cs.snapshot()
        cs.drop_dial("g1", "C/D")
        self.assertEqual(snap.dial_map("g1"), {"A/B": "3", "C/D": "2"})

    def test_flash_subtractive_clear_refreshes_views(self):
        s, _ = _mk_session()
        C = self.W + "/p3.rda"
        import shutil
        shutil.copy(self.A, C)
        s.open(C)
        leif = s.proj.by_guid["1645021"]
        s.set_dial(leif, "Military/MaxUnitCount", "55")
        s.flash(C)
        self.assertEqual(s.changes, {})          # flashed edit cleared
        s.close()


if __name__ == "__main__":
    unittest.main()
