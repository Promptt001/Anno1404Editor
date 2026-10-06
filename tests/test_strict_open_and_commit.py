"""Strict open and commit-protocol tests.

- A corrupt archive cannot be opened (strict open), so a save can never
  silently drop unreadable members.
- An in-place save refuses when the file changed on disk since open.
- A same-key re-edit made during a build survives as pending.
- An in-place restore keeps edits queued or changed during the restore.
- _read_rda_stream validates against the passed size, not a fresh stat.
- Plus: replayed saves, unmodelled restore reports, effective relations
  exclusivity, comment-safe indents, exact extras clears, vanilla copy
  validation and unrevertable-surface reporting.
"""
import os
import struct
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from synthetic_rda import make_synthetic_rda                # noqa: E402
from annoedit.rda import (read_rda, write_rda,              # noqa: E402
                          _read_rda_stream, RdaFormatError)
from annoedit.appsettings import Settings                   # noqa: E402
from annoedit.session import Session, SessionError          # noqa: E402
from annoedit import ops                                     # noqa: E402

os.environ["ANN0140_STRICT_THREADS"] = "1"
os.environ.setdefault("ANN0140_HOME", tempfile.mkdtemp(prefix="p2120h"))
os.environ.setdefault("ANN0140_EXPORTS_DIR", tempfile.mkdtemp(prefix="p2120e"))


def _corrupt_first_txt_block(path):
    """The 's corruption: one .txt directory block's compressed
    bytes damaged so zlib decompress fails on read."""
    data = bytearray(open(path, "rb").read())
    off = struct.unpack_from("<I", data, 1044)[0]
    while off < len(data):
        flags, cnt, dsz, dec, nxt = struct.unpack_from("<5I", data, off)
        dirpos = off - dsz
        dirbuf = zlib.decompress(bytes(data[dirpos:off])) if flags & 1 \
            else bytes(data[dirpos:off])
        if dirbuf[:520].decode("utf-16-le").split("\x00")[0].endswith(".txt"):
            data[dirpos + 2:dirpos + 6] = b"\xff\xff\xff\xff"
            open(path, "wb").write(bytes(data))
            return
        off = nxt
    raise AssertionError("no .txt block found")


