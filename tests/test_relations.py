#!/usr/bin/env python3
"""Relations feature tests (Session + CLI + GUI dialog).

Relations are the War/Ally/Trade/AvoidWar ProfileGUID lists inside each
profile's <Relationships> block. They are edited through the Session
(validated + dry-run before acceptance), surfaced in the CLI and in the
character editor's Relations dialog, and carried by persona presets.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from annoedit.backup import md5_of
from annoedit.session import Session, SessionError, load_personas

from fixture import TEST_RDA, HAVE_RDA

# authoritative relations of the in-game-verified persona ("trio") build
TRIO_RELS = {
    "1645021": {"War": ["1645020", "1645024", "1645026"],
                "AvoidWar": ["1645028", "1645022"]},
    "1645023": {"War": ["1645006", "1645020", "1645027"],
                "AvoidWar": ["1645028", "1645022", "1645024", "1645026"]},
    "1645025": {"War": ["1645006", "1645020", "1645024"],
                "AvoidWar": ["1645028", "1645021"]},
}


class PureRelationsTests(unittest.TestCase):
    """No game data needed — always run."""

    def test_trio_rels_data_complete(self):
        for guid, rels in TRIO_RELS.items():
            for kind in ("War", "AvoidWar"):
                self.assertIn(kind, rels, guid)
                self.assertTrue(rels[kind], f"{guid}/{kind} empty")

    @unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
    def test_persona_files_carry_trio_relations(self):
        personas = load_personas()
        exp = {"The Admiral": "1645021", "The Spider": "1645023",
               "The Conqueror": "1645025"}
        for label, guid in exp.items():
            self.assertIn(label, personas)
            targets = personas[label]["targets"]
            hit = [t for t in targets.values() if t.get("relations")]
            self.assertTrue(hit, f"{label}: no target carries relations")
            rels = hit[0]["relations"]
            self.assertEqual(rels, TRIO_RELS[guid], label)



def safe_war_target(ses, profile):
    """A war target coherent with the FILE lists
    NOT in the profile's current AvoidWar list (the effective-state check
    refuses that). Works on the synthetic fixture AND real data (picks
    the first other profile not in the profile's AvoidWar)."""
    avoid = set(ses.proj.relations(profile).get("AvoidWar", ()))
    for g, q in ses.proj.by_guid.items():
        if g != profile.guid and g not in avoid:
            return g
    raise AssertionError("fixture has no war-safe target")


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class SessionRelationsTests(unittest.TestCase):
    """set_relations pending state, validation, build, flash, restore."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cerel_")
        self.src = os.path.join(self.tmp, "data1.rda")
        shutil.copyfile(TEST_RDA, self.src)
        self.vanilla_md5 = md5_of(self.src)
        self.ses = Session(backup_root=os.path.join(self.tmp, "backups"),
                           exports_root=os.path.join(self.tmp, "exports"),
                           persona_dirs=(os.path.join(
                               os.path.dirname(__file__), "..", "annoedit", "presets"),))

    def tearDown(self):
        self.ses.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def prof(self, key):
        if key in self.ses.proj.by_guid:
            return self.ses.proj.by_guid[key]
        return self.ses.proj.by_name[key]

    def test_set_relations_queues_pending(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        # The war target must be coherent with
        # the FILE lists — vanilla Leif lists 1645020 in AvoidWar, so
        # a Venetian (in no base profile's lists) is the safe target
        tgt = safe_war_target(self.ses, p)
        out = self.ses.set_relations(p, war=[tgt])
        self.assertEqual(out["War"], [tgt])
        # current (source) untouched, pending visible via relations_row
        self.assertEqual(self.ses.proj.relations(p).get("War", []), [])
        self.assertEqual(self.ses.relations_row(p, "War"), [tgt])
        self.assertIn(f"Relations/War: [] -> ['{tgt}']",
                      self.ses.change_report())

    def test_set_relations_full_replacement_semantics(self):
        self.ses.open(self.src)
        p = self.prof("1645025")   # vanilla has Trade + Ally + AvoidWar
        out = self.ses.set_relations(p, avoidwar=[])
        self.assertEqual(out["AvoidWar"], [])
        # kinds not passed are NOT queued (leave-as-is)
        self.assertNotIn("Trade", out)
        self.assertNotIn("Ally", out)

    def test_set_relations_rejects_unknown_name(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        with self.assertRaises(SessionError):
            self.ses.set_relations(p, war=["Nobody Here"])

    def test_set_relations_rejects_bad_kind(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        from annoedit.session import _norm_rels
        with self.assertRaises(SessionError):
            _norm_rels({"Pest": ["1645020"]})

    def test_set_relations_rejects_non_list(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        with self.assertRaises(SessionError):
            self.ses.set_relations(p, war="1645020")  # type error, value irrelevant

    def test_build_applies_relations(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        self.ses.set_relations(p, war=TRIO_RELS["1645021"]["War"],
                               avoidwar=TRIO_RELS["1645021"]["AvoidWar"])
        out = os.path.join(self.tmp, "out.rda")
        rep = self.ses.export(out)
        self.assertEqual(rep["relations_edits"], 5)
        self.assertIn("addondata/config/ai/aiprofiles.xml", rep["changed"])
        from annoedit.core import ModProject
        p2 = ModProject(out)
        got = {k: v for k, v in p2.relations(p2.by_guid["1645021"]).items()
               if k in TRIO_RELS["1645021"]}
        self.assertEqual(got, TRIO_RELS["1645021"])

    def test_clear_relations_and_mode_vanilla(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        tgt = safe_war_target(self.ses, p)
        self.ses.set_relations(p, war=[tgt])
        self.ses.clear_relations(p, "War")
        self.assertNotIn("1645021", self.ses.rels)
        self.ses.set_relations(p, war=[tgt])
        self.ses.set_mode(p, "vanilla")
        self.assertNotIn("1645021", self.ses.rels)
        self.assertEqual(self.ses.relations_row(p, "War"), [])

    def test_flash_writes_relations_in_place(self):
        self.ses.open(self.src)
        p = self.prof("1645023")
        # War alone would clash with Hildegard's FILE
        # AvoidWar (the trio War list includes 1645020, which vanilla
        # Hildegard avoids) — the persona applies War AND AvoidWar
        # together (the trio build's coherent pair), so do the same here
        self.ses.set_relations(p, war=TRIO_RELS["1645023"]["War"],
                               avoidwar=TRIO_RELS["1645023"]["AvoidWar"])
        rep = self.ses.flash()
        self.assertEqual(rep["relations_edits"], 7)
        from annoedit.core import ModProject
        p2 = ModProject(self.src)
        self.assertEqual(p2.relations(p2.by_guid["1645023"])["War"],
                         TRIO_RELS["1645023"]["War"])

    def test_restore_drops_pending_relations(self):
        self.ses.open(self.src)
        p = self.prof("1645025")
        self.ses.set_relations(p, war=[safe_war_target(self.ses, p)])
        self.ses.flash()
        self.ses.restore_vanilla()
        self.assertEqual(self.ses.rels, {})
        self.assertEqual(self.ses.relations_row(p, "War"), [])

    def test_persona_mode_queues_relations(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        self.ses.set_mode(p, "The Admiral")
        self.assertEqual(self.ses.rels["1645021"]["War"],
                         TRIO_RELS["1645021"]["War"])
        # relations-only flash must be allowed (guard includes rels)
        rep = self.ses.flash()
        self.assertEqual(rep["relations_edits"], 5)
        from annoedit.core import ModProject
        p2 = ModProject(self.src)
        got = {k: v for k, v in p2.relations(p2.by_guid["1645021"]).items()
               if k in TRIO_RELS["1645021"]}
        self.assertEqual(got, TRIO_RELS["1645021"])

    def test_named_preset_roundtrip_carries_relations(self):
        self.ses.open(self.src)
        p = self.prof("1645021")
        self.ses.set_relations(p, war=[safe_war_target(self.ses, p)])
        # a preset with relations + one dial
        preset_path = os.path.join(self.tmp, "p.json")
        with open(preset_path, "w", encoding="utf-8") as f:
            json.dump({"name": "x", "description": "",
                       "characters": {p.name: {
                           "dials": {"Build/BuildingSpeed": "99"},
                           "relations": {"War": [safe_war_target(self.ses, p)]}}}}, f)
        # session applies it via load_named_preset-style flow is for dials;
        # relations in named presets ride the same JSON shape (spec test)
        with open(preset_path, encoding="utf-8") as f:
            data = json.load(f)
        spec = data["characters"][p.name]
        self.ses.set_relations(
            p, war=spec["relations"].get("War"))
        self.assertEqual(self.ses.rels[p.guid]["War"],
                         [safe_war_target(self.ses, p)])


@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class CliRelationsTests(unittest.TestCase):
    """`relations` view + `relations-apply` spec JSON round trip."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cerelcli_")
        self.src = os.path.join(self.tmp, "data1.rda")
        shutil.copyfile(TEST_RDA, self.src)
        self.store_root = os.path.join(self.tmp, "backups")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relations_view_and_apply(self):
        from annoedit import cli
        from annoedit.backup import BackupStore
        real_init = BackupStore.__init__

        def patched(self_, root=None):
            real_init(self_, self.store_root)

        BackupStore.__init__ = patched
        try:
            rc = cli.main(["relations", self.src, "1645021"])
            self.assertEqual(rc, 0)
            spec = os.path.join(self.tmp, "spec.json")
            with open(spec, "w", encoding="utf-8") as f:
                json.dump({"relations": [{
                    "character": "Leif Jorgensen",
                    "War": ["1645020", "1645024", "1645026"],
                    "AvoidWar": ["1645028"]}]}, f)
            out = os.path.join(self.tmp, "out.rda")
            rc = cli.main(["relations-apply", self.src, out, spec])
            self.assertEqual(rc, 0)
            from annoedit.core import ModProject
            p2 = ModProject(out)
            rel = p2.relations(p2.by_guid["1645021"])
            self.assertEqual(rel["War"], ["1645020", "1645024", "1645026"])
            self.assertEqual(rel["AvoidWar"], ["1645028"])
        finally:
            BackupStore.__init__ = real_init


