"""One locator for reader, writer and oracle.

- Relations reading/writing is comment-blind (a commented <War> block
  before or after the real one never matters).
- Structural relations errors raise instead of reading as {}.
- Fertility parse and edit share one comment-masked locator and agree on
  duplicates.
- Duplicate profile identity (two assets, same Name+GUID) is refused.
- The oracle ignores commented-out kind blocks.
- extras.occurrences' fallback scan is comment-masked.
"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)
from synthetic_rda import make_synthetic_rda


def _inject(pr, guid, payload, before=True, anchor="</Relations>"):
    """Insert payload into guid's asset text and resync offsets."""
    p = pr.by_guid[guid]
    fk = p.filekey
    t = pr.filetexts[fk]
    v = pr.text_of_fresh(p)
    i = t.index(v) + v.index(anchor)
    if not before:
        i += len(anchor)
    pr.filetexts[fk] = t[:i] + payload + t[i:]
    pr._resync_offsets(fk)
    return pr


_COMMENT_WAR = ("<!-- <War><Profiles><Item>"
                "<ProfileGUID>9999999</ProfileGUID>"
                "</Item></Profiles></War> -->")


class RelationsCommentBlindTests(unittest.TestCase):
    """reader and writer must both skip commented-out kind blocks."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.path = make_synthetic_rda(os.path.join(self.tmp, "a.rda"))

    def _proj(self):
        from annoedit.core import ModProject
        return ModProject(self.path)

    def test_comment_after_real_block_ignored_by_reader(self):
        # the reader used to return the commented GUIDs.
        pr = _inject(self._proj(), "1645020", _COMMENT_WAR, before=False)
        rel = pr.relations(pr.by_guid["1645020"])
        self.assertNotIn("9999999", str(rel),
                         "commented GUIDs must never be read")
        self.assertNotEqual(rel.get("War"), ["9999999"])

    def test_comment_before_real_block_editable(self):
        # every relations edit for the character used to be
        # refused by a fooled oracle.
        from annoedit.model import EditError
        # inject right after the <Relations> opening tag
        pr = self._proj()
        p = pr.by_guid["1645020"]
        fk = p.filekey
        t = pr.filetexts[fk]
        v = pr.text_of_fresh(p)
        i = t.index(v) + v.index("<Relations>") + len("<Relations>")
        pr.filetexts[fk] = t[:i] + _COMMENT_WAR + t[i:]
        pr._resync_offsets(fk)
        p = pr.by_guid["1645020"]
        try:
            pr.set_relations(p, war=["1645006", "1645021"])
        except EditError as e:
            self.fail(f"set_relations refused on a commented block: {e}")
        rel = pr.relations(p)
        self.assertEqual(rel.get("War"), ["1645006", "1645021"])

    def test_duplicate_real_kind_blocks_refused(self):
        from annoedit.model import EditError
        pr = self._proj()
        p = pr.by_guid["1645020"]
        fk = p.filekey
        t = pr.filetexts[fk]
        v = pr.text_of_fresh(p)
        wm = re.search(r"([ \t]*)<War>.*?</War>", v, re.S)
        dup = v[wm.start():wm.end()]
        i = t.index(v) + v.index("</Relations>")
        pr.filetexts[fk] = t[:i] + dup + t[i:]
        pr._resync_offsets(fk)
        with self.assertRaises(EditError):
            pr.relations(p)
        with self.assertRaises(EditError):
            pr.set_relations(p, war=["1645006"])

    def test_reader_writer_round_trip(self):
        pr = self._proj()
        p = pr.by_guid["1645020"]
        pr.set_relations(p, war=["1645006"], ally=["1645026"],
                         trade=[], avoidwar=["1645027"])
        rel = pr.relations(p)
        self.assertEqual(rel.get("War"), ["1645006"])
        self.assertEqual(rel.get("Ally"), ["1645026"])
        self.assertEqual(rel.get("Trade"), [])
        self.assertEqual(rel.get("AvoidWar"), ["1645027"])


class RelationsStructuralErrorTests(unittest.TestCase):
    """structural errors must raise, never silently read as {}."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.path = make_synthetic_rda(os.path.join(self.tmp, "a.rda"))

    def test_two_relationships_blocks_raise(self):
        from annoedit.core import ModProject
        from annoedit.model import EditError
        pr = ModProject(self.path)
        p = pr.by_guid["1645024"]
        fk = p.filekey
        t = pr.filetexts[fk]
        v = pr.text_of_fresh(p)
        i = t.index(v) + v.index("</Values>")
        pr.filetexts[fk] = (t[:i] +
                             "<Relationships><Relations/></Relationships>"
                             + t[i:])
        pr._resync_offsets(fk)
        with self.assertRaises(EditError):
            pr.relations(p)

    def test_vanilla_mode_rolls_back_on_broken_reference(self):
        from annoedit.session import Session
        from annoedit.session import SessionError
        import shutil
        from annoedit.core import ModProject
        # Break the VANILLA copy's character (two Relationships blocks).
        van = os.path.join(self.tmp, "van.rda")
        shutil.copy(self.path, van)
        pr = ModProject(van)
        p = pr.by_guid["1645024"]
        fk = p.filekey
        t = pr.filetexts[fk]
        v = pr.text_of_fresh(p)
        i = t.index(v) + v.index("</Values>")
        pr.filetexts[fk] = (t[:i] +
                             "<Relationships><Relations/></Relationships>"
                             + t[i:])
        pr._resync_offsets(fk)
        broken = os.path.join(self.tmp, "broken.rda")
        pr.build(broken)
        s = Session(backup_root=os.path.join(self.tmp, "b"),
                    exports_root=os.path.join(self.tmp, "e"))
        s.provide_vanilla(broken)
        s.open(self.path)
        s.set_dial(s.proj.by_name["Leif Jorgensen"],
                   "Military/MaxUnitCount", "42")
        with self.assertRaises(SessionError):
            s.set_mode(s.proj.by_guid["1645024"], "vanilla")
        # The pending edit survived the rollback.
        self.assertEqual(
            s.cs.dials.get(("1645021", "Military/MaxUnitCount")).value, "42")

    def test_drift_unavailable_on_broken_live_relations(self):
        from annoedit.core import ModProject
        from annoedit.session import Session
        from annoedit import ops
        import shutil
        os.makedirs(os.path.join(self.tmp, "live"))
        live = os.path.join(self.tmp, "live", "data1.rda")
        shutil.copy(self.path, live)
        pr = ModProject(live)
        p = pr.by_guid["1645024"]
        fk = p.filekey
        t = pr.filetexts[fk]
        v = pr.text_of_fresh(p)
        i = t.index(v) + v.index("</Values>")
        pr.filetexts[fk] = (t[:i] +
                             "<Relationships><Relations/></Relationships>"
                             + t[i:])
        pr._resync_offsets(fk)
        pr.build(live)
        s = Session(backup_root=os.path.join(self.tmp, "b"),
                    exports_root=os.path.join(self.tmp, "e"))
        s.set_live_path(live)
        s.open(self.path)
        with self.assertRaises(ops.DriftUnavailable):
            ops.drift_check(*s.freeze_drift_inputs())


