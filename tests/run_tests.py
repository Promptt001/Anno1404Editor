#!/usr/bin/env python3
"""Anno1404 GameEditor — headless test suite.

Runs with the stdlib unittest runner, no external dependencies, no display:

    python3 tests/run_tests.py

Data-dependent tests (archive round-trips, preset equivalence) need a vanilla
`data1.rda` and are skipped with a clear message when it is not available.
Point them at your copy via:

    ANN0140_TEST_RDA=/path/to/data1.rda python3 tests/run_tests.py
"""
import os
import sys
import subprocess
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Canonical fixture: ANN0140_TEST_RDA when set, otherwise
# the SYNTHETIC archive built into a temp dir. Importing fixture ALSO pins
# ANN0140_HOME (the single user-state root) to a temp dir, so no test (or
# its CLI subprocesses) can touch the real ~/.anno1404gameeditor.
from fixture import TEST_RDA, IS_SYNTHETIC, real_rda, home_untouched  # noqa: E402

# Reasons that mean "a GUI test did not run" (headless box). Used by
# the --require-gui gate: a green run with these skips is NOT green.
import re as _re  # noqa: E402
_GUI_SKIP_RE = _re.compile(r"tkinter|display|headless|Tk", _re.IGNORECASE)


if IS_SYNTHETIC and not os.environ.get("_ANN0140_NO_GUI_COMPILE"):
    # The GUI always gets at least a compile check, even without Tk.
    _gui_dir = os.path.join(os.path.dirname(__file__), "..", "annoedit", "gui")
    _rc = subprocess.run([sys.executable, "-m", "py_compile"] + sorted(
        os.path.join(_gui_dir, f) for f in os.listdir(_gui_dir)
        if f.endswith(".py"))).returncode
    if _rc != 0:
        raise SystemExit("annoedit/gui/*.py failed py_compile (gate)")


class PureLogicTests(unittest.TestCase):
    """No game data needed — always run."""

    def test_package_imports(self):
        import annoedit
        self.assertTrue(annoedit.__version__)

    def test_rda_module_sanity(self):
        from annoedit import rda
        # header parsing constants are module-level; light structural checks
        self.assertTrue(hasattr(rda, "read_rda"))
        self.assertTrue(hasattr(rda, "write_rda"))

    def test_preset_directions_complete(self):
        from annoedit.presets import KEY_DIALS
        for entry in KEY_DIALS:
            self.assertEqual(len(entry), 2)
            path, direction = entry
            self.assertIn(direction, ("max", "min"), path)
            self.assertTrue(path)


@real_rda
class ArchiveTests(unittest.TestCase):
    """Full-pipeline tests against a real (vanilla) data1.rda."""

    @classmethod
    def setUpClass(cls):
        from annoedit.core import ModProject
        cls.proj = ModProject(TEST_RDA)

    def test_roster_loads(self):
        profiles = [p for ps in self.proj.profiles.values() for p in ps]
        self.assertGreaterEqual(len(profiles), 10)
        names = {p.name for p in profiles}
        for expected in ("Giovanni", "Hildegard", "Willem"):
            self.assertTrue(any(expected in n for n in names), expected)

    def test_round_trip_identical(self):
        """Pack the archive unchanged -> re-read -> every entry byte-identical."""
        from annoedit.rda import read_rda, write_rda
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".rda", delete=False) as tf:
            out = tf.name
        try:
            write_rda(self.proj.entries, out)
            back = read_rda(out)
            self.assertEqual(set(back), set(self.proj.entries))
            mismatches = [
                n for n, (d, _) in self.proj.entries.items()
                if back[n][0] != d
            ]
            self.assertEqual(mismatches, [])
        finally:
            os.unlink(out)

    def test_scope_guard_rejects_unknown_profile_edit(self):
        from annoedit.model import EditError, set_dial
        fk = next(iter(self.proj.filetexts))
        text = self.proj.filetexts[fk]
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        import types
        ghost = types.SimpleNamespace(name="NO-SUCH-CHARACTER", guid="999999")
        with self.assertRaises(EditError):
            set_dial(text, ghost, "Military/MaxUnitCount", "70")


