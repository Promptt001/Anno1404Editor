#!/usr/bin/env python3
"""Release-gate tests (headless).

  * tools/tree_hash.py: a stable content hash over the release tree
    (immune to scratch files and results), so gate evidence binds to
    one tree;
  * tools/gate_verify.py: a results.json counts as GUI evidence only
    when it records a green --require-gui run of the same tree;
  * tests/run_tests.py gate_mode: CI implies --require-gui;
  * make_release.sh carries the same-tree evidence requirement (only
    inspected here, never run).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TOOLS = os.path.join(_ROOT, "tools")


def _run(mod, *args, **kw):
    return subprocess.run([sys.executable, os.path.join(_TOOLS, mod), *args],
                          capture_output=True, text=True, **kw)


class TreeHashTests(unittest.TestCase):
    def test_hash_stable_and_scratch_immune(self):
        r1 = _run("tree_hash.py", _ROOT).stdout.strip()
        self.assertEqual(len(r1), 64)
        # scratch files that never ship must NOT move the hash
        probe = os.path.join(_HERE, "scratch_probe.rda")
        results = os.path.join(_HERE, "results.json")
        had_results = os.path.isfile(results)
        saved = None
        if had_results:
            with open(results) as f:
                saved = f.read()
        try:
            open(probe, "wb").close()
            if not had_results:
                open(results, "w").write('{"x":1}')
            r2 = _run("tree_hash.py", _ROOT).stdout.strip()
        finally:
            if os.path.exists(probe):
                os.unlink(probe)
            if not had_results and os.path.exists(results):
                os.unlink(results)
            elif saved is not None:
                with open(results, "w") as f:
                    f.write(saved)
        self.assertEqual(r1, r2, "scratch/results must not move the hash")

    def test_hash_sensitive_to_content(self):
        # A content change in a shipped file MUST move the hash — the
        # gate's same-tree binding depends on this direction too.
        r1 = _run("tree_hash.py", _ROOT).stdout.strip()
        victim = os.path.join(_TOOLS, "tree_hash.py")
        with open(victim) as f:
            saved = f.read()
        try:
            with open(victim, "a") as f:
                f.write("\n# sensitivity probe\n")
            r2 = _run("tree_hash.py", _ROOT).stdout.strip()
        finally:
            with open(victim, "w") as f:
                f.write(saved)
        self.assertNotEqual(r1, r2)

    def test_release_script_pins_evidence_gate(self):
        with open(os.path.join(_TOOLS, "make_release.sh")) as f:
            text = f.read()
        # A bare bypass must no longer be accepted anywhere
        self.assertNotIn("ANN0140_SKIP_GUI_GATE", text)
        # evidence gate markers
        for needle in ("ANN0140_GUI_RESULTS", "gate_verify.py",
                       "SAME tree", "--require-gui"):
            self.assertIn(needle, text, needle)


class GateVerifyTests(unittest.TestCase):
    def _write(self, d, **fields):
        p = os.path.join(d, "results.json")
        base = {"ok": True, "gui_required": True, "gui_skips": 0,
                "ran": 500, "failures": 0, "errors": 0, "skips": 35,
                "tree_hash": _run("tree_hash.py", _ROOT).stdout.strip(),
                "python": "3.12"}
        base.update(fields)
        with open(p, "w") as f:
            json.dump(base, f)
        return p

    def test_accepts_green_require_gui_same_tree(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d)
            r = _run("gate_verify.py", p, _ROOT)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_refuses_headless_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, gui_required=False, gui_skips=19)
            r = _run("gate_verify.py", p, _ROOT)
            self.assertEqual(r.returncode, 1)
            self.assertIn("require-gui", r.stdout)

    def test_refuses_red_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, ok=False, failures=2)
            r = _run("gate_verify.py", p, _ROOT)
            self.assertEqual(r.returncode, 1)
            self.assertIn("NOT green", r.stdout)

    def test_refuses_skipped_gui(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, gui_skips=13)
            r = _run("gate_verify.py", p, _ROOT)
            self.assertEqual(r.returncode, 1)
            self.assertIn("GUI", r.stdout)

    def test_refuses_foreign_tree(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, tree_hash="0" * 64)
            r = _run("gate_verify.py", p, _ROOT)
            self.assertEqual(r.returncode, 1)
            self.assertIn("DIFFERENT tree", r.stdout)

    def test_refuses_corrupt_or_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "results.json")
            with open(p, "w") as f:
                f.write("{not json")
            r = _run("gate_verify.py", p, _ROOT)
            self.assertEqual(r.returncode, 1)
            self.assertIn("unreadable", r.stdout)
            r = _run("gate_verify.py", os.path.join(d, "none.json"), _ROOT)
            self.assertEqual(r.returncode, 1)


class GateModeTests(unittest.TestCase):
    def test_rules(self):
        from run_tests import gate_mode
        self.assertEqual(gate_mode([], {}), (False, False, []))
        self.assertEqual(gate_mode(["--require-gui"], {}),
                         (True, False, []))
        self.assertEqual(gate_mode([], {"CI": "true"}), (True, True, []))
        self.assertEqual(gate_mode([], {"ANN0140_CI": "1"}), (True, True, []))
        self.assertEqual(gate_mode([], {"CI": "false"}), (False, False, []))
        self.assertEqual(gate_mode(["--require-gui"], {"CI": "1"}),
                         (True, True, []))
        # the flag is stripped from argv for the unittest runner
        self.assertEqual(gate_mode(["--require-gui", "-v"], {}),
                         (True, False, ["-v"]))


if __name__ == "__main__":
    unittest.main()