class FertilityLocatorTests(unittest.TestCase):
    """one locator for fertility parse and edit."""

    def _text(self, cider=60):
        def tier(name):
            return (f"<k><ResourceAmount>{name}</ResourceAmount></k><v>"
                    "<k><Fertility>Cider</Fertility></k>"
                    f"<v><North>{cider}</North><South>0</South></v>"
                    "<k><Fertility>Almond</Fertility></k>"
                    "<v><North>90</North><South>0</South></v></v>")
        return ("head<![binary]>\r\n<Config><FertilityRates>"
                + tier("low") + tier("medium") + tier("high")
                + "</FertilityRates></Config>\r\n")

    def test_duplicate_tier_refused(self):
        from annoedit.fertility import FertilityError, parse_fertility_rates
        base = self._text()
        dup = re.search(r"<k><ResourceAmount>low</ResourceAmount></k><v>.*?</v>",
                        base, re.S).group(0)
        text = base.replace("<FertilityRates>",
                            "<FertilityRates>" + dup, 1)
        with self.assertRaises(FertilityError):
            parse_fertility_rates(text)

    def test_duplicate_block_refused(self):
        from annoedit.fertility import FertilityError, parse_fertility_rates
        block = re.search(r"<FertilityRates>.*?</FertilityRates>",
                           self._text(), re.S).group(0)
        text = self._text() + block
        with self.assertRaises(FertilityError):
            parse_fertility_rates(text)

    def test_commented_crop_entry_ignored(self):
        from annoedit.fertility import (FertilityError, parse_fertility_rates,
                                        set_fertility)
        text = self._text().replace(
            "<k><Fertility>Almond</Fertility></k>",
            "<!-- <k><Fertility>Almond</Fertility></k>"
            "<v><North>1</North><South>2</South></v> -->"
            "<k><Fertility>Almond</Fertility></k>", 1)
        rates = parse_fertility_rates(text)
        self.assertEqual(rates["low"]["Almond"], (90, 0),
                         "the real entry must win, not the comment")
        # A crop that exists only as a comment must not be editable.
        text2 = self._text().replace(
            "<k><Fertility>Almond</Fertility></k>"
            "<v><North>90</North><South>0</South></v>",
            "<!-- <k><Fertility>Almond</Fertility></k>"
            "<v><North>90</North><South>0</South></v> -->", 1)
        with self.assertRaises(FertilityError):
            set_fertility(text2, "low", "Almond", north=5)

    def test_edit_hits_the_only_copy_and_round_trips(self):
        from annoedit.fertility import parse_fertility_rates, set_fertility
        text = self._text()
        new_text, old = set_fertility(text, "low", "Cider", north=33)
        self.assertEqual(old, {"north": "60"})
        self.assertEqual(parse_fertility_rates(new_text)["low"]["Cider"],
                         (33, 0))
        # re-apply is byte-identical
        new2, _ = set_fertility(text, "low", "Cider", north=33)
        self.assertEqual(new_text, new2)