class P2120Base(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p2120")
        self.A = os.path.join(self.W, "a.rda")          # variant 0
        self.B = os.path.join(self.W, "b.rda")          # variant 1
        make_synthetic_rda(self.A, variant=0)
        make_synthetic_rda(self.B, variant=1)
        self.home = tempfile.mkdtemp(prefix="p2120home")
        os.environ["ANN0140_HOME"] = self.home

    def tearDown(self):
        import shutil
        shutil.rmtree(self.W, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def mk_session(self):
        return Session(backup_root=self.W + "/b",
                        exports_root=self.W + "/e",
                        settings=Settings(self.W + "/s"))


class StrictOpenTests(P2120Base):
    """Corrupt archive -> open REFUSES; no silent entry loss."""

    def test_corrupt_archive_open_refused(self):
        bad = os.path.join(self.W, "bad.rda")
        make_synthetic_rda(bad, variant=0)
        n_before = len(read_rda(bad, strict=True))
        self.assertGreater(n_before, 0)
        _corrupt_first_txt_block(bad)
        s = self.mk_session()
        try:
            with self.assertRaises(RdaFormatError):
                s.open(bad)
            self.assertIsNone(s.proj)   # session untouched
        finally:
            s.close()

    def test_modproject_disk_read_is_strict(self):
        from annoedit.core import ModProject
        bad = os.path.join(self.W, "bad2.rda")
        make_synthetic_rda(bad, variant=0)
        _corrupt_first_txt_block(bad)
        with self.assertRaises(RdaFormatError):
            ModProject(bad)


class ExpectedMd5Tests(P2120Base):
    """In-place save refuses when the file changed on disk."""

    def test_in_place_flash_refuses_changed_file(self):
        s = self.mk_session()
        try:
            s.open(self.A)
            # an external tool writes a new member into the archive AFTER
            # the open (Steam 'verify files', another mod manager)
            ents = read_rda(self.A)
            ents["addondata/othermod/patch.txt"] = (b"other mod", 0)
            write_rda(ents, self.A)
            p0 = s.proj.by_guid["1645021"]
            s.set_dial(p0, "Military/MaxUnitCount", "42")
            with self.assertRaises(SessionError) as cm:
                s.flash()
            self.assertIn("changed on disk", str(cm.exception))
            # the other mod's file is still there (we never replaced)
            self.assertIn("addondata/othermod/patch.txt", read_rda(self.A))
        finally:
            s.close()

    def test_non_in_place_flash_allows_live_changes(self):
        s = self.mk_session()
        try:
            live = os.path.join(self.W, "live.rda")
            make_synthetic_rda(live, variant=0)
            s.open(self.A)
            s.settings.set("live_path", live)
            ents = read_rda(live)
            ents["addondata/othermod/patch.txt"] = (b"other mod", 0)
            write_rda(ents, live)
            p0 = s.proj.by_guid["1645021"]
            s.set_dial(p0, "Military/MaxUnitCount", "42")
            s.flash(target=live)      # must succeed (rebase keeps it)
            self.assertIn("addondata/othermod/patch.txt", read_rda(live))
        finally:
            s.close()


class ValueEqClearTests(P2120Base):
    """Same-key re-edits during a build survive."""

    def test_reedit_during_build_survives(self):
        s = self.mk_session()
        try:
            s.open(self.A)
            prof = s.proj.by_name["Leif Jorgensen"]
            s.set_dial(prof, "Military/MaxUnitCount", "50")
            cs, target, in_place = s.prepare_flash()
            res = ops.flash_build(
                s._write_lock, s.store, s.proj.entries, s.source_path,
                s._build, cs, target, in_place)
            # the user re-edits the SAME dial while the build runs
            s.set_dial(prof, "Military/MaxUnitCount", "77")
            s.apply_flash_result(res)
            self.assertEqual(
                s.cs.dial_value(prof.guid, "Military/MaxUnitCount"), "77",
                "the re-edit made during the build must stay pending")
            # the NEXT save must write 77
            out = os.path.join(self.W, "out.rda")
            rep = s.export(out)
            self.assertEqual(rep["dial_edits"], 1)
            from annoedit.core import ModProject
            p2 = ModProject(out)
            self.assertEqual(
                p2.by_guid[prof.guid].dials.get("Military/MaxUnitCount"),
                "77")
        finally:
            s.close()

    def test_unchanged_during_build_is_cleared(self):
        s = self.mk_session()
        try:
            s.open(self.A)
            prof = s.proj.by_name["Leif Jorgensen"]
            s.set_dial(prof, "Military/MaxUnitCount", "50")
            s.flash()
            self.assertIsNone(
                s.cs.dial_value(prof.guid, "Military/MaxUnitCount"),
                "the flashed edit (unre-edited) must clear")
        finally:
            s.close()


class RestoreDuringEditsTests(P2120Base):
    """An in-place restore keeps edits queued/changed during it."""

    def test_in_place_restore_keeps_during_restore_edits(self):
        s = self.mk_session()
        try:
            s.provide_vanilla(self.A)
            s.open(self.B)
            p0 = s.proj.by_guid["1645021"]
            s.set_dial(p0, "Military/MaxUnitCount", "66")
            # simulate the GUI: freeze the snapshot on the UI thread, run
            # the pure restore, queue an edit DURING it, then commit
            cs_snap = s.cs.snapshot()
            res = ops.restore_build(
                s._write_lock, s.store, s.exports_store, s.source_path,
                False, s.source_path, cs=cs_snap)
            s.set_dial(p0, "Military/MaxUnitCount", "88")
            s.apply_restore_result(res)
            self.assertEqual(
                s.cs.dial_value(p0.guid, "Military/MaxUnitCount"), "88",
                "an edit queued DURING the restore must survive")
            self.assertEqual(s.source_md5, res.vmd5)
        finally:
            s.close()

    def test_in_place_restore_resets_preexisting_edits(self):
        s = self.mk_session()
        try:
            s.provide_vanilla(self.A)
            s.open(self.B)
            p0 = s.proj.by_guid["1645021"]
            s.set_dial(p0, "Military/MaxUnitCount", "66")
            vmd5 = s.restore_vanilla(s.source_path)
            self.assertTrue(vmd5)
            self.assertFalse(s.cs, "pre-existing edits are reset")
        finally:
            s.close()


class M7FsizeTests(P2120Base):
    """_read_rda_stream must use the passed fsize, not re-stat."""

    def test_fsize_is_not_restatted(self):
        import io as _io
        blob = open(self.A, "rb").read()
        # a WRONG fsize (smaller than the actual blob) must be USED,
        # not overridden by a fresh os.path.getsize
        with _io.BytesIO(blob) as f:
            with self.assertRaises(RdaFormatError):
                _read_rda_stream(f, fsize=4, path=self.A, strict=True)


if __name__ == "__main__":
    unittest.main()


# ============================================================

class ReplaySaveTests(P2120Base):
    """Save-to-live REPLAYS the
    ChangeSet onto the live members — everything in live the editor does
    not overwrite survives (the old design silently reverted other mods'
    edits inside the 4 tracked members, )."""

    def _mk_live_with_other_mod(self, comment=b"OTHER MOD WAS HERE"):
        from annoedit.core import ASSETS_FILE
        from annoedit.rda import read_rda, write_rda
        live = os.path.join(self.W, "live.rda")
        ents = read_rda(self.A)
        a = ents[ASSETS_FILE][0].decode("latin-1")
        a = a.replace("</Assets>", "<!-- " + comment.decode() + " -->"
                      + "</Assets>", 1)
        ents[ASSETS_FILE] = (a.encode("latin-1"), ents[ASSETS_FILE][1])
        write_rda(ents, live)
        return live

    def test_other_mods_assets_edit_survives_save_to_live(self):
        # Another mod's assets.xml change (unmodelled) survives a
        # save-to-live AND is not reported as a blocking conflict
        from annoedit.core import ASSETS_FILE, ModProject
        from annoedit.rda import read_rda
        live = self._mk_live_with_other_mod()
        s = self.mk_session()
        try:
            s.open(self.A)
            s.settings.set("live_path", live)
            s.set_dial(s.proj.by_guid["1645021"],
                       "Military/MaxUnitCount", "42")
            # drift is honest: the other mod's edit is UNMODELLED (kept,
            # reported) — not silent, not a blocking false conflict
            drift = s.target_drift(live)
            self.assertIsNotNone(drift)
            self.assertTrue(drift.unmodelled, "unmodelled member reported")
            self.assertIn(ASSETS_FILE, drift.unmodelled)
            self.assertEqual(drift[0], 0)      # no dial conflicts
            s.flash(target=live)
            self.assertIn(b"OTHER MOD WAS HERE", read_rda(live)[ASSETS_FILE][0])
            # our own edit landed on top
            lp = ModProject(live)
            self.assertEqual(lp.by_guid["1645021"].dials["Military/MaxUnitCount"],
                             "42")
        finally:
            s.close()

    def test_foreign_dial_in_live_survives_and_no_false_conflict(self):
        # a foreign dial value in live (another tool edited the SAME key
        # we are not touching) survives; drift is None (kept, not conflict)
        from annoedit.core import ModProject
        p = ModProject(self.A)
        p.set_dials(p.by_guid["1645021"],
                    {"Military/MaxUnitCount": "99"})
        live = os.path.join(self.W, "live9.rda")
        p.build(live)
        s = self.mk_session()
        try:
            s.open(self.A)
            self.assertFalse(s.target_drift(live), "kept-only: falsy, never None")
            s.set_dial(s.proj.by_guid["1645021"],
                       "Military/AttackDelay", "30000")
            s.flash(target=live)
            lp = ModProject(live)
            self.assertEqual(lp.by_guid["1645021"].dials["Military/MaxUnitCount"],
                             "99", "the foreign live dial must survive")
            self.assertEqual(lp.by_guid["1645021"].dials["Military/AttackDelay"],
                             "30000", "our own edit lands on top")
        finally:
            s.close()

    def test_true_conflict_reported_when_pending_overwrites_live(self):
        # pending AND live != pending AND opened != live -> TRUE conflict
        # (the save would overwrite a live value the user never saw)
        from annoedit.core import ModProject
        p = ModProject(self.A)
        p.set_dials(p.by_guid["1645021"],
                    {"Military/MaxUnitCount": "99"})
        live = os.path.join(self.W, "live10.rda")
        p.build(live)
        s = self.mk_session()
        try:
            s.open(self.A)
            # our pending edit DIFFERS from the live value (99)
            s.set_dial(s.proj.by_guid["1645021"],
                       "Military/MaxUnitCount", "42")
            drift = s.target_drift(live)
            self.assertIsNotNone(drift)
            self.assertEqual(drift[0], 1)          # one dial conflict
            self.assertTrue(drift.dial_keys)
            self.assertIn("MaxUnitCount", drift.dial_keys[0])
            self.assertEqual(drift.kept_dials, 0)
        finally:
            s.close()

    def test_landed_pending_edit_is_noop_not_conflict(self):
        # a pending edit that already LANDED in live (live == pending)
        # is a no-op — never a conflict (semantics under the replay)
        s = self.mk_session()
        try:
            s.open(self.A)
            p0 = s.proj.by_guid["1645021"]
            s.set_dial(p0, "Military/MaxUnitCount", "77")
            live = os.path.join(self.W, "live11.rda")
            s.export(live)
            s.close()
            s2 = self.mk_session()
            s2.open(self.A)
            s2.set_dial(s2.proj.by_guid["1645021"],
                        "Military/MaxUnitCount", "77")
            self.assertFalse(s2.target_drift(live), 'falsy-not-None')
            s2.close()
        except Exception:
            s.close()
            raise


class RestoreUnmodelledTests(P2120Base):
    """Step 6: surgical restore warns about unmodelled edits."""

    def test_restore_reports_unmodelled_tracked_member(self):
        from annoedit.core import ASSETS_FILE, ModProject
        from annoedit.rda import read_rda, write_rda
        # a live file whose assets.xml carries ANOTHER mod's unmodelled
        # edit (a comment) — restore must report it
        live = os.path.join(self.W, "liveu.rda")
        ents = read_rda(self.A)
        a = ents[ASSETS_FILE][0].decode("latin-1")
        a = a.replace("</Assets>", "<!-- THIRD PARTY MOD --></Assets>", 1)
        ents[ASSETS_FILE] = (a.encode("latin-1"), ents[ASSETS_FILE][1])
        write_rda(ents, live)
        s = self.mk_session()
        try:
            s.provide_vanilla(self.A)
            res = ops.restore_build(
                s._write_lock, s.store, s.exports_store, live, False,
                s.source_path)
            self.assertIn(ASSETS_FILE, res.unmodelled,
                          "restore must report the unmodelled member")
            # the member was restored (vanilla wins for tracked members)
            lp = ModProject(live)
            self.assertEqual(
                lp.entries[ASSETS_FILE][0],
                ModProject(self.A).entries[ASSETS_FILE][0])
        finally:
            s.close()


# ============================================================

class EffectiveRelationTests(P2120Base):
    """Relation exclusivity checked against the EFFECTIVE
    post-build state (file lists overlaid with pending), not pending
    only — the file's Ally list matters."""

    def test_war_against_file_avoidwar_refused(self):
        # the EMPIRICAL exclusivity rule (verified against vanilla AND the
        # playtested trio): War/Ally vs AvoidWar disjoint. Willem's file
        # lists 1645020 in AvoidWar -> War=[1645020] is refused.
        s = self.mk_session()
        try:
            s.open(self.A)
            w = s.proj.by_name["Willem van der Mark"]
            # find a target in Willem's FILE AvoidWar list
            avoid = s.proj.relations(w).get("AvoidWar", ())
            self.assertTrue(avoid, "fixture: Willem must carry AvoidWar")
            target = avoid[0]
            with self.assertRaises(SessionError) as cm:
                s.set_relations(w, war=[target])
            self.assertIn("RESULTING profile", str(cm.exception))
        finally:
            s.close()

    def test_war_against_file_ally_tolerated(self):
        # War vs Ally is TOLERATED by the game: the playtested trio build
        # itself carries 1645006 in BOTH War and Ally for Hildegard and
        # was confirmed working in game — NOT refused
        s = self.mk_session()
        try:
            s.open(self.A)
            w = s.proj.by_name["Willem van der Mark"]
            ally = s.proj.relations(w).get("Ally", ())
            if not ally:
                self.skipTest("fixture: Willem carries no Ally list")
            out = s.set_relations(w, war=list(ally))
            self.assertEqual(out["War"], list(ally))
        finally:
            s.close()

    def test_trade_overlap_war_still_allowed(self):
        # vanilla Giovanni trades with war targets — Trade is not exclusive
        s = self.mk_session()
        try:
            s.open(self.A)
            w = s.proj.by_name["Willem van der Mark"]
            cur = s.proj.relations(w)
            war = list(cur.get("War", ())) or ["1645020"]
            s.set_relations(w, trade=war)      # must NOT raise
            self.assertTrue(True)
        finally:
            s.close()


class CommentSafeIndentTests(P2120Base):
    """Missing-leaf insert must not duplicate comments that
    sit before the parent's first child; comment-free parents stay
    byte-identical (trio-pin shape)."""

    def test_comment_not_duplicated(self):
        from annoedit.model import set_dial, parse_profiles
        txt = ("<Assets>\r\n<Asset>\r\n  <Template>HardCSP</Template>\r\n"
               "  <Values>\r\n    <Military>\r\n"
               "      <!-- tuned by designer -->\r\n"
               "      <MaxUnitCount>10</MaxUnitCount>\r\n"
               "    </Military>\r\n  </Values>\r\n  <Standard>\r\n"
               "    <Name>X</Name>\r\n    <GUID>1</GUID>\r\n  </Standard>\r\n"
               "</Asset>\r\n</Assets>\r\n")
        new = set_dial(txt, parse_profiles("f", txt)[0],
                       "Military/MaxMilitaryPoints", "5")
        self.assertEqual(txt.count("tuned by designer"),
                         new.count("tuned by designer"))
        self.assertIn("<MaxMilitaryPoints>5</MaxMilitaryPoints>", new)
        # exactly one comment remains, well-formed
        self.assertEqual(new.count("<!--"), 1)

    def test_comment_free_parent_shape_unchanged(self):
        from annoedit.model import set_dial, parse_profiles
        txt = ("<Assets>\r\n<Asset>\r\n  <Template>HardCSP</Template>\r\n"
               "  <Values>\r\n    <Military>\r\n"
               "      <MaxUnitCount>10</MaxUnitCount>\r\n"
               "    </Military>\r\n  </Values>\r\n  <Standard>\r\n"
               "    <Name>X</Name>\r\n    <GUID>1</GUID>\r\n  </Standard>\r\n"
               "</Asset>\r\n</Assets>\r\n")
        new = set_dial(txt, parse_profiles("f", txt)[0],
                       "Military/MaxMilitaryPoints", "5")
        self.assertIn("<MaxMilitaryPoints>5</MaxMilitaryPoints>", new)
        self.assertNotIn("\r\r", new)          # no doubled EOLs
        # the existing child is untouched and still exactly once
        self.assertEqual(new.count("<MaxUnitCount>10</MaxUnitCount>"), 1)


class ExactExtrasClearTests(P2120Base):
    """Clearing ONE occurrence of a multi-instance tag clears
    exactly that occurrence; clear_extra remains the explicit all-reset."""

    def test_clear_one_occurrence_only(self):
        s = self.mk_session()
        try:
            s.open(self.A)
            s.set_extra("Noria", "NoriaEndRadius", "11", 0)
            s.set_extra("Noria", "NoriaEndRadius", "22", 1)
            s.set_extra("Noria", "NoriaEndRadius", "", 0)
            pend = {k: v.value for k, v in s.cs.extras.items()}
            self.assertEqual(
                pend, {("Noria", "NoriaEndRadius", 1): "22"},
                "clearing occ#0 must keep occ#1")
        finally:
            s.close()

    def test_clear_extra_resets_all_occurrences(self):
        s = self.mk_session()
        try:
            s.open(self.A)
            s.set_extra("Noria", "NoriaEndRadius", "11", 0)
            s.set_extra("Noria", "NoriaEndRadius", "22", 1)
            s.clear_extra("Noria", "NoriaEndRadius")
            self.assertEqual(dict(s.cs.extras), {})
        finally:
            s.close()


class VanillaCopyValidationTests(P2120Base):
    """The provided vanilla copy is STRICT-parsed before storing."""

    def test_garbage_vanilla_refused(self):
        s = self.mk_session()
        try:
            bad = os.path.join(self.W, "bad.rda")
            with open(bad, "wb") as f:
                f.write(b"not an archive" * 100)
            with self.assertRaises(SessionError) as cm:
                s.provide_vanilla(bad)
            self.assertIn("not a readable", str(cm.exception))
        finally:
            s.close()

    def test_corrupt_vanilla_refused(self):
        s = self.mk_session()
        try:
            bad = os.path.join(self.W, "bad2.rda")
            make_synthetic_rda(bad, variant=0)
            _corrupt_first_txt_block(bad)
            with self.assertRaises(SessionError):
                s.provide_vanilla(bad)
        finally:
            s.close()

    def test_good_vanilla_still_stored(self):
        s = self.mk_session()
        try:
            info = s.provide_vanilla(self.A)
            self.assertEqual(len(info["md5"]), 32)
            self.assertTrue(s.exports_store.has_vanilla_copy())
        finally:
            s.close()


class UnrevertableSurfaceTests(P2120Base):
    """Vanilla mode records (and surfaces) leaves the opened archive
    ADDED that vanilla lacks with no schema default."""

    def test_unrevertable_recorded(self):
        # build a MODDED archive whose Leif has an EXTRA leaf that the
        # vanilla lacks and no schema default exists for
        from annoedit.core import ModProject
        modded = os.path.join(self.W, "modded.rda")
        p = ModProject(self.A)
        # a leaf the synthetic vanilla Leif does NOT carry and the schema
        # has NO default for (a genuinely added leaf)
        added = "Espionage/SuperSecretKnob"
        pv = ModProject(self.A)
        self.assertNotIn(added, pv.by_guid["1645021"].dials)
        self.assertNotIn(added, pv.defaults)
        p.set_dials(p.by_guid["1645021"], {added: "85"})
        p.build(modded)
        s = self.mk_session()
        try:
            s.provide_vanilla(self.A)
            s.open(modded)
            leif = s.proj.by_guid["1645021"]
            self.assertIn(added, leif.dials)
            self.assertNotIn(added, s.proj.defaults)
            s.set_mode(leif, "vanilla")
            self.assertIn(added, s._last_unrevertable)
        finally:
            s.close()