try:
    import tkinter as tk
    HAVE_TK = True
except Exception:                 # no display / no python3-tk
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "no tkinter")
@unittest.skipUnless(HAVE_RDA, f"no test archive at {TEST_RDA}")
class GuiRelationsTests(unittest.TestCase):
    """The Relations dialog: pending-state wiring headless."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cerelgui_")
        self.src = os.path.join(self.tmp, "data1.rda")
        shutil.copyfile(TEST_RDA, self.src)
        # GUI tests need a display; skip gracefully if none (CI).
        try:
            import tkinter  # noqa
        except Exception:
            raise unittest.SkipTest("no tkinter/display")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relations_dialog_add_and_remove(self):
        try:
            root = tk.Tk()
        except Exception:
            raise unittest.SkipTest("no display")
        try:
            ses = Session(backup_root=os.path.join(self.tmp, "backups"),
                          exports_root=os.path.join(self.tmp, "exports"),
                          persona_dirs=(os.path.join(
                              os.path.dirname(__file__), "..", "annoedit", "presets"),))
            ses.open(self.src)
            p = ses.proj.by_guid["1645021"]
            from annoedit.gui.editor import RelationsDialog
            dlg = RelationsDialog(root, ses, p)
            # pending relations empty before any edit
            self.assertEqual(ses.rels.get(p.guid, {}), {})
            # add via the dialog's add-button session call (headless path:
            # same call the '+' button makes, minus the modal picker)
            ses.set_relations(p, war=ses.relations_row(p, "War") + ["1645024"])
            self.assertEqual(ses.rels[p.guid]["War"], ["1645024"])
            # refresh reflects the pending list (display names carry the guid)
            dlg._refresh()
            # derive the expected display name from the
            # roster instead of hardcoding a stale spelling
            expected = [f"{ses.proj.by_guid['1645024'].name} (1645024)"]
            self.assertEqual(dlg._kind_names("War"), expected)
            # remove via the same path the '−' button uses
            ses.set_relations(p, war=[g for g in ses.relations_row(p, "War")
                                      if g != "1645024"])
            self.assertEqual(ses.rels.get(p.guid, {}).get("War", []), [])
            dlg.destroy()
            ses.close()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
