#!/usr/bin/env python3
"""Source gates: no direct pending-dict writes outside ChangeSet, and
named presets carry relations.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixture import TEST_RDA  # noqa: E402


REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GUI_CLI = [os.path.join(REPO, "annoedit", "gui"),
           os.path.join(REPO, "annoedit", "cli.py")]
# direct pending-dict writes: X['key'] = ..., X.pop(...), del X[...] on the
# four compat views — the GUI/CLI must go through Session.set_* methods.
# the old pattern ended in \b AFTER '}' / ')' — \b never
# matches there (word char to non-word char is required), so '= {}' was
# NEVER caught (that is exactly how shipped). No trailing \b now.
_WRITE_PAT = re.compile(
    r"\b(changes|rels|extras|fert)\s*(\[[^\]]+\]\s*=[^=]|\.pop\(|\.setdefault\(|\.clear\(\)|= *(\{\}|dict\(\)))")


def _gate_offending_lines(sample):
    """The gate's matcher as a function, so the self-test (below) feeds it
    known-bad and known-good samples instead of trusting the regex by sight."""
    return [f"line {i}: {line.strip()}" for i, line in
            enumerate(sample.splitlines(), 1)
            if _WRITE_PAT.search(line)]


class GrepGateTests(unittest.TestCase):
    """No direct pending-dict writes in the GUI or the CLI."""

    def test_no_direct_pending_writes_in_gui_or_cli(self):
        offenders = []
        for target in GUI_CLI:
            if os.path.isdir(target):
                files = [os.path.join(target, f) for f in
                         sorted(os.listdir(target)) if f.endswith(".py")]
            else:
                files = [target]
            for path in files:
                with open(path, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if _WRITE_PAT.search(line):
                            offenders.append(f"{path}:{i}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            "direct pending-dict writes outside ChangeSet:\n"
            + "\n".join(offenders))

    def test_gate_matches_direct_writes_negative_self_test(self):
        """the gate must catch the class of bug ('ses.extras = {}'
        crashed the 'Reset all extras' button) and NOT flag legal lines.
        The old regex's trailing \b could never match '= {}'.
        """
        bad = [
            "            ses.extras = {}",
            "        self.fert = {}",
            "    app.changes[guid] = {k: v}",
            "        ses.rels.pop(guid)",
            "            self.extras.clear()",
            "    x = dict() if y else ses.changes = {}",
        ]
        self.assertEqual(len(_gate_offending_lines("\n".join(bad))), 6)
        good = [
            "            ses.clear_extras()",
            "        out = {k: e.value for k, e in self.cs.extras.items()}",
            "        pend = self.ses.changes.get(self.profile.guid, {})",
            "            # set_extras calls the session, never the dict",
            "        for k, v in self.extras.items()",
        ]
        self.assertEqual(_gate_offending_lines("\n".join(good)), [])


class NamedPresetRelationTests(unittest.TestCase):
    """named presets save AND load relations (persona file shape)."""

    def setUp(self):
        import shutil
        import tempfile
        from annoedit.session import Session
        self.tmp = tempfile.mkdtemp(prefix="np9_")
        self.ses = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=_tmp_settings(self.tmp))
        shutil.copyfile(TEST_RDA, os.path.join(self.tmp, "data1.rda"))
        self.ses.open(os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        self.ses.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_named_preset_roundtrip_carries_relations(self):
        p = self.ses.proj.by_guid["1645021"]
        self.ses.set_dial(p, "Military/MaxUnitCount", "99")
        # War targets must be coherent with the
        # FILE lists — not in this profile's AvoidWar list
        avoid = set(self.ses.proj.relations(p).get("AvoidWar", ()))
        t = [g for g in self.ses.proj.by_guid
             if g != p.guid and g not in avoid][:2]
        self.ses.set_relations(p, war=t)
        self.ses.save_named_preset(p, "warmonger")
        # a FRESH session on the same archive (the preset was saved to the
        # settings-dir store, which persists independent of the session)
        from annoedit.session import Session
        self.ses.close()          # release the store lock before re-opening
        s2 = Session(
            backup_root=os.path.join(self.tmp, "backups"),
            exports_root=os.path.join(self.tmp, "exports"),
            settings=_tmp_settings(self.tmp))
        s2.open(os.path.join(self.tmp, "data1.rda"))
        p2 = s2.proj.by_guid["1645021"]
        got = s2.load_named_preset(p2, "warmonger")
        self.assertEqual(got.get("Military/MaxUnitCount"), "99")
        # the relations came back as pending relations
        self.assertEqual(s2.rels["1645021"]["War"], t)
        s2.close()


class GuiSourceGates(unittest.TestCase):
    """AST/source gates on gui/app.py — (refuse close while busy)."""

    def test_on_close_refuses_while_busy(self):
        # On_close must check the busy flag BEFORE the pending-changes
        # dialog and return early (a background build must never be torn
        # down mid-run by closing the window)
        import ast
        path = os.path.join(REPO, "annoedit", "gui", "app.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_close":
                body = node.body
                if body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant):
                    body = body[1:]     # skip the docstring
                self.assertTrue(body, "on_close has an empty body")
                # first real statement must test the busy flag
                src = ast.dump(body[0])
                self.assertIn("_busy_flag", src,
                              "on_close must refuse close while busy")
                return
        self.fail("on_close not found")


def _tmp_settings(tmp):
    from annoedit.appsettings import Settings
    return Settings(os.path.join(tmp, "settings", "settings.json"))


if __name__ == "__main__":
    unittest.main()
