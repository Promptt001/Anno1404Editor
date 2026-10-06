#!/usr/bin/env python3
"""Edit-engine guards (real archive; skipped without ANN0140_TEST_RDA).

- set_relations/relations re-locate the profile by identity (Name+GUID),
  never by stored offsets that go stale after an earlier asset grows.
- Dial values containing <, > or & are refused with a clear EditError.
- Also: hardened idempotence, no duplicate inserts, self-closed tag
  expansion, refusal of ambiguous paths.
"""
import os
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
from fixture import TEST_RDA as SRC, real_rda
from annoedit.core import ModProject
from annoedit.model import EditError, apply_changes, set_dial


@real_rda
class EngineGuardTests(unittest.TestCase):
    """Stale-offset and bad-value regression guards + standing guards."""


    def test_relations_stale_offsets(self):
        """Grow the FIRST asset, then set_relations on a STALE later-profile
        object: the edit must land in the RIGHT character, and every OTHER
        character's Relations must stay identical to vanilla."""
        proj = ModProject(SRC)
        fk = "aiprofiles.xml"
        stale = {q.guid: q for q in proj.profiles[fk]}
        vanilla_rel = {q.guid: proj.relations(q) for q in proj.profiles[fk]}
        A = stale["1645024"]                       # Lucius, FIRST asset
        proj.set_dials(A, {f"Build/ZZZprobe{i:03d}": "1" for i in range(2000)})
        shift = proj.by_guid["1645026"].values_start - stale["1645026"].values_start
        assert shift > 1000, f"test setup: no shift induced ({shift})"
        G = stale["1645026"]                       # Giovanni, STALE offsets
        proj.set_relations(G, war=["1645020"])
        assert proj.verify_xml() == [], "XML must still parse"
        rel = {q.guid: proj.relations(q) for q in proj.profiles[fk]}
        assert rel["1645026"].get("War") == ["1645020"], \
            f"Giovanni's War not set: {rel['1645026'].get('War')}"
        assert rel["1645020"] == vanilla_rel["1645020"], \
            f"BARONESS corrupted (the v2 bug): {rel['1645020']}"
        assert rel["1645024"] == vanilla_rel["1645024"], "Lucius corrupted"

    def test_relations_reader_after_shift(self):
        """relations() on a stale object must also read the right character."""
        proj = ModProject(SRC)
        fk = "aiprofiles.xml"
        stale = {q.guid: q for q in proj.profiles[fk]}
        proj.set_dials(stale["1645024"],
                       {f"Build/ZZZq{i:03d}": "1" for i in range(2000)})
        got = proj.relations(stale["1645026"])     # Giovanni via STALE object
        want = proj.relations(proj.by_guid["1645026"])  # via FRESH object
        assert got == want, f"reader diverged: {got} != {want}"


    def test_value_special_chars_refused(self):
        text = ('<Asset><Values>\r\n  <ShipFight>\r\n    <X>1</X>\r\n  </ShipFight>\r\n'
                '  <Standard><Name>Probe</Name><GUID>9999001</GUID></Standard>\r\n'
                '</Values></Asset>')
        p = type("P", (), {})(); p.name, p.guid = "Probe", "9999001"
        for bad in ("50&10", "1<2", "3>1", "a&b<c"):
            with self.assertRaises(EditError, msg=f"value {bad!r} accepted"):
                set_dial(text, p, "ShipFight/X", bad)
        out = set_dial(text, p, "ShipFight/X", "42")
        assert "<X>42</X>" in out
        ET.fromstring(out)

    def test_apply_changes_special_chars_error(self):
        """apply_changes surfaces the refusal as an error entry, never writes."""
        text = ('<Asset><Values>\r\n  <ShipFight>\r\n    <X>1</X>\r\n  </ShipFight>\r\n'
                '  <Standard><Name>Probe</Name><GUID>9999001</GUID></Standard>\r\n'
                '</Values></Asset>')
        p = type("P", (), {})(); p.name, p.guid = "Probe", "9999001"
        new, applied, errors = apply_changes(text, p, {"ShipFight/X": "5&5"})
        assert errors and not applied and new == text

    # ------------------------------------------------------------ standing guards

    def test_hardened_idempotent(self):
        import hashlib
        from annoedit.presets import HARD_GUIDS, hardened_changes
        outs = []
        for i in (1, 2):
            proj = ModProject(SRC)
            allp = [q for ps in proj.profiles.values() for q in ps]
            for fk, ps in proj.profiles.items():
                for q in ps:
                    if q.guid in HARD_GUIDS:
                        continue
                    ch = hardened_changes(q, allp, proj.defaults)
                    if ch:
                        proj.set_dials(q, ch)
            out = f"/tmp/ce_idem_{i}.rda"
            proj.build(out)
            outs.append(hashlib.md5(open(out, "rb").read()).hexdigest())
        assert outs[0] == outs[1], f"hardened not idempotent: {outs}"

    def test_insert_never_duplicates(self):
        text = ('<Asset><Values>\r\n  <ShipFight>\r\n    <ShipAmountPerLevel>\r\n'
                '      <Peasant>2</Peasant>\r\n    </ShipAmountPerLevel>\r\n  </ShipFight>\r\n'
                '  <Standard><Name>Probe</Name><GUID>9999001</GUID></Standard>\r\n'
                '</Values></Asset>')
        p = type("P", (), {})(); p.name, p.guid = "Probe", "9999001"
        new, applied, errors = apply_changes(
            text, p, {"ShipFight/ShipAmountPerLevel/Peasant": "8"})
        assert not errors and new.count("<Peasant>") == 1 and "<Peasant>8</Peasant>" in new
        ET.fromstring(new)

    def test_self_closed_single_conversion(self):
        text = ('<Asset><Values>\r\n  <Diplomacy/>\r\n'
                '  <Standard><Name>Probe</Name><GUID>9999001</GUID></Standard>\r\n'
                '</Values></Asset>')
        p = type("P", (), {})(); p.name, p.guid = "Probe", "9999001"
        new, _, errors = apply_changes(
            text, p, {"Diplomacy/DeclareWarMinPlayTime": "600000"})
        assert not errors
        assert new.count("<Diplomacy>") == 1 and "<Diplomacy/>" not in new
        ET.fromstring(new)

    def test_ambiguous_refused(self):
        text = ('<Asset><Values>\r\n  <TownAcquisition>\r\n    <A>1</A>\r\n  </TownAcquisition>\r\n'
                '  <TownAcquisition>\r\n    <B>2</B>\r\n  </TownAcquisition>\r\n'
                '  <Standard><Name>Probe</Name><GUID>9999001</GUID></Standard>\r\n'
                '</Values></Asset>')
        p = type("P", (), {})(); p.name, p.guid = "Probe", "9999001"
        _, _, errors = apply_changes(text, p, {"TownAcquisition/BudgetPerMinute": "1300"})
        assert errors, "ambiguous same-name blocks must be refused"


if __name__ == "__main__":
    unittest.main(verbosity=2)
