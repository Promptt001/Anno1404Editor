#!/usr/bin/env python3
"""Replay, restore and locator regressions (synthetic archive).

- source_md5 after an in-place surgical restore is the md5 of the bytes
  actually written, so the next in-place save works.
- A pending INSERT extras edit is clearable via occ=None.
- CLI restore over a corrupt archive succeeds (no open first).
- Unmodelled detection is a true residual compare.
- A commented-out duplicate asset never captures an edit.
- Vanilla-mode queue order is PYTHONHASHSEED-independent.
- An export named 'foo.meta.json' is refused (meta collision).
- The extras replay guard refuses when the live occurrence count or old
  value differs from queue time.
- Non-UTF-8 bytes in datasets.xml never silently disable validation.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: (pins ANN0140_HOME isolation on import)
from synthetic_rda import make_synthetic_rda

from annoedit.rda import read_rda, write_rda
from annoedit.session import Session, SessionError

LEIF = "1645021"
M = "addondata/config/ai/aiprofiles.xml"
A = "addondata/config/game/assets.xml"
D = "addondata/config/game/datasets.xml"


def _mutate(path, fn):
    e = read_rda(path)
    fn(e)
    write_rda(e, path)


class _Base(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="t213_")

    def synth(self, name="data1.rda", variant=0):
        p = os.path.join(self.W, name)
        make_synthetic_rda(p, variant)
        return p


class R1SourceMd5AfterRestore(_Base):
    def test_in_place_save_works_after_surgical_restore(self):
        van = self.synth("vanilla.rda")
        live = self.synth("live.rda")
        _mutate(live, lambda e: e.update(
            {"data/othermod.txt": (b"other mod", 1)}))
        s = Session()
        s.provide_vanilla(van)
        s.open(live)
        s.set_dial(s.proj.by_guid[LEIF], "Military/MaxUnitCount", "77")
        s.flash()
        s.restore_vanilla()
        # the follow-up edit + in-place save must NOT be refused
        s.set_dial(s.proj.by_guid[LEIF], "Military/MaxUnitCount", "55")
        rep = s.flash()
        self.assertTrue(rep["in_place"])
        s.close()
        # and the save landed: the dial reads back 55
        s2 = Session(); s2.open(live)
        self.assertEqual(
            s2.proj.by_guid[LEIF].dials["Military/MaxUnitCount"], "55")
        s2.close()

    def test_restore_result_carries_written_md5(self):
        from annoedit.backup import md5_of
        van = self.synth("v.rda")
        live = self.synth("l.rda")
        _mutate(live, lambda e: e.update(
            {"data/othermod.txt": (b"other mod", 1)}))
        s = Session(); s.provide_vanilla(van); s.open(live)
        s.restore_vanilla()
        self.assertEqual(s.source_md5, md5_of(live))
        s.close()


class R2ClearPendingInsert(_Base):
    def test_pending_insert_clearable(self):
        s = Session(); s.open(self.synth())
        s.set_extra("PrintingHouse", "ProductionTime", "30000")  # INSERT
        self.assertEqual(len(s.cs.extras), 1)
        s.set_extra("PrintingHouse", "ProductionTime", "", None)  # clear
        self.assertEqual(list(s.cs.extras), [])
        s.close()


class R3CliRestoreCorrupt(_Base):
    def _cli(self, *a):
        env = dict(os.environ)
        env.pop("ANN0140_TEST_RDA", None)
        return subprocess.run(
            [sys.executable, "-m", "annoedit.cli", *a],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=env, capture_output=True, text=True, timeout=180)

    def test_restore_over_corrupt_archive(self):
        van = self.synth("v.rda")
        bad = self.synth("bad.rda")
        with open(bad, "rb") as f:
            b = bytearray(f.read())
        b[-40:-20] = b"\xff" * 20
        with open(bad, "wb") as f:
            f.write(bytes(b))
        self._cli("provide-vanilla", van)
        r = self._cli("restore", bad)
        self.assertEqual(r.returncode, 0, r.stderr)
        # restored: the 4 tracked members parse again
        from annoedit.core import ModProject
        self.assertIn(M, ModProject(bad).entries)


class R4UnmodelledResidual(_Base):
    def _proj_pair(self, modeled, other):
        van = self.synth("v.rda")
        def mut(e):
            raw, ts = e[M]; t = raw.decode()
            if modeled:
                t = t.replace("<MaxUnitCount>41</MaxUnitCount>",
                              "<MaxUnitCount>99</MaxUnitCount>", 1)
            if other:
                t += "<!-- other mod -->"
            e[M] = (t.encode(), ts)
        p = self.synth("m.rda"); _mutate(p, mut)
        from annoedit.core import ModProject
        from annoedit import ops
        return ops, ModProject(p), ModProject(van)

    def test_mixed_modeled_plus_unmodelled_reported(self):
        ops, P, V = self._proj_pair(True, True)
        self.assertTrue(ops._modeled_member_diff(P, V, M))

    def test_only_other_mod_reported(self):
        ops, P, V = self._proj_pair(False, True)
        self.assertTrue(ops._modeled_member_diff(P, V, M))

    def test_pure_modeled_not_reported(self):
        ops, P, V = self._proj_pair(True, False)
        self.assertFalse(ops._modeled_member_diff(P, V, M))

    def test_identical_not_reported(self):
        ops, P, V = self._proj_pair(False, False)
        self.assertFalse(ops._modeled_member_diff(P, V, M))


class R5CommentedAsset(_Base):
    def _comment_dup(self, p):
        def mut(e):
            t = e[M][0].decode()
            blk = next(m.group(0) for m in
                       re.finditer(r"<Asset>.*?</Asset>", t, re.S)
                       if "<Name>Leif Jorgensen</Name>" in m.group(0))
            i = t.find("<Asset>")
            e[M] = ((t[:i] + "<!-- old version\n" + blk + "\n-->\n"
                     + t[i:]).encode(), e[M][1])
        _mutate(p, mut)

    def test_roster_lists_char_once_and_edit_lands_in_live_asset(self):
        p = self.synth("c.rda"); self._comment_dup(p)
        s = Session(); s.open(p)
        self.assertEqual(
            sum(q.name == "Leif Jorgensen" for q in s.roster), 1)
        s.set_dial(s.proj.by_guid[LEIF], "Military/MaxUnitCount", "99")
        out = os.path.join(self.W, "c_out.rda"); s.export(out)
        t = read_rda(out)[M][0].decode()
        # the edit must NOT be inside the comment span
        c0, c1 = t.find("<!--"), t.find("-->")
        live = t.find("<MaxUnitCount>99<")
        self.assertFalse(c0 < live < c1)
        self.assertGreater(live, c1)   # after the comment, in the real asset
        s.close()

    def test_extras_parse_assets_comment_blind(self):
        from annoedit.extras import parse_assets
        t = read_rda(self.synth())[A][0].decode("latin-1")
        a0 = next(a for a in parse_assets(t) if a["name"] == "Bakery")
        commented = ("<!-- <Asset><Template>Building</Template>"
                     + t[a0["start"]:a0["end"]]
                     + " -->\n") + t
        names = [a["name"] for a in parse_assets(commented)]
        self.assertEqual(names.count("Bakery"), 1)


class R7HashSeedOrder(_Base):
    def test_vanilla_mode_order_seed_independent(self):
        body = (
            "import os, sys\n"
            "sys.path.insert(0, {root!r})\n"
            "sys.path.insert(0, os.path.join({root!r}, 'tests'))\n"
            "os.environ['ANN0140_HOME'] = {home!r}\n"
            "os.environ.pop('ANN0140_EXPORTS_DIR', None)\n"
            "os.environ.pop('ANN0140_TEST_RDA', None)\n"
            "from synthetic_rda import make_synthetic_rda\n"
            "from annoedit.session import Session\n"
            "van = os.path.join({home!r}, 'v.rda'); make_synthetic_rda(van, 0)\n"
            "mod = os.path.join({home!r}, 'm.rda'); make_synthetic_rda(mod, 1)\n"
            "s = Session(); s.provide_vanilla(van); s.open(mod)\n"
            "s.set_mode(s.proj.by_guid['1645027'], 'vanilla')\n"
            "print(list(s.changes['1645027']))\n")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        home = tempfile.mkdtemp(prefix="seed_")
        code = body.format(root=root, home=home)
        outs = set()
        for seed in ("1", "2", "3", "4"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            r = subprocess.run([sys.executable, "-c", code],
                               env=env, capture_output=True, text=True,
                               cwd=root, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            outs.add(r.stdout.strip())
        self.assertEqual(len(outs), 1)   # ONE order across all seeds


class R8ExportNameCollision(_Base):
    def test_meta_json_name_refused(self):
        from annoedit.exports import ExportStore, ExportsError
        st = ExportStore(os.path.join(self.W, "exp"))
        src = self.synth("e.rda")
        st.save_named_export(src, "foo", note="original note")
        with self.assertRaises(ExportsError):
            st.save_named_export(src, "foo.meta.json")
        # the original export's meta SURVIVED
        self.assertEqual(st._read_meta("foo").get("note"), "original note")


class R9ExtrasReplayGuard(_Base):
    def _live_with_added_level(self):
        def add_level(e):
            raw, ts = e[A]
            e[A] = (raw.replace(
                b"<NoriaEndRadius>8</NoriaEndRadius>",
                b"<NoriaEndRadius>6</NoriaEndRadius>\r\n"
                b"      <NoriaEndRadius>8</NoriaEndRadius>", 1), ts)
        live = self.synth("l.rda"); _mutate(live, add_level)
        return live

    def test_replay_refuses_on_occurrence_count_change(self):
        from annoedit.core import ModProject
        opened = self.synth("o.rda")
        live = self._live_with_added_level()
        s = Session(); s.set_live_path(live); s.open(opened)
        s.set_extra("Noria", "NoriaEndRadius", "12", 1)
        with self.assertRaises(SessionError) as cm:
            s.flash(target=live)
        self.assertIn("occurrence", str(cm.exception))
        s.close()
        # live untouched by the refused save
        vals = ModProject(live).extras_catalog()["noria"][
            "NoriaEndRadius"]["Noria"]
        self.assertEqual(vals, ["6", "8", "10"])

    def test_replay_control_applies_without_live_change(self):
        from annoedit.core import ModProject
        opened = self.synth("o2.rda")
        live = self.synth("l2.rda")
        s = Session(); s.set_live_path(live); s.open(opened)
        s.set_extra("Noria", "NoriaEndRadius", "12", 1)
        s.flash(target=live)
        vals = ModProject(live).extras_catalog()["noria"][
            "NoriaEndRadius"]["Noria"]
        self.assertEqual(vals, ["8", "12"])
        s.close()


class R10DatasetsEncoding(_Base):
    def test_non_utf8_datasets_keeps_choice_validation(self):
        def mut(e):
            raw, ts = e[D]
            e[D] = (raw.replace(
                b"<DataSets>", b"<DataSets><!-- Gr\xfc\xdfe -->", 1), ts)
        p = self.synth("ds.rda"); _mutate(p, mut)
        s = Session(); s.open(p)
        bar = s.proj.by_guid["1645020"]
        # the enumeration LOADED (latin-1): choices are non-empty
        choices = s.datasets_choices("ResidentLevel")
        self.assertTrue(choices)
        # and a bogus Choice value is REFUSED (never silently accepted)
        with self.assertRaises(SessionError):
            s.set_dial(bar, "Build/MaxCivilizationLevel",
                       "TotallyBogusLevel")
        s.close()

    def test_enum_validation_available_true_and_fail_closed(self):
        p = self.synth()
        s = Session(); s.open(p)
        self.assertTrue(s.enum_validation_available)
        s.close()
        # a datasets.xml that fails ET parsing -> validation OFF and the
        # Choice dial FAILS CLOSED (refused, never silently accepted)
        def mut(e):
            raw, ts = e[D]
            e[D] = (raw.replace(b"<DataSets>", b"<DataSets><oops", 1), ts)
        p2 = self.synth("ds2.rda"); _mutate(p2, mut)
        s2 = Session(); s2.open(p2)
        self.assertFalse(s2.enum_validation_available)
        bar = s2.proj.by_guid["1645020"]
        with self.assertRaises(SessionError):
            s2.set_dial(bar, "Build/MaxCivilizationLevel", "TotallyBogus")
        s2.close()


class Misc2130(_Base):
    """One permanent pin each."""

    def test_rebase_raises_on_unreadable_existing_target(self):
        from annoedit.rda import RdaFormatError
        B = os.path.join(self.W, "corrupt.rda")
        open(B, "wb").write(b"garbage" * 100)
        s = Session(); s.open(self.synth())
        s.set_dial(s.proj.by_guid[LEIF], "Military/MaxUnitCount", "55")
        with self.assertRaises((SessionError, RdaFormatError)):
            s.flash(B)
        # the corrupt target was NOT overwritten
        with open(B, "rb") as f:
            self.assertEqual(f.read(), b"garbage" * 100)
        s.close()

    def test_stale_temp_sweep_on_open(self):
        p = self.synth("g.rda")
        stale = os.path.join(self.W, ".flashbuild-999999.rda")
        open(stale, "wb").write(b"junk" * 100)
        s = Session(); s.open(p)
        self.assertFalse(os.path.exists(stale))
        s.close()

    def test_unchanged_label_not_a_mode(self):
        # 'Unchanged' is a display label; the GUI maps it to no-op.
        # Headless pin: the label is produced only by _mode_label-like
        # logic; here we pin that set_mode REJECTS it.
        s = Session(); s.open(self.synth())
        with self.assertRaises(SessionError):
            s.set_mode(s.proj.by_guid[LEIF], "Unchanged")
        s.close()


if __name__ == "__main__":
    unittest.main()
