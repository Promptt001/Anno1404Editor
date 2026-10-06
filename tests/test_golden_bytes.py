#!/usr/bin/env python3
"""Golden bytes: the engine's output contract without game data.

Six canonical workflows (persona / hardened / vanilla-on-modded /
relations rewrite / extras incl. INSERT + multi-occurrence + ambiguous
name / fertility) are driven through the real Session stack on the
synthetic archive, and the four edited members' exact bytes are
compared against tests/golden_fixtures.json.

A mismatch means the change under test altered behaviour; it is not
merely a test to update. The failure prints the workflow, the member
and the first differing lines. Fix the engine or justify the change in
CHANGELOG.md, then re-record deliberately:

    python3 tests/golden_bytes.py record

Never re-record to turn a red build green without understanding why the
bytes moved.
"""
import difflib
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from golden_bytes import check, FIXTURES_PATH  # noqa: E402


class GoldenBytesTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.assertTrue(os.path.isfile(FIXTURES_PATH),
                        f"{FIXTURES_PATH} missing — record once via "
                        "'python3 tests/golden_bytes.py record'")

    def test_golden_bytes_unchanged(self):
        problems = check()
        if not problems:
            return
        # LOUD, actionable: name every problem, show the first byte diff.
        lines = ["GOLDEN BYTES CHANGED — this refactor changed emitted "
                 "bytes (behaviour), not just code:"]
        for p in problems:
            got, exp = p.get("got"), p.get("expected")
            if got is not None and exp is not None:
                gt = got.decode("latin-1").splitlines()
                et = exp.decode("latin-1").splitlines()
                diff = list(difflib.unified_diff(
                    et, gt, "fixture", "emitted now", n=1, lineterm=""))
                lines.append(f"  [{p['workflow']}/{p['member']}] {p['error']}")
                lines.extend("      " + d for d in diff[:24])
            else:
                lines.append(f"  [{p['workflow']}/{p['member']}] {p['error']}")
        lines.append(
            "  If the change is INTENDED: justify it in CHANGELOG.md, then "
            "re-record deliberately with 'python3 tests/golden_bytes.py "
            "record'. Never re-record just to go green.")
        self.fail("\n".join(lines))

    def test_fixtures_shape(self):
        """The fixture file is well-formed, carries all six workflows
        and all four members each (a truncated/corrupt fixture must
        fail here, not downstream as a confusing byte mismatch)."""
        import json
        with open(FIXTURES_PATH) as f:
            doc = json.load(f)
        self.assertIn("workflows", doc)
        for name in ("persona", "hardened", "vanilla_on_modded",
                     "relations", "extras", "fert"):
            self.assertIn(name, doc["workflows"], name)
            wf = doc["workflows"][name]
            self.assertIn("content_md5", wf, name)
            self.assertTrue(wf["members"], name)
            import base64
            for mkey, mem in wf["members"].items():
                # every recorded member must carry md5 + b64
                # (decodable round-trip) — a corrupt fixture fails HERE,
                # not downstream as a confusing byte mismatch
                self.assertIn("md5", mem, mkey)
                base64.b64decode(mem["b64"])


if __name__ == "__main__":
    unittest.main()
