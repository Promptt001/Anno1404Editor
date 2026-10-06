#!/usr/bin/env python3
"""Non-vanilla highlight/filter tests.

The GUI classifies every row in the dial/EXTRAS/fertility tables as
"non-vanilla" when the current (opened archive) value differs from the
vanilla reference (the stored vanilla copy). Such rows are highlighted,
and a "Non-vanilla only" filter narrows the table to them. Without a
stored vanilla copy the highlight/filter stay off (the fallback
reference would be the opened archive itself) and the count line says
so.

Headless: gui/logic.py is tkinter-free, so these run without python3-tk.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixture import TEST_RDA, HAVE_RDA                    # noqa: E402
from synthetic_rda import make_synthetic_rda              # noqa: E402
from annoedit.session import Session                     # noqa: E402
from annoedit.appsettings import Settings                # noqa: E402
from annoedit.gui.logic import (differs_from_vanilla,   # noqa: E402
                                fertility_row_differs)


class _DualSandbox(unittest.TestCase):
    """Vanilla copy provided (variant 0) + modded archive opened
    (variant 1) — the same sandbox the dual-catalog tests use."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nv_")
        self.addCleanup(os.chdir, os.getcwd())
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vanilla = make_synthetic_rda(
            os.path.join(self.tmp, "van", "data1.rda"), variant=0)
        self.modded = make_synthetic_rda(
            os.path.join(self.tmp, "mod", "data1.rda"), variant=1)
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=Settings(os.path.join(self.tmp, "cfg")))
        self.ses.provide_vanilla(self.vanilla)
        self.ses.open(self.modded)
        self.asset = "Warehouse01 [1001]"
        self.tag = "PassiveTradeSlots"

    def _ref_vals(self, catalog):
        for section in catalog.values():
            fam = section.get(self.tag)
            if fam and fam.get(self.asset):
                return fam[self.asset]
        return None


class DiffersFromVanillaTests(unittest.TestCase):
    """Pure classifier rules (no tkinter needed)."""

    def test_no_reference_means_not_nonvanilla(self):
        # the trust rule: no stored vanilla copy -> highlight stays OFF
        self.assertFalse(differs_from_vanilla("40", None))
        self.assertFalse(differs_from_vanilla(None, None))
        self.assertFalse(differs_from_vanilla("", None))

    def test_equal_values_are_vanilla(self):
        self.assertFalse(differs_from_vanilla("40", "40"))
        self.assertFalse(differs_from_vanilla("40 ", "40"))
        self.assertFalse(differs_from_vanilla(" 40", "40 "))
        self.assertFalse(differs_from_vanilla("abc", "abc"))

    def test_changed_value_is_nonvanilla(self):
        self.assertTrue(differs_from_vanilla("50", "40"))
        self.assertTrue(differs_from_vanilla("abc", "abd"))
        self.assertTrue(differs_from_vanilla("40.0", "40"))

    def test_missing_on_one_side_is_nonvanilla(self):
        # current is None but vanilla has a value (a mod removed it)
        self.assertTrue(differs_from_vanilla(None, "40"))
        # current has a value but vanilla is blank (a mod added it)
        self.assertTrue(differs_from_vanilla("40", ""))
        # both blank = vanilla
        self.assertFalse(differs_from_vanilla(None, ""))
        self.assertFalse(differs_from_vanilla("", ""))

    def test_extras_occurrence_lists(self):
        # equal lists are vanilla, same length one-changed is non-vanilla
        self.assertFalse(differs_from_vanilla(["A", "B"], ["A", "B"]))
        self.assertTrue(differs_from_vanilla(["A", "X"], ["A", "B"]))
        # length change (a mod added or dropped a level) is non-vanilla
        self.assertTrue(differs_from_vanilla(["A"], ["A", "B"]))
        self.assertTrue(differs_from_vanilla(["A", "B"], ["A"]))
        # list vs non-list (type mismatch) is non-vanilla
        self.assertTrue(differs_from_vanilla("A", ["A"]))
        # missing current list (None) with a vanilla list is non-vanilla
        self.assertTrue(differs_from_vanilla(None, ["A"]))
        # element whitespace is normalized like scalars
        self.assertFalse(differs_from_vanilla(["A ", "B"], ["A", " B"]))

    def test_missing_current_list_with_none_vanilla(self):
        self.assertFalse(differs_from_vanilla(["A"], None))


class FertilityRowDiffersTests(unittest.TestCase):
    """Fertility classification (pure helper, no tkinter needed)."""

    def test_missing_current_row_is_nonvanilla(self):
        # opened archive lacks the crop row the vanilla has -> mod removed it
        self.assertTrue(fertility_row_differs({}, {"north": 40, "south": 0}))
        self.assertTrue(fertility_row_differs(None, {"north": 40, "south": 0}))

    def test_equal_rows_are_vanilla(self):
        self.assertFalse(fertility_row_differs(
            {"north": 40, "south": 0}, {"north": 40, "south": 0}))

    def test_changed_north_or_south_is_nonvanilla(self):
        self.assertTrue(fertility_row_differs(
            {"north": 50, "south": 0}, {"north": 40, "south": 0}))
        self.assertTrue(fertility_row_differs(
            {"north": 40, "south": 20}, {"north": 40, "south": 0}))
        # a missing key on the current side counts as changed (None != 40)
        self.assertTrue(fertility_row_differs(
            {"south": 0}, {"north": 40, "south": 0}))


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class ExtrasNonVanillaTests(_DualSandbox):
    """End-to-end: with a stored vanilla copy, the modded archive's EXTRAS
    values must classify as non-vanilla (the highlight/filter feed)."""

    def test_extras_current_classifies_as_nonvanilla(self):
        ref = self.ses.extras_catalog()
        cur = self.ses.extras_current()
        ref_vals = self._ref_vals(ref)
        cur_vals = self._ref_vals(cur)
        self.assertIsNotNone(ref_vals)
        self.assertIsNotNone(cur_vals)
        # variant 1 raised PassiveTradeSlots on the warehouse -> non-vanilla
        self.assertTrue(differs_from_vanilla(cur_vals, ref_vals))

    def test_extras_nonvanilla_filter_would_show_warehouse(self):
        # the filter row-set: every asset whose current differs from ref
        ref = self.ses.extras_catalog()
        cur = self.ses.extras_current()
        hits = []
        for section, fams in ref.items():
            for tag, fam in fams.items():
                for asset, vals in fam.items():
                    cv = cur.get(section, {}).get(tag, {}).get(asset)
                    if differs_from_vanilla(cv, vals):
                        hits.append((section, tag, asset))
        self.assertIn(("trade", self.tag, self.asset), hits)

    def test_without_vanilla_copy_nothing_classifies(self):
        # fresh session, only the modded archive opened, NO vanilla copy:
        # nothing may classify (the reference would be the opened archive itself)
        self.ses2 = Session(
            backup_root=os.path.join(self.tmp, "backups2"),
            exports_root=os.path.join(self.tmp, "exports2"),
            settings=Settings(os.path.join(self.tmp, "cfg2")))
        self.ses2.open(self.modded)
        self.assertIsNone(self.ses2.vanilla_baseline)


if __name__ == "__main__":
    unittest.main()
