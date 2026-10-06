"""Performance budget guards for the EXTRAS pipeline.

A full parse of the comment-heavy ~9 MB assets.xml costs ~0.3 s, and
revert-globals can queue 1000+ edits on real data, so re-parsing per
edit would be an O(N x filesize) cliff. parse_assets is cached per text
object (ModProject replaces the text object on every edit, so identity
implies freshness); these tests keep that cliff from returning.

Budgets are generous (10x the measured cost) to stay robust across
machines, but tight enough that a per-edit full re-parse would blow
them by orders of magnitude.
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)


def _big_assets_text(n_assets=8000, target_mb=9.0):
    """A large, comment-heavy assets.xml like the real one (shape-probe:
    ~9.4 MB real file, comments trigger the mask pass)."""
    parts = ["<?xml version=\"1.0\"?>", "<Assets>"]
    for i in range(n_assets):
        parts.append(
            "<!-- asset %d: developer note %s -->" % (i, "x" * 60))
        parts.append(
            "<Asset><Template>Building</Template>"
            "<Values><WareProduction>"
            "<ProductionTime>15000</ProductionTime>"
            "<Product>Milk</Product>"
            "</WareProduction>"
            "<MoneyCost>10</MoneyCost>"
            "</Values>"
            "<Standard><Name>Asset%04d</Name>"
            "<GUID>%d</GUID></Standard></Asset>" % (i, 100000 + i))
    parts.append("</Assets>")
    text = "\n".join(parts)
    # pad with trailing comments to the real size class if needed
    while len(text) < target_mb * 1e6:
        text += "\n<!-- " + "x" * 200 + " -->"
    return text


class ParseBudgetTests(unittest.TestCase):
    """parse_assets must be effectively free on repeat for the same text
    object, and set_extra on a large file must not re-parse per call."""

    @classmethod
    def setUpClass(cls):
        cls.text = _big_assets_text()
        from annoedit.extras import parse_assets
        from annoedit.extras import _PARSE_CACHE
        _PARSE_CACHE.clear()
        t0 = time.perf_counter()
        parse_assets(cls.text)
        cls._cold_parse_seconds = time.perf_counter() - t0
        _PARSE_CACHE.clear()

    def test_parse_cached_repeat_is_free(self):
        from annoedit.extras import parse_assets
        t0 = time.perf_counter()
        first = parse_assets(self.text)
        t_first = time.perf_counter() - t0
        t0 = time.perf_counter()
        second = parse_assets(self.text)
        t_cached = time.perf_counter() - t0
        self.assertGreater(len(first), 7000)
        self.assertIs(first, second,
                       "repeat parse did not hit the identity cache")
        # budget: cached repeat must be 50x faster than the cold parse
        self.assertLess(t_cached, max(t_first / 50.0, 0.02),
                        f"cold {t_first:.3f}s vs cached {t_cached:.6f}s")

    def test_new_text_object_reparses(self):
        from annoedit.extras import parse_assets
        parse_assets(self.text)
        # a NEW text object (e.g. ModProject after set_extra) must NOT
        # return the stale parse of the old object
        mutated = self.text.replace("<MoneyCost>10</MoneyCost>",
                                    "<MoneyCost>20</MoneyCost>", 1)
        fresh = parse_assets(mutated)
        self.assertIsNot(fresh, parse_assets(self.text))
        self.assertEqual(len(fresh), len(parse_assets(self.text)))

    def test_set_extra_budget_on_large_file(self):
        from annoedit.extras import parse_assets, set_extra
        # warm the cache like a session does (catalog built once)
        parse_assets(self.text)
        t0 = time.perf_counter()
        nt, old = set_extra(self.text, "Asset0001", "ProductionTime", "9")
        t_edit = time.perf_counter() - t0
        self.assertEqual(old, "15000")
        # budget: one edit on a warm 9 MB file must stay well under
        # 0.1 s (the pre-fix per-edit re-parse was ~0.3 s on the real
        # file; the same class of cost would blow this budget)
        self.assertLess(t_edit, 0.1,
                        f"set_extra took {t_edit:.3f}s on a warm cache")

    def test_batch_edits_budget(self):
        """A 20-edit batch (the revert-globals/build shape, scaled
        down): one parse for the guard checks + ONE batch apply "
        "(set_extras); total time must scale with the number of "
        "edits, not edits x full-parse."""
        from annoedit.extras import set_extras
        parse_budget = self._cold_parse_seconds
        edits = [{"asset": "Asset%04d" % (i + 2),
                  "tag": "MoneyCost", "value": "42"}
                 for i in range(20)]
        t0 = time.perf_counter()
        batch_text, results = set_extras(self.text, edits)
        dt = time.perf_counter() - t0
        self.assertNotEqual(batch_text, self.text)
        self.assertEqual(results, ["10"] * 20)
        # 20 edits must cost about ONE parse (plus per-edit O(block)
        # work), never 20 parses: budget 3x one cold parse
        self.assertLess(dt, parse_budget * 3.0 + 0.1,
                        f"20-edit batch took {dt:.2f}s vs one parse "
                        f"{parse_budget:.2f}s (per-edit re-parse "
                        "regression?)")


if __name__ == "__main__":
    unittest.main()
