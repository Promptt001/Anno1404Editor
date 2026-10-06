#!/usr/bin/env python3
"""gate_verify — the GUI-evidence gate for headless release cuts.

Verifies a results.json (written by tests/run_tests.py from a
--require-gui run) is valid EVIDENCE for cutting a release of the tree
at <root>:

  1. the file is well-formed JSON with the required fields;
  2. the recorded run was GREEN (ok=true) and no GUI test skipped
     (gui_required=true, gui_skips=0);
  3. the recorded tree_hash equals the CURRENT tree's content hash
     (tools/tree_hash.py) — evidence from a DIFFERENT tree (an old
     checkout, a partially edited tree) is not evidence.

Exit 0 = evidence accepted; exit 1 = refused (prints the reason).

    python3 tools/gate_verify.py <results.json> <repo-root>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tree_hash import tree_hash  # noqa: E402

REQUIRED = ("ok", "gui_required", "gui_skips", "ran",
            "failures", "errors", "tree_hash")


def verify(res_path, root):
    try:
        with open(res_path) as f:
            doc = json.load(f)
    except Exception as e:
        return f"results file unreadable/not JSON: {e}"
    for k in REQUIRED:
        if k not in doc:
            return f"results file missing key {k!r} — written by an " \
                   "older run_tests.py; re-run with --require-gui"
    if not doc.get("ok"):
        return (f"the recorded GUI run was NOT green "
                f"(failures={doc.get('failures')} errors={doc.get('errors')}"
                f") — fix and re-run before cutting a release")
    if not doc.get("gui_required"):
        return "the recorded run did not pass --require-gui — GUI skips " \
               "were not gated; re-run with --require-gui"
    if doc.get("gui_skips"):
        return (f"the recorded run skipped {doc['gui_skips']} GUI "
                "test(s) — need tkinter + a display (e.g. xvfb-run -a)")
    if doc.get("failures") or doc.get("errors"):
        return "the recorded run carried failures/errors"
    cur = tree_hash(root)
    if doc["tree_hash"] != cur:
        return ("the results file was recorded on a DIFFERENT tree "
                f"(hash {doc['tree_hash'][:12]}... vs this tree "
                f"{cur[:12]}...) — evidence from another tree is not "
                "evidence; re-run --require-gui from THIS tree")
    return None


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip())
        return 2
    res_path, root = argv[1], os.path.abspath(argv[2])
    reason = verify(res_path, root)
    if reason:
        print(f"FAIL: {reason}")
        return 1
    print(f"GUI evidence accepted ({res_path}, "
          f"tree {doc_hash(res_path)[:12]}...)")
    return 0


def doc_hash(res_path):
    with open(res_path) as f:
        return json.load(f)["tree_hash"]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
