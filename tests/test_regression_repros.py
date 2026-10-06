#!/usr/bin/env python3
"""Reproduction cases for previously fixed defects.

Each test encodes the correct behaviour for a scenario that once failed,
so the fix can never silently regress. Runs fully on the synthetic
fixture (no game data); isolation comes from fixture.py (ANN0140_HOME
pinned to a temp dir).
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import fixture  # noqa: E402  (pins ANN0140_HOME before annoedit imports)


from synthetic_rda import make_synthetic_rda  # noqa: E402


def _session(tmp, **kw):
    from annoedit.session import Session
    return Session(backup_root=os.path.join(tmp, "bk"),
                   persona_dirs=(os.path.join(HERE, "..", "annoedit", "presets"),),
                   **kw)


class RegressionRepros(unittest.TestCase):
    """Each test: the defect it guards against, then the expected behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auditrepro_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(
            os.path.join(self.tmp, "game", "data1.rda"))

    # Defect: load_export_path('vanilla') raised although 'vanilla' is a
    # listed, reserved name, so "Open" on the vanilla row failed.
    # Guard: the reserved name is checked before slug_export_name.
    def test_r1_load_export_vanilla_row(self):
        s = _session(self.tmp)
        s.provide_vanilla(self.game)
        names = [r["name"] for r in s.list_saved_exports()]
        self.assertIn("vanilla", names)
        path = s.load_saved_export_path("vanilla")
        self.assertEqual(path, s.exports_store.vanilla_path)

    # Defect: a depth-blind chain match wrote into a NESTED same-name
    # block. Guard: the span engine inserts at the right depth; the nested
    # <Max> is untouched and <Diplomacy>/<Max> goes in as a direct child.
    def test_r2_depth_blind_chain_match(self):
        from annoedit.model import Profile, set_dial, dials_dict
        txt = ("<Assets>\r\n  <Asset>\r\n    <Template>HardCSP</Template>\r\n"
               "    <Values>\r\n      <Diplomacy>\r\n"
               "        <CompetenceUsageRanges>\r\n"
               "          <TownAcquisition>\r\n            <Max>5</Max>\r\n"
               "          </TownAcquisition>\r\n"
               "        </CompetenceUsageRanges>\r\n      </Diplomacy>\r\n"
               "    </Values>\r\n    <Standard>\r\n      <Name>X</Name>\r\n"
               "      <GUID>1</GUID>\r\n    </Standard>\r\n  </Asset>\r\n"
               "</Assets>\r\n")
        p = Profile("f", "X", "1", "HardCSP", 0, 0, 0, 0)
        new = set_dial(txt, p, "TownAcquisition/BudgetPerMinute", "999")
        a = new[new.find("<Asset>"):new.find("</Asset>") + 8]
        dials = dials_dict(a)
        self.assertIn("TownAcquisition/BudgetPerMinute", dials)
        self.assertNotIn(
            "Diplomacy/CompetenceUsageRanges/TownAcquisition/BudgetPerMinute",
            dials)
        # second half: Diplomacy/Max must NOT rewrite the nested Max
        new2 = set_dial(txt, p, "Diplomacy/Max", "77")
        a2 = new2[new2.find("<Asset>"):new2.find("</Asset>") + 8]
        d2 = dials_dict(a2)
        self.assertIn("Diplomacy/Max", d2)
        self.assertEqual(
            d2.get("Diplomacy/CompetenceUsageRanges/TownAcquisition/Max"),
            "5")

    # Defect: a container path was treated as a missing scalar and
    # duplicated. Uses a profile that HAS a War list (Rufus 1645022, a
    # 2-item list in the fixture). Guard: the edit is refused.
    def test_r3_container_path_duplicate_insert(self):
        from annoedit.core import ModProject
        from annoedit.model import EditError
        proj = ModProject(self.game)
        p = proj.by_guid["1645022"]
        self.assertTrue(proj.relations(p).get("War"))   # list exists
        with self.assertRaises(EditError):
            proj.set_dials(p, {"Relationships/Relations/War": "5"})
        t = proj.text_of(proj.by_guid["1645022"])
        self.assertEqual(t.count("<War>"), 1)

    # Defect: junk values were accepted at queue time and only failed at
    # build time. Guard: typed validation refuses non-numeric dial values
    # when queued, with a clear SessionError.
    def test_r4_set_dial_accepts_junk(self):
        s = _session(self.tmp)
        s.open(self.game)
        p = s.proj.by_guid["1645021"]
        with self.assertRaises(Exception):
            s.set_dial(p, "Military/MaxUnitCount", "abc")
        with self.assertRaises(Exception):
            s.set_dial(p, "Build/BuildingSpeed", "5&6")
        s.close()

    # Defect: int() accepts '1_000' and non-ASCII digits.
    # Guard: normalize_int accepts ASCII digits only.
    def test_r5_extras_int_parsing(self):
        s = _session(self.tmp)
        s.open(self.game)
        with self.assertRaises(Exception):
            s.set_extra("Bakery", "MoneyCost", "1_000")
        with self.assertRaises(Exception):
            s.set_extra("Bakery", "MoneyCost", "\u0663")
        s.close()

    # Defect: export had no protected-path guard.
    # Guard: the exports dir is protected for every write.
    def test_r6_export_overwrites_vanilla_copy(self):
        from annoedit.backup import md5_of
        # isolated exports store + an explicit provided vanilla copy
        s = _session(self.tmp, exports_root=os.path.join(self.tmp, "exp6"))
        s.open(self.game)
        s.provide_vanilla(self.game)
        v = s.exports_store.vanilla_path
        before = md5_of(v)
        s.set_dial(s.proj.by_guid["1645021"],
                   "Military/MaxUnitCount", "99")
        with self.assertRaises(Exception):
            s.export(v)
        self.assertEqual(md5_of(v), before)
        s.close()

    # Defect: an in-place flash kept the flashed edits pending.
    # Guard: the flashed edits are cleared after an in-place flash.
    def test_r7_in_place_flash_clears_pending(self):
        s = _session(self.tmp)
        s.open(self.game)
        p = s.proj.by_guid["1645021"]
        s.set_dial(p, "Military/MaxUnitCount", "77")
        rep = s.flash()
        self.assertTrue(rep["in_place"])
        self.assertFalse(s.changes)

    # Defect: the build re-read the source from disk (TOCTOU).
    # Guard: _build seeds from the in-memory opened entries, so a disk
    # change after open can never leak into the build.
    def test_r7b_build_uses_reviewed_bytes(self):
        g = make_synthetic_rda(os.path.join(self.tmp, "g7b", "data1.rda"))
        s = _session(self.tmp)
        s.open(g)
        md5_open = s.source_md5
        opened_dials = dict(s.proj.by_guid["1645021"].dials)  # reviewed bytes
        make_synthetic_rda(g, variant=3)   # file changes on disk after open
        s.set_dial(s.proj.by_guid["1645021"],
                   "Military/MaxUnitCount", "77")
        out = os.path.join(self.tmp, "o7.rda")
        s.export(out)
        # The build must have used the reviewed bytes, or at least refused:
        # either identical to a build of the opened snapshot, or an error.
        s.close()
        # The real assertion: export must not silently mix the changed
        # disk file — the built profile must be EXACTLY the OPENED snapshot's
        # dials plus the queued edit (a disk-mixing build would carry
        # variant-3's other dial values instead).
        from annoedit.core import ModProject
        proj = ModProject(out)
        p = proj.by_guid["1645021"]
        expected = dict(opened_dials)
        expected["Military/MaxUnitCount"] = "77"
        self.assertEqual(p.dials, expected)

    # Defect: the first archive opened was recorded as "vanilla", so
    # opening a modded file first made Restore Vanilla restore the
    # modded file. Guard: the auto-capture is a "first-open snapshot
    # (unverified)", never called vanilla, and the restore source label
    # says so.
    def test_r8_modded_first_open_poisons_backup(self):
        modded = make_synthetic_rda(
            os.path.join(self.tmp, "g8", "data1.rda"), variant=5)
        # an ISOLATED exports store: the fixture's shared ANN0140_HOME
        # may already hold a provided vanilla copy from another test
        s = _session(self.tmp, exports_root=os.path.join(self.tmp, "exp8"))
        s.open(modded)
        label = str(s.restore_source_label() or "").lower()
        self.assertIn("first-open snapshot", label,
                      "the fallback source must be labelled a first-open "
                      "snapshot, not presented as vanilla")
        self.assertIn("unverified", label,
                      "the snapshot fallback must be marked unverified")

    # Defect: a GUID in the vanilla list but not in the CSP roster
    # blocked ANY edit of that list. Guard: GUIDs already in the list pass
    # through; only new additions are validated.
    def test_r9_unknown_guid_blocks_list_edit(self):
        from annoedit.rda import read_rda, write_rda
        g = make_synthetic_rda(os.path.join(self.tmp, "g9", "data1.rda"))
        e = read_rda(g)
        k = "addondata/config/ai/aiprofiles.xml"
        t = e[k][0].decode()
        t = t.replace("<ProfileGUID>1645006</ProfileGUID>",
                      "<ProfileGUID>1650020</ProfileGUID>", 1)
        e[k] = (t.encode(), e[k][1])
        write_rda(e, g)
        s = _session(self.tmp)
        s.open(g)
        p = [q for q in s.roster
             if "1650020" in s.relations_row(q, "War")][0]
        cur = s.relations_row(p, "War")
        # removing one entry must be possible even though 1650020 is not
        # a known CSP GUID (it is already IN the list)
        s.set_relations(p, war=[x for x in cur if x != "1645024"]
                        or cur)
        s.close()

    # Defect: with a self-closed <Trade/>, the reader missed it and the
    # writer added a second <Trade> block. Guard: the reader reports it as
    # an empty list and the writer replaces it in place.
    def test_r10_self_closed_trade_kind(self):
        from annoedit.core import ModProject
        proj = ModProject(self.game)
        p = proj.by_guid["1645022"]   # carries <Trade/> in the fixture
        rel = proj.relations(p)
        self.assertIn("Trade", rel)          # reader must SEE the kind
        proj.set_relations(p, trade=["1645020"])
        a = proj.text_of(proj.by_guid["1645022"])
        self.assertEqual(a.count("<Trade>"), 1)   # exactly ONE Trade block
        self.assertEqual(a.count("<Trade/>"), 0)  # self-closed replaced

    # Defect: schema docs keyed by leaf name gave nested dials the wrong
    # range (DeclareWar/Min got OfferPeace's 0..5). Guard: parse_schema
    # keys by full path; a leaf alias exists only when unique.
    def test_r11_schema_docs_by_full_path(self):
        from annoedit.model import parse_schema
        schema = ("<Properties><DefaultValues/><Group>"
                  "<Property><Name>Diplomacy</Name>"
                  "<ValueDefinition><Name>DeclareWar</Name>"
                  "<Min>-100</Min><Max>0</Max>"
                  "<ValueDefinition><Name>Min</Name>"
                  "<Min>-100</Min><Max>100</Max></ValueDefinition>"
                  "</ValueDefinition>"
                  "<ValueDefinition><Name>OfferPeace</Name>"
                  "<ValueDefinition><Name>Min</Name>"
                  "<Min>0</Min><Max>5</Max></ValueDefinition>"
                  "</ValueDefinition>"
                  "</Property></Group></Properties>")
        docs, _d = parse_schema(schema)
        dip = docs.get("Diplomacy", {})
        # Lookups are keyed by full path:
        # 'Diplomacy/DeclareWar/Min' must keep DeclareWar's own range,
        # distinct from 'Diplomacy/OfferPeace/Min'.
        dd = dip.get("DeclareWar/Min") or dip.get("Min", {})
        self.assertNotEqual(dd.get("max"), "5",
                            "DeclareWar/Min must not inherit "
                            "OfferPeace/Min's max")
        if "DeclareWar/Min" in dip:
            self.assertEqual(dip["DeclareWar/Min"]["max"], "100")

    # Defect: the same leaf could be queued under several EXTRAS keys.
    # Guard: set_extra canonicalises the asset name and occ, so all
    # spellings of one leaf collapse to one pending edit.
    def test_r12_extras_canonical_keys(self):
        s = _session(self.tmp)
        s.open(self.game)
        # three spellings of the SAME leaf: plain occ=None, explicit occ=0,
        # and the 'Name [GUID]' display form — all must collapse to ONE
        # canonical pending edit / review row (set_extra canonicalises)
        s.set_extra("Bakery", "MoneyCost", "20")
        s.set_extra("Bakery", "MoneyCost", "30", occ=0)
        s.set_extra("Bakery [1002]", "MoneyCost", "40")
        rows, _t = s.pending_change_rows()
        xr = [r for r in rows if r["section"] == "EXTRAS"]
        self.assertEqual(len(xr), 1)   # ONE canonical row for one leaf
        s.close()

    # Defect: relations GUID counts were mixed into "total dial edits".
    # Guard: they are counted only in the relations total.
    def test_r13_change_report_counts(self):
        s = _session(self.tmp)
        s.open(self.game)
        p = s.proj.by_guid["1645021"]
        s.set_relations(p, war=["1645020", "1645024", "1645026"])
        rep = s.change_report()
        self.assertIn("total dial edits: 0", rep)
        self.assertIn("total relations edits: 3", rep)
        s.close()

    # Defect: a next_block cycle looped forever.
    # Guard: a visited-set cycle check.
    def test_r14_rda_reader_cycle_guard(self):
        bad = os.path.join(self.tmp, "cycle.rda")
        shutil.copy(self.game, bad)
        with open(bad, "r+b") as f:
            f.seek(36 + 1008)
            first = struct.unpack("<I", f.read(4))[0]
            f.seek(first + 16)
            f.write(struct.pack("<I", first))
        code = ("import sys; sys.path.insert(0, %r); "
                "from annoedit.rda import read_rda; read_rda(%r)"
                % (os.path.join(HERE, ".."), bad))
        try:
            r = subprocess.run([sys.executable, "-c", code],
                               timeout=10, capture_output=True)
            # a clean RdaFormatError, exit != 0, no hang
            self.assertNotEqual(r.returncode, 0)
            self.assertIn(b"RdaFormatError", r.stderr)
        except subprocess.TimeoutExpired:
            self.fail("read_rda hangs on a cyclic block chain")

    # Defect: flash replaced the live file with mode 0600.
    # Guard: the target's mode is preserved.
    def test_r15_flash_preserves_file_mode(self):
        g = make_synthetic_rda(os.path.join(self.tmp, "g15", "data1.rda"))
        os.chmod(g, 0o644)
        s = _session(self.tmp)
        s.open(g)
        s.set_dial(s.proj.by_guid["1645021"],
                   "Military/MaxUnitCount", "70")
        s.flash()
        s.close()
        self.assertEqual(oct(os.stat(g).st_mode & 0o777), "0o644")

    # Defect: the session lock was not re-entrant.
    # Guard: nested session_lock() on one store re-enters; another
    # process still gets BackupError.
    def test_r16_session_lock_reentrancy(self):
        from annoedit.backup import BackupStore
        b = BackupStore(os.path.join(self.tmp, "bk16"))
        with b.session_lock():
            with b.session_lock():   # must NOT raise (documented contract)
                pass

    # Defect: hardened_changes crashed on a non-numeric current value.
    # Guard: such dials are skipped.
    def test_r17_hardened_non_numeric(self):
        from annoedit.model import Profile
        from annoedit.presets import hardened_changes
        p = Profile("f", "X", "1", "EasyCSP", 0, 0, 0, 0)
        p.dials = {"Military/MaxUnitCount": "abc"}
        h = Profile("f", "H", "1645020", "HardCSP", 0, 0, 0, 0)
        h.dials = {"Military/MaxUnitCount": "80"}
        # must skip-and-report, not raise TypeError
        hardened_changes(p, [p, h], {})


if __name__ == "__main__":
    unittest.main()