class CLITests(unittest.TestCase):
    """Pure-logic CLI checks — no game data, no display."""

    def test_parser_commands_exist(self):
        from annoedit.cli import build_parser
        p = build_parser()
        args = p.parse_args(["personas"])
        self.assertEqual(args.cmd, "personas")
        args = p.parse_args(["apply", "a.rda", "b.rda", "--persona",
                             "The Admiral", "--char", "Leif", "--dry-run"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.persona, "The Admiral")
        args = p.parse_args(["flash", "a.rda", "--json"])
        self.assertTrue(args.json)

    def test_version_flag(self):
        from annoedit import __version__
        from annoedit.cli import build_parser
        with self.assertRaises(SystemExit) as cm:
            build_parser().parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(__version__)


class GUIImportTests(unittest.TestCase):
    """The GUI is display-free at import time (compile/import only)."""

    def test_gui_modules_import(self):
        try:
            import annoedit.gui.app   # noqa  # availability probe
        except ImportError as e:
            self.skipTest(f"tkinter unavailable: {e}")


@real_rda
class PresetEquivalenceTests(unittest.TestCase):
    """Hardened build correctness: clean output, correct scope.

    Historical note: the first shipped hardened build (md5 6aca62a1...) was
    produced by an engine with a latent missing-parent-chain bug — it wrote
    two literal 'INSERT-CHAIN' marker strings into two profiles. The engine
    is fixed; the pinned md5 below is the clean build's, and we additionally
    assert no marker leakage.
    """

    # Whole-file md5 of the hardened build (depends on the zlib build).
    # The authoritative pin is CLEAN_CONTENT: an md5 over the sorted
    # (name, data) pairs of the DECOMPRESSED entries, independent of zlib.
    CLEAN_MD5 = "805c1bc9e8b7ccac5c6580e9f4e30d17"
    CLEAN_CONTENT = "dad7249dd6aa8984c0de63423e8b3509"

    def test_hardened_default_is_clean_and_scoped(self):
        import tempfile
        from annoedit.core import hardened_build
        from annoedit.presets import HARD_GUIDS
        from annoedit.rda import read_rda
        with tempfile.NamedTemporaryFile(suffix=".rda", delete=False) as tf:
            out = tf.name
        try:
            report, _ = hardened_build(TEST_RDA, out, exclude_guids=HARD_GUIDS)
            self.assertEqual(report["md5"], self.CLEAN_MD5)
            # Content hash — the portable, zlib-independent pin
            import hashlib as _hl
            from annoedit.rda import read_rda as _rr
            _e = _rr(out)
            _h = _hl.md5()
            for _name in sorted(_e):
                _h.update(_name.encode() + b"\x00" + _e[_name][0])
            self.assertEqual(_h.hexdigest(), self.CLEAN_CONTENT)
            self.assertEqual(report["changed"],
                             ["addondata/config/ai/aiprofiles.xml",
                              "addondata/config/balancing/addon_01_aiprofiles.xml"])
            for f in report["changed"]:
                data, _ = read_rda(out)[f]
                self.assertNotIn(b"INSERT-CHAIN", data)
        finally:
            os.unlink(out)

    def test_edited_profiles_still_parse_as_xml(self):
        import tempfile
        from annoedit.core import ModProject, hardened_build
        with tempfile.NamedTemporaryFile(suffix=".rda", delete=False) as tf:
            out = tf.name
        try:
            hardened_build(TEST_RDA, out)
            proj2 = ModProject(out)
            for fk, entries_key in (("ai/aiprofiles.xml", None),):
                pass
            for fname, _ in proj2.entries.items():
                if not fname.endswith(".xml"):
                    continue
                if "aiprofiles" not in fname:
                    continue
                data, _ = proj2.entries[fname]
                ET.fromstring(data.decode("utf-8", errors="strict"))
        finally:
            os.unlink(out)


@unittest.skipUnless(
    not IS_SYNTHETIC and os.path.isfile(os.environ.get(
        "ANN0140_TRIO_RDA",
        os.path.join(os.path.dirname(__file__), "..", "..", "builds",
                     "ai_hard_trio_v1_data1.rda"))),
    "needs the real vanilla + the playtested trio build "
    "(set ANN0140_TEST_RDA and ANN0140_TRIO_RDA)")
class PersonaEquivalenceTests(unittest.TestCase):
    """The persona JSONs must reproduce the in-game-verified build
    (the "trio" build, md5 a38800e4...) exactly."""

    TRIO_RDA = os.environ.get(
        "ANN0140_TRIO_RDA",
        os.path.join(os.path.dirname(__file__), "..", "..", "builds",
                     "ai_hard_trio_v1_data1.rda"))

    def test_personas_reproduce_trio(self):
        import re
        from annoedit.core import ModProject
        from annoedit.model import apply_changes, dials_dict
        from annoedit.session import load_personas

        van = ModProject(TEST_RDA)
        trio = ModProject(self.TRIO_RDA)
        pdir = os.path.join(os.path.dirname(__file__), "..", "annoedit", "presets")
        personas = load_personas([pdir])
        # Apply dial edits WITH the playtested insert_after anchors
        # the merged persona map keeps per-dial anchors per character
        changes = {}     # name -> {path: (value, insert_after|None)}
        for label, spec in personas.items():
            for cname, tspec in spec["targets"].items():
                ia = tspec.get("insert_after") or {}
                changes.setdefault(cname, {}).update(
                    {k: (v, ia.get(k)) for k, v in tspec["dials"].items()})

        by_name = {}
        for fk, ps in van.profiles.items():
            for p in ps:
                by_name.setdefault(p.name, []).append((fk, p))
        trio_by_guid = {p.guid: p for ps in trio.profiles.values()
                        for p in ps}

        from annoedit.core import re_find_relations
        from annoedit.session import load_personas
        personas = load_personas([pdir])
        n_dial = n_rel = 0
        for name, dials in changes.items():
            hits = [(fk, p) for fk, p in by_name.get(name, [])
                    if p.template in ("EasyCSP", "MediumCSP", "HardCSP")]
            self.assertEqual(len(hits), 1, (name, hits))
            fk, p = hits[0]
            text = van.filetexts[fk]
            new_text, applied, errors = apply_changes(text, p, dials)
            self.assertEqual(errors, [], f"{name}: apply errors {errors}")
            n_dial += len(applied)
            # The personas' RELATIONS must be applied too
            # the trio build's assets carry them (17 relations GUIDs)
            new_text = self._apply_relations(van, fk, p, name, personas,
                                             new_text)
            m = re.search(re.escape(p.name) + r"</Name>\s*<GUID>"
                          + re.escape(p.guid), new_text)
            self.assertTrue(m, f"identity lost for {name} after edit")
            start = new_text.rfind("<Asset>", 0, m.start())
            end = new_text.find("</Asset>", m.end()) + len("</Asset>")
            new_dials = dials_dict(new_text[start:end])
            tri = trio_by_guid[p.guid].dials
            diff = {k: (tri.get(k), new_dials.get(k))
                    for k in set(tri) | set(new_dials)
                    if tri.get(k) != new_dials.get(k)}
            self.assertEqual(diff, {},
                             f"{name} ({p.guid}): {len(diff)} dial mismatches")
            # Relations compare via re_find_relations, and
            # the FULL asset text compares BYTE-FOR-BYTE against the trio
            # build — the real 'byte-verified' claim, not values only.
            tri_text = trio.text_of(trio_by_guid[p.guid])
            new_asset = new_text[start:end]
            tri_asset = tri_text
            # locate the trio asset the same way (identity slice)
            tm = re.search(re.escape(p.name) + r"</Name>\s*<GUID>"
                           + re.escape(p.guid), tri_text)
            self.assertTrue(tm, f"trio identity lost for {name}")
            tstart = tri_text.rfind("<Asset>", 0, tm.start())
            tend = tri_text.find("</Asset>", tm.end()) + len("</Asset>")
            tri_asset = tri_text[tstart:tend]
            self.assertEqual(
                new_asset, tri_asset,
                f"{name} ({p.guid}): asset text NOT byte-identical with the "
                "playtested trio build")
            rel_new = re_find_relations(new_asset)
            rel_tri = re_find_relations(tri_asset)
            self.assertEqual(
                rel_new, rel_tri,
                f"{name} ({p.guid}): relations differ from the trio build")
            n_rel += sum(len(v) for v in rel_new.values())
        # the trio gate totals: 194 dial edits + 17 persona relations GUIDs
        # (the characters' FULL relations maps carry 29 GUIDs incl. vanilla
        # wiring — the persona-edited kinds carry 17)
        self.assertEqual(n_dial, 194, "persona dial edits vs trio")
        self.assertEqual(n_rel, 29, "relations GUIDs in the trio assets")

    def _apply_relations(self, van, fk, p, name, personas, new_text):
        """Apply the persona's relations edits on top of the dial edits
        full-list replacement through the engine, same build path."""
        from annoedit.core import ModProject
        rels = None
        for label, spec in personas.items():
            for cname, tspec in (spec.get("targets") or {}).items():
                if cname == name and tspec.get("relations"):
                    self.assertIsNone(rels, f"{name}: relations in 2 personas")
                    rels = tspec["relations"]
        if rels is None:
            return new_text
        proj = ModProject.from_entries(van.entries, van.source_rda)
        proj.filetexts = dict(van.filetexts)
        proj.filetexts[fk] = new_text
        prof = proj.by_guid[p.guid]
        kwargs = {k.lower(): list(v) for k, v in rels.items()}
        proj.set_relations(prof, **kwargs)
        return proj.filetexts[fk]


def gate_mode(argv, environ):
    """-> (require_gui, ci, argv_without_flag). The runner's gate
    settings, extracted so tests can exercise the rules directly:

      * --require-gui in argv  -> GUI skips are failures;
      * a CI environment (ANN0140_CI=1 or CI=true/1) IMPLIES
        --require-gui — a headless CI run that skips GUI tests is a
        HARD FAILURE, never a green build (a display-less release
        gate shipped a GUI where every save crashed; CI must never be
        able to repeat that).
    """
    ci = (environ.get("ANN0140_CI") == "1"
          or environ.get("CI", "").lower() in ("true", "1"))
    require_gui = "--require-gui" in argv or ci
    argv = [a for a in argv if a != "--require-gui"]
    return require_gui, ci, argv


if __name__ == "__main__":
    # Require-gui — fail loudly when GUI tests were skipped instead
    # of passing green on a headless box (that is how shipped).
    require_gui, _ci, argv = gate_mode(sys.argv[1:], os.environ)
    if require_gui and _ci:
        print("CI mode: GUI test skips are hard failures "
              "(equivalent to --require-gui)")
    # discover every test_*.py in this directory (session, named presets,
    # backup, equivalence, CLI, GUI-import) plus the classes defined here
    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir=os.path.dirname(os.path.abspath(__file__)),
                            pattern="test_*.py",
                            top_level_dir=os.path.dirname(
                                os.path.abspath(__file__)))
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    # LOUD skip summary — skips are never silent again
    skipped = list(getattr(result, "skipped", []))
    if skipped:
        print(f"\nSKIPPED {len(skipped)} test(s):")
        seen = {}
        for test, reason in skipped:
            seen.setdefault(reason, []).append(str(test))
        for reason, tests in sorted(seen.items()):
            print(f"  [{len(tests)}x] {reason}")
            for t in sorted(tests):
                print(f"        - {t}")
    gui_skip_re = _GUI_SKIP_RE
    gui_skips = [t for t, r in skipped if gui_skip_re.search(r)]
    if require_gui and gui_skips:
        print(f"\nFAIL: --require-gui set but {len(gui_skips)} GUI test(s) "
              "skipped (need tkinter + a display, e.g. xvfb-run -a)")
    # gate: the real home dir must be untouched by the whole run
    ok, msg = home_untouched()
    if not ok:
        print(f"FAIL: {msg}")
        sys.exit(1)
    failed = not result.wasSuccessful() or (require_gui and gui_skips)
    # RESULTS FILE — the release gate's proof: a GUI-capable run of
    # THIS exact tree records its verdict + the tree hash, so a
    # headless release smoke can verify the bypass evidence instead of
    # trusting a bare env var (a bypass that once shipped a broken GUI
    # save). Written on green AND red runs — a red run's results file
    # records failed=true and is rejected by the gate.
    import json as _json
    try:
        _tools = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
        if _tools not in sys.path:
            sys.path.insert(0, _tools)
        from tree_hash import tree_hash
        _results = {
            "ok": not failed,
            "gui_required": bool(require_gui),
            "gui_skips": len(gui_skips),
            "ran": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skips": len(skipped),
            "tree_hash": tree_hash(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..")),
            "python": sys.version.split()[0],
        }
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "results.json"), "w") as _f:
            _json.dump(_results, _f, indent=1)
            _f.write("\n")
    except Exception as _e:  # results recording must never mask failures
        print(f"note: results.json not written ({_e})")
    sys.exit(1 if failed else 0)
