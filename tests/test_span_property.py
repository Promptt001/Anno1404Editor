#!/usr/bin/env python3
"""Property tests for the span engine.

Random nested XML with repeated tag names at different depths ->
random path edits -> invariants:
  ORACLE: dials_dict(new) == dials_dict(old) + exactly the applied changes;
  BYTE IDENTITY: everything outside the edited asset's <Values> span is
  byte-identical (CRLF and all);
  WELL-FORMED: the edited text still parses as XML.

List structure (repeated siblings, Item/Profiles) is generated in the trees
but never targeted: those paths are not dials and are edited via
set_relations, not set_dial.
"""
import random
import sys
import os
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from annoedit.model import (EditError, Profile, apply_changes,  # noqa: E402
                            dials_dict, set_dial, _locate_values)

# tree tag alphabet — repeated siblings and nested same-name shapes arise
TREE_TAGS = ["Cat", "Mil", "B", "C", "D", "E", "F", "Max", "Town"]
# Item/Profiles only ever appear as repeated siblings (list structure, )
LIST_TAGS = ["Item", "Profiles"]
# dial-path alphabet for the random missing-chain / refusal probes
PATH_TAGS = ["Cat", "Mil", "B", "C", "D", "E", "F", "Max", "Town", "Zz"]


def _gen_tree(rng, depth, ind, eol):
    """Random well-formed XML children at `ind`, depth-capped."""
    parts = []
    n = rng.randint(0, 4)
    tags = [rng.choice(TREE_TAGS) for _ in range(n)]
    if n and rng.random() < 0.25:
        tags.append(rng.choice(tags))          # repeated sibling (list)
    if rng.random() < 0.12:
        tags.append(rng.choice(LIST_TAGS))
        tags.append(rng.choice(LIST_TAGS))    # Item/Profiles pair (shape)
    for tag in tags:
        if rng.random() < 0.08:
            parts.append(f"{ind}<{tag}/>{eol}")            # self-closed
        elif depth > 0 and rng.random() < 0.45:
            inner = _gen_tree(rng, depth - 1, ind + "  ", eol)
            parts.append(f"{ind}<{tag}>{eol}{inner}{ind}</{tag}>{eol}")
        else:
            val = str(rng.randint(0, 999)) if rng.random() < 0.85 else "  "
            parts.append(f"{ind}<{tag}>{val}</{tag}>{eol}")
    return "".join(parts)


def _gen_asset(rng):
    eol = rng.choice(["\r\n", "\n"])
    kids = _gen_tree(rng, 3, "    ", eol)
    return (f"<Asset>{eol}  <Template>HardCSP</Template>{eol}"
            f"  <Values>{eol}{kids}  </Values>{eol}"
            f"  <Standard>{eol}    <Name>X</Name>{eol}"
            f"    <GUID>1</GUID>{eol}  </Standard>{eol}"
            f"</Asset>{eol}"), eol


P = Profile("f", "X", "1", "HardCSP", 0, 0, 0, 0)


def _random_path(rng):
    return "/".join(rng.choice(PATH_TAGS)
                    for _ in range(rng.randint(1, 3)))


def _specs(rng, dials, k):
    """Candidate (path, value) edits: existing dials + random probes."""
    out = []
    keys = list(dials)
    rng.shuffle(keys)
    out.extend(keys[:k // 2])
    while len(out) < k:
        out.append(_random_path(rng))
    return [(p, str(rng.randint(0, 999))) for p in out]


class SpanPropertyTests(unittest.TestCase):
    """Fuzz invariants of set_dial / apply_changes over random trees."""

    N = 120

    def _check_edit(self, old, new, old_dials, path, val):
        # well-formed after the edit
        try:
            ET.fromstring(new)
        except ET.ParseError as e:
            self.fail(f"edit {path!r} broke XML: {e}\n---\n{new}")
        # byte identity outside the asset's <Values> span (re-locate in the
        # NEW text — the old offsets are stale after an insert)
        s, e = _locate_values(old, P)
        ns, ne = _locate_values(new, P)
        self.assertIsNotNone(ns, f"edit {path!r}: asset lost after edit")
        self.assertEqual(old[:s], new[:ns],
                         f"edit {path!r}: bytes before <Values> changed")
        self.assertEqual(old[e:], new[ne:],
                         f"edit {path!r}: bytes after <Values> changed")
        # oracle: exactly old dials + this change
        expected = dict(old_dials)
        expected[path] = str(val)
        got = dials_dict(new)
        self.assertEqual(got, expected,
                         f"edit {path!r}: dial oracle violated\n"
                         f"missing={ {k: expected[k] for k in expected if k not in got} }\n"
                         f"extra={ {k: got[k] for k in got if k not in expected} }")

    def test_random_single_edits(self):
        for seed in range(self.N):
            rng = random.Random(seed)
            txt, _ = _gen_asset(rng)
            dials = dials_dict(txt)
            for path, val in _specs(rng, dials, 6):
                with self.subTest(seed=seed, path=path):
                    try:
                        new = set_dial(txt, P, path, val)
                    except EditError:
                        continue     # refusal is legal on random probes
                    self._check_edit(txt, new, dials, path, val)

    def test_random_batches(self):
        for seed in range(self.N):
            rng = random.Random(1000 + seed)
            txt, _ = _gen_asset(rng)
            dials = dials_dict(txt)
            changes = dict(_specs(rng, dials, 4))
            new, applied, errors = apply_changes(txt, P, changes)
            self.assertTrue(set(applied) <= set(changes))
            self.assertTrue({p for p, _ in errors} <= set(changes))
            self.assertTrue(not (set(applied) & {p for p, _ in errors}))
            with self.subTest(seed=seed):
                try:
                    ET.fromstring(new)
                except ET.ParseError as e:
                    self.fail(f"batch {list(changes)} broke XML: {e}")
                s, e = _locate_values(txt, P)
                ns, ne = _locate_values(new, P)
                self.assertIsNotNone(ns)
                self.assertEqual(txt[:s], new[:ns])
                self.assertEqual(txt[e:], new[ne:])
                expected = dict(dials)
                for path in applied:
                    expected[path] = str(changes[path])
                self.assertEqual(dials_dict(new), expected,
                                 f"batch {list(changes)}: dial oracle violated")


if __name__ == "__main__":
    unittest.main()
