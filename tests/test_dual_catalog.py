#!/usr/bin/env python3
"""Dual-catalog and sortable-column tests.

The EXTRAS/FERTILITY tabs show two reference columns:
  * 'vanilla' = the provided vanilla copy (reference catalog), else the
                opened archive;
  * 'current' = what the opened archive actually contains (what an edit
                replaces), which matters when editing a modded data1.rda.
'old' in the review rows = the current (opened) value.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixture import TEST_RDA, HAVE_RDA                      # noqa: E402
from synthetic_rda import make_synthetic_rda                 # noqa: E402
from annoedit.session import Session                        # noqa: E402
from annoedit.appsettings import Settings                   # noqa: E402


class _DualSandbox(unittest.TestCase):
    """A vanilla copy provided (variant 0) + a MODDED archive opened
    (variant 1 — synthetic assets.xml values differ by variant): the two
    catalogs MUST disagree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dual_")
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
        # variant 1 raises PassiveTradeSlots on the warehouses. The
        # synthetic fixture has TWO Warehouse01 assets (ambiguous name;
        # the catalog keys are 'Name [GUID]' display forms)
        self.asset = "Warehouse01 [1001]"
        self.tag = "PassiveTradeSlots"

    def _ref_vals(self, catalog):
        for section in catalog.values():
            fam = section.get(self.tag)
            if fam and fam.get(self.asset):
                return fam[self.asset]
        return None

    def _cur_vals(self, catalog):
        return self._ref_vals(catalog)


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class DualCatalogTests(_DualSandbox):

    def test_extras_current_differs_from_vanilla_reference(self):
        ref = self._ref_vals(self.ses.extras_catalog())
        cur = self._cur_vals(self.ses.extras_current())
        self.assertIsNotNone(ref)
        self.assertIsNotNone(cur)
        self.assertNotEqual(ref, cur, "modded open must differ from the "
                                       "provided vanilla reference")
        # the reference must be the VANILLA (variant 0) value
        self.assertEqual(ref, ["4"])
        self.assertEqual(cur, ["5"])

    def test_fertility_current_matches_opened_and_reference(self):
        # the synthetic fert file does not vary by variant — current and
        # reference are equal but MUST both be present (not None)
        cur = self.ses.fertility_current()
        ref = self.ses.fertility_catalog()
        self.assertTrue(len(cur) > 0 and len(ref) > 0)

    def test_no_vanilla_copy_means_current_equals_reference(self):
        # without a provided vanilla copy the reference IS the opened
        # archive — the two catalogs agree
        self.ses.close()
        self.ses2 = Session(
            backup_root=os.path.join(self.tmp, "b2"),
            exports_root=os.path.join(self.tmp, "e2"),
            settings=Settings(os.path.join(self.tmp, "c2")))
        self.ses2.open(self.modded)
        self.assertEqual(self._ref_vals(self.ses2.extras_catalog()),
                         self._cur_vals(self.ses2.extras_current()))

    def test_review_old_uses_current_value(self):
        # 'old' in the review rows = the value in the OPENED archive
        # the edit replaces THAT value, not the reference value
        cur = self._cur_vals(self.ses.extras_current())[0]
        self.ses.set_extra(self.asset, self.tag, "12")
        rows, totals = self.ses.pending_change_rows()
        xr = [r for r in rows if r["section"] == "EXTRAS"]
        self.assertEqual(len(xr), 1)
        self.assertEqual(xr[0]["old"], cur)
        self.assertEqual(totals["extras"], 1)

    def test_clear_extras_drops_all_pending(self):
        # 'Reset all extras' goes through Session.clear_extras
        self.ses.set_extra(self.asset, self.tag, "12")
        self.assertTrue(self.ses.extras)
        self.ses.clear_extras()
        self.assertEqual(self.ses.extras, {})

    def test_catalog_cached_per_project(self):
        # Repeated catalog calls on one project return the same
        # (cached) object; an edit invalidates the cache
        p = self.ses.proj
        c1 = p.extras_catalog()
        c2 = p.extras_catalog()
        self.assertIs(c1, c2)
        p.set_extra(self.asset, self.tag, "12")
        c3 = p.extras_catalog()
        self.assertIsNot(c1, c3)
        f1 = p.fertility_catalog()
        f2 = p.fertility_catalog()
        self.assertIs(f1, f2)


class SortKeyTests(unittest.TestCase):
    """Numeric-aware sort keys (the shared widget helper)."""

    def test_numbers_sort_numerically(self):
        from annoedit.gui.logic import sort_key
        vals = ["90000", "12000", "1500", "250"]
        self.assertEqual(sorted(vals, key=sort_key),
                         ["250", "1500", "12000", "90000"])

    def test_numbers_before_text(self):
        from annoedit.gui.logic import sort_key
        self.assertLess(sort_key("42"), sort_key("abc"))

    def test_prefixed_numbers_and_negatives(self):
        from annoedit.gui.logic import sort_key
        self.assertLess(sort_key("-5"), sort_key("0"))
        self.assertLess(sort_key("N=10  S=20"), sort_key("N=90  S=0"))

    def test_none_and_empty_sort_as_text(self):
        from annoedit.gui.logic import sort_key
        # empty/None are TEXT class (1, ...) — they sort AFTER numbers
        # (blank pending cells group at the bottom of a numeric column)
        self.assertLess(sort_key("1"), sort_key(""))
        self.assertLess(sort_key(None), sort_key("abc"))
        self.assertEqual(sort_key(None), sort_key(""))


if __name__ == "__main__":
    unittest.main()
