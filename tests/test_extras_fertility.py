#!/usr/bin/env python3
"""EXTRAS + fertility engines and their wiring.

- extras engine (annoedit/extras.py): parse, single/multi-instance
  edits, INSERT shape, refusal rules, ambiguous 'Name [GUID]' addressing.
- fertility engine (annoedit/fertility.py): parse (3 tiers x 16 crops),
  tier-region boundaries, byte-safe span edits, error paths.
- core wiring: ARCHIVE_MEMBERS includes assets.xml and
  randommapgenerator.xml; extras-only / fertility-only / combined builds;
  round trip; scope guards (hardened + vanilla rewrite touch neither).
- session: set_extra/set_fertility validation, catalogs, change report
  sections, _build applies extras+fertility on a fresh project.
- CLI: extras / extras-apply / fertility / fertility-apply.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO)

from fixture import TEST_RDA


class ExtrasEngineTests(unittest.TestCase):
    """Pure engine tests — no game data needed."""

    TEXT = (
        "<Asset><Template>drm</Template><Values>"
        "<Object><ProductionTime>15000</ProductionTime>"
        "<InfluenceRadius>20</InfluenceRadius></Object>"
        "</Values><Standard><Name>Mill</Name><GUID>1</GUID></Standard>"
        "</Asset>"
        "<Asset><Template>drm</Template><Values>"
        "<Object><NoriaEndRadius>26</NoriaEndRadius>"
        "<NoriaEndRadius>25</NoriaEndRadius>"
        "<NoriaEndRadius>24</NoriaEndRadius></Object>"
        "</Values><Standard><Name>Noria</Name><GUID>2</GUID></Standard>"
        "</Asset>"
        "<Asset><Template>drm</Template><Values><Object>"
        "<WareProduction><Product>Book</Product></WareProduction></Object>"
        "</Values><Standard><Name>PrintingHouse</Name><GUID>3</GUID>"
        "</Standard></Asset>"
    )

    def test_parse_assets(self):
        from annoedit.extras import parse_assets
        assets = parse_assets(self.TEXT)
        self.assertEqual([a["name"] for a in assets],
                         ["Mill", "Noria", "PrintingHouse"])

    def test_single_instance_edit(self):
        from annoedit.extras import set_extra
        nt, old = set_extra(self.TEXT, "Mill", "ProductionTime", "7500")
        self.assertEqual(old, "15000")
        self.assertIn("<ProductionTime>7500</ProductionTime>", nt)
        self.assertNotIn("15000", nt)

    def test_multi_instance_edit_requires_occ(self):
        from annoedit.extras import ExtrasError, set_extra
        with self.assertRaises(ExtrasError):
            set_extra(self.TEXT, "Noria", "NoriaEndRadius", "10")

    def test_multi_instance_occ_edit(self):
        from annoedit.extras import set_extra
        nt, old = set_extra(self.TEXT, "Noria", "NoriaEndRadius", "10", 1)
        self.assertEqual(old, "25")
        self.assertIn("<NoriaEndRadius>26</NoriaEndRadius>", nt)
        self.assertIn("<NoriaEndRadius>10</NoriaEndRadius>", nt)
        self.assertIn("<NoriaEndRadius>24</NoriaEndRadius>", nt)

    def test_insert_shape(self):
        # The insert must land INSIDE the proven
        # parent block (<WareProduction>), as its FIRST child — never
        # directly under <Values> (an in-game silent no-op)
        from annoedit.extras import set_extra
        nt, old = set_extra(self.TEXT, "PrintingHouse", "ProductionTime", "1000")
        self.assertIsNone(old)
        self.assertIn("<ProductionTime>1000</ProductionTime>", nt)
        # FIRST child of <WareProduction>, before <Product> (Bakery shape)
        self.assertIn(
            "<WareProduction><ProductionTime>1000</ProductionTime>"
            "<Product>Book</Product>", nt)
        # never directly under <Values> (PrintingHouse asset's Values,
        # split at the WareProduction boundary: the pre-parent part
        # must not carry the tag)
        i = nt.find("<Name>PrintingHouse</Name>")
        vs = nt.rfind("<Values>", 0, i)
        vseg = nt[vs:nt.find("</Values>", vs)]
        self.assertNotIn("<ProductionTime>", vseg.split("<WareProduction>")[0])

    def test_xml_special_refused(self):
        from annoedit.extras import ExtrasError, set_extra
        with self.assertRaises(ExtrasError):
            set_extra(self.TEXT, "Mill", "ProductionTime", "<bad>")

    def test_unknown_asset_refused(self):
        from annoedit.extras import ExtrasError, set_extra
        with self.assertRaises(ExtrasError):
            set_extra(self.TEXT, "Ghost", "ProductionTime", "5")

    def test_ambiguous_guid_addressing(self):
        from annoedit.extras import ExtrasError, find_asset, parse_assets
        two = (self.TEXT +
               "<Asset><Template>drm</Template><Values><Object/>"
               "</Values><Standard><Name>Mill</Name><GUID>9</GUID>"
               "</Standard></Asset>")
        assets = parse_assets(two)
        with self.assertRaises(ExtrasError):
            find_asset(assets, "Mill")           # ambiguous bare name
        a = find_asset(assets, "Mill [9]")        # disambiguated form
        self.assertEqual(a["guid"], "9")


class FertilityEngineTests(unittest.TestCase):
    """Pure engine tests — no game data needed."""

    TEXT = (
        "<RandomMapGenerator><FertilityRates>"
        "<k><ResourceAmount>low</ResourceAmount>\r\n</k>\r\n"
        "<v><k><Fertility>Dates</Fertility>\r\n</k>\r\n"
        "<v><North>0</North>\r\n<South>60</South>\r\n</v>\r\n"
        "<k><Fertility>Spices</Fertility>\r\n</k>\r\n"
        "<v><North>0</North>\r\n<South>90</South>\r\n</v>\r\n"
        "</v>\r\n"
        "<k><ResourceAmount>high</ResourceAmount>\r\n</k>\r\n"
        "<v><k><Fertility>Dates</Fertility>\r\n</k>\r\n"
        "<v><North>0</North>\r\n<South>60</South>\r\n</v>\r\n"
        "</v>\r\n"
        "</FertilityRates></RandomMapGenerator>"
    )

    def test_parse(self):
        from annoedit.fertility import parse_fertility_rates
        rates = parse_fertility_rates(self.TEXT)
        self.assertEqual(set(rates), {"low", "high"})
        self.assertEqual(rates["low"]["Dates"], (0, 60))
        self.assertEqual(rates["high"]["Spices"] if "Spices" in rates["high"]
                         else None, None)  # only Dates in tier high

    def test_edit_north_only(self):
        from annoedit.fertility import parse_fertility_rates, set_fertility
        nt, old = set_fertility(self.TEXT, "low", "Dates", north=40)
        self.assertEqual(old, {"north": "0"})
        r = parse_fertility_rates(nt)
        self.assertEqual(r["low"]["Dates"], (40, 60))   # south untouched
        self.assertEqual(r["low"]["Spices"], (0, 90))   # sibling untouched
        self.assertEqual(r["high"]["Dates"], (0, 60))   # other tier untouched

    def test_edit_combined(self):
        from annoedit.fertility import parse_fertility_rates, set_fertility
        nt, old = set_fertility(self.TEXT, "high", "Dates", north=30, south=80)
        self.assertEqual(old, {"north": "0", "south": "60"})
        self.assertEqual(parse_fertility_rates(nt)["high"]["Dates"], (30, 80))

    def test_error_paths(self):
        from annoedit.fertility import FertilityError, set_fertility
        for kwargs in ({"tier": "odd", "crop": "Dates", "north": 1},
                       {"tier": "low", "crop": "Pizza", "north": 1},
                       {"tier": "low", "crop": "Dates", "north": 101},
                       {"tier": "low", "crop": "Dates", "north": "4x"},
                       {"tier": "low", "crop": "Dates"}):
            with self.assertRaises(FertilityError):
                set_fertility(self.TEXT, **kwargs)

    def test_reapply_byte_identical(self):
        from annoedit.fertility import set_fertility
        nt, _ = set_fertility(self.TEXT, "low", "Dates", north=40)
        nt2, _ = set_fertility(nt, "low", "Dates", north=40)
        self.assertEqual(nt, nt2)


@unittest.skipUnless(os.path.isfile(TEST_RDA), f"test RDA not found: {TEST_RDA}")
class PipelineTests(unittest.TestCase):
    """Core wiring + session + CLI against the real vanilla archive."""

    def test_scope_guard_widened(self):
        from annoedit.core import ARCHIVE_MEMBERS
        self.assertIn("addondata/config/game/assets.xml", ARCHIVE_MEMBERS)
        self.assertIn("addondata/config/game/randommapgenerator.xml",
                      ARCHIVE_MEMBERS)

    def test_fertility_only_build(self):
        from annoedit.core import ModProject
        from annoedit.fertility import (FERT_FILE, parse_fertility_rates)
        from annoedit.rda import read_rda
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "f.rda")
            p = ModProject(TEST_RDA)
            p.set_fertility("low", "Dates", north=40)
            rep = p.build(out)
            self.assertEqual(rep["changed"], [FERT_FILE])
            self.assertEqual(rep["files"], len(p.entries))
            txt = read_rda(out)[FERT_FILE][0].decode("cp1252")
            self.assertEqual(parse_fertility_rates(txt)["low"]["Dates"],
                             (40, 60))

    def test_extras_only_build(self):
        from annoedit.core import ModProject
        from annoedit.extras import ASSETS_FILE
        from annoedit.rda import read_rda
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "x.rda")
            p = ModProject(TEST_RDA)
            p.set_extra("Mill", "ProductionTime", "7500", None)
            rep = p.build(out)
            self.assertIn(ASSETS_FILE, rep["changed"])
            self.assertEqual(rep["files"], len(p.entries))
            self.assertIn(b"<ProductionTime>7500</ProductionTime>",
                          read_rda(out)[ASSETS_FILE][0])

    def test_combined_build_all_three(self):
        from annoedit.core import ModProject
        from annoedit.extras import ASSETS_FILE
        from annoedit.fertility import FERT_FILE
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "c.rda")
            p = ModProject(TEST_RDA)
            prof = p.by_guid["1645021"]
            p.set_dials(prof, {"Build/BuildingSpeed": "100"})
            p.set_extra("Mill", "ProductionTime", "7500", None)
            p.set_fertility("high", "Spices", north=30, south=80)
            rep = p.build(out)
            self.assertEqual(set(rep["changed"]),
                             {"addondata/config/ai/aiprofiles.xml",
                              ASSETS_FILE, FERT_FILE})

    def test_hardened_touches_neither(self):
        from annoedit.core import hardened_build, ModProject
        from annoedit.extras import ASSETS_FILE
        from annoedit.fertility import FERT_FILE
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "h.rda")
            rep, _ = hardened_build(TEST_RDA, out)
            self.assertNotIn(ASSETS_FILE, rep["changed"])
            self.assertNotIn(FERT_FILE, rep["changed"])
            self.assertEqual(rep["files"], len(ModProject(TEST_RDA).entries))

    def test_session_extras_and_fertility(self):
        from annoedit.session import Session
        from annoedit.fertility import FERT_FILE
        from annoedit.rda import read_rda
        with tempfile.TemporaryDirectory() as td:
            ses = Session(backup_root=os.path.join(td, "store"),
                        exports_root=os.path.join(td, "exports"))
            ses.open(TEST_RDA)
            try:
                # extras queue + validation
                ses.set_extra("Mill", "ProductionTime", "7500", None)
                self.assertEqual(len(ses.extras), 1)
                with self.assertRaises(Exception):
                    ses.set_extra("Mill", "ProductionTime", "bad", None)
                # fertility queue + validation
                ses.set_fertility("low", "Dates", north=40)
                self.assertEqual(str(ses.fert[("low", "Dates")][0]), "40")
                self.assertIsNone(ses.fert[("low", "Dates")][1])
                with self.assertRaises(Exception):
                    ses.set_fertility("low", "Dates", north=101)
                # change report carries the new sections
                rep = ses.change_report()
                self.assertIn("EXTRAS (assets.xml", rep)
                self.assertIn("FERTILITY (randommapgenerator.xml", rep)
                # export applies both on a fresh project
                out = os.path.join(td, "s.rda")
                r = ses.export(out)
                self.assertEqual(r["extras_edits"], 1)
                self.assertEqual(r["fert_edits"], 1)
                self.assertEqual(set(r["changed"]),
                                 {"addondata/config/game/assets.xml",
                                  FERT_FILE})
                from annoedit.fertility import parse_fertility_rates
                txt = read_rda(out)[FERT_FILE][0].decode("cp1252")
                self.assertEqual(parse_fertility_rates(txt)["low"]["Dates"],
                                 (40, 60))
                # clear helpers
                ses.clear_extra("Mill", "ProductionTime")
                ses.clear_fertility("low", "Dates")
                self.assertFalse(ses.extras)
                self.assertFalse(ses.fert)
            finally:
                ses.close()

    def test_cli_fertility(self):
        from annoedit.fertility import FERT_FILE, parse_fertility_rates
        from annoedit.rda import read_rda
        with tempfile.TemporaryDirectory() as td:
            spec = os.path.join(td, "spec.json")
            out = os.path.join(td, "o.rda")
            with open(spec, "w") as f:
                json.dump({"fertility": [
                    {"tier": "low", "crop": "Dates", "north": 40},
                    {"tier": "high", "crop": "Spices", "north": 30,
                     "south": 80}]}, f)
            r = subprocess.run(
                [sys.executable, "-m", "annoedit.cli",
                 "fertility-apply", TEST_RDA, out, spec],
                cwd=REPO, capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            self.assertIn(f"changed: {FERT_FILE}", r.stdout)
            txt = read_rda(out)[FERT_FILE][0].decode("cp1252")
            rates = parse_fertility_rates(txt)
            self.assertEqual(rates["low"]["Dates"], (40, 60))
            self.assertEqual(rates["high"]["Spices"], (30, 80))

    def test_cli_fertility_list(self):
        r = subprocess.run(
            [sys.executable, "-m", "annoedit.cli",
             "fertility", TEST_RDA, "low"],
            cwd=REPO, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertIn("== low (16 crops) ==", r.stdout)
        self.assertIn("Dates", r.stdout)

    def test_cli_extras(self):
        from annoedit.extras import ASSETS_FILE
        with tempfile.TemporaryDirectory() as td:
            spec = os.path.join(td, "spec.json")
            out = os.path.join(td, "o.rda")
            with open(spec, "w") as f:
                json.dump({"extras": [
                    {"asset": "Mill", "tag": "ProductionTime",
                     "value": 7500, "occ": None}]}, f)
            r = subprocess.run(
                [sys.executable, "-m", "annoedit.cli",
                 "extras-apply", TEST_RDA, out, spec],
                cwd=REPO, capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            self.assertIn(f"changed: {ASSETS_FILE}", r.stdout)
        r = subprocess.run(
            [sys.executable, "-m", "annoedit.cli",
             "extras", TEST_RDA, "noria"],
            cwd=REPO, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertIn("== noria ==", r.stdout)

    def test_vanilla_rewrite_touches_neither(self):
        from annoedit.core import ModProject
        from annoedit.extras import ASSETS_FILE
        from annoedit.fertility import FERT_FILE
        from annoedit.rda import read_rda
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "v.rda")
            rep = ModProject(TEST_RDA).build(out)
            self.assertEqual(rep["changed"], [])
            self.assertEqual(read_rda(out)[ASSETS_FILE],
                             read_rda(TEST_RDA)[ASSETS_FILE])
            self.assertEqual(read_rda(out)[FERT_FILE],
                             read_rda(TEST_RDA)[FERT_FILE])


if __name__ == "__main__":
    unittest.main()