class DuplicateProfileIdentityTests(unittest.TestCase):
    """two assets with the same identity must be refused, not guessed."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.path = make_synthetic_rda(os.path.join(self.tmp, "a.rda"))

    def test_duplicate_guid_refused_at_parse(self):
        from annoedit.core import ModProject
        from annoedit.model import EditError, parse_profiles
        pr = ModProject(self.path)
        p = pr.by_guid["1645021"]
        fk = p.filekey
        t = pr.filetexts[fk]
        # a full second <Asset> copy with the same identity
        am = None
        for m in re.finditer(r"<Asset>.*?</Asset>", t, re.S):
            if f"<GUID>{p.guid}</GUID>" in m.group(0):
                am = m
                break
        pr.filetexts[fk] = t[:am.end()] + am.group(0) + t[am.end():]
        with self.assertRaises(EditError):
            parse_profiles(fk, pr.filetexts[fk])
        # A FULL re-parse of the modified archive refuses too (build it
        # to disk so ModProject re-reads the duplicated file).
        out = os.path.join(self.tmp, "dup.rda")
        pr.build(out)
        with self.assertRaises(EditError):
            ModProject(out)

    def test_locate_values_exactly_one(self):
        from annoedit.model import EditError, _locate_values
        from annoedit.core import ModProject
        pr = ModProject(self.path)
        p = pr.by_guid["1645021"]
        fk = p.filekey
        t = pr.filetexts[fk]
        am = None
        for m in re.finditer(r"<Asset>.*?</Asset>", t, re.S):
            if f"<GUID>{p.guid}</GUID>" in m.group(0):
                am = m
                break
        dup_text = t[:am.end()] + am.group(0) + t[am.end():]
        with self.assertRaises(EditError):
            _locate_values(dup_text, p)


class OracleIndependentTests(unittest.TestCase):
    """the oracle must catch damage the shared locator cannot see."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.path = make_synthetic_rda(os.path.join(self.tmp, "a.rda"))

    def test_dial_edit_damaging_relations_refused(self):
        from annoedit.core import ModProject, _oracle_check
        from annoedit.model import EditError
        pr = ModProject(self.path)
        p = pr.by_guid["1645021"]
        v = pr.text_of_fresh(p)
        edits = {"Military/MaxUnitCount": "42"}
        # new: the dial changed AND a relations GUID changed under it
        new = v.replace(
            "<MaxUnitCount>41</MaxUnitCount>",
            "<MaxUnitCount>42</MaxUnitCount>", 1)
        new = re.sub(r"(<ProfileGUID>)\d+(</ProfileGUID>)",
                     r"\g<1>1234567\g<2>", new, count=1)
        self.assertNotEqual(v, new)
        with self.assertRaises(EditError):
            _oracle_check(v, new, p, edits, None)

    def test_relations_edit_damaging_dial_refused(self):
        from annoedit.core import ModProject, _oracle_check
        from annoedit.model import EditError
        pr = ModProject(self.path)
        p = pr.by_guid["1645020"]
        v = pr.text_of_fresh(p)
        war = re.search(r"<War>.*?</War>", v, re.S)
        new = (v[:war.start()] +
               war.group(0).replace("<ProfileGUID>", "<ProfileGUID>1", 1) +
               v[war.end():])
        new = new.replace("<MaxUnitCount>", "<MaxUnitCount>", 1)
        m = re.search(r"(<MaxUnitCount>)(\d+)(</MaxUnitCount>)", new)
        if m:
            new = new[:m.start(2)] + "99" + new[m.end(2):]
        with self.assertRaises(EditError):
            _oracle_check(v, new, p, {"War": ["1645006", "1"]}, None,
                          relations_after_fn=True)


class OccurrencesFallbackMaskedTests(unittest.TestCase):
    """the SpanError fallback regex must be comment-masked."""

    def test_fallback_skips_commented_tag(self):
        from annoedit import extras
        blk = ("<Root><WareProduction>"
               "<!-- <ProductionTime>11</ProductionTime> -->"
               "<ProductionTime>1000</ProductionTime></Peace>")
        occ = extras.occurrences(blk, "ProductionTime")
        vals = [o.group(1) for o in occ]
        self.assertEqual(vals, ["1000"],
                         "commented values must not appear in the fallback")


if __name__ == "__main__":
    unittest.main()
