#!/usr/bin/env python3
"""tree_hash — stable content hash over the RELEASE TREE.

Hashes every file that ships in a release zip (annoedit/, tools/, tests/,
docs/ + the root files), over file CONTENT — never mtimes or inode order.
Two trees hash equal iff their release content is identical, so a test
RESULTS FILE recorded on one tree can be verified against another tree
(bit-for-bit reproducible; independent of permissions/umask).

Used by tests/run_tests.py (records the hash next to the results) and
tools/make_release.sh (the release-bypass gate: a GUI-suite bypass must
point at a results file from THIS exact tree).

    python3 tools/tree_hash.py [root]     # default: the repo root
"""
import hashlib
import os
import sys

ROOT_DIRS = ("annoedit", "tools", "tests", "docs")
ROOT_FILES = ("pyproject.toml", "README.md", "LICENSE",
              "CHANGELOG.md", ".gitignore")
SKIP_DIRS = {"__pycache__", ".git", "build", "annoedit.egg-info"}
# Scratch artefacts that never ship (the zip-cleanliness check is
# separate; the hash must be stable even when scratch exists).
SKIP_SUFFIXES = (".pyc", ".rda", ".md5", ".zip", ".log")
# Per-run suite output — NOT release content; hashing it would make the
# tree hash depend on whether a previous run left its results behind.
SKIP_NAMES = {"results.json"}


def _release_files(root):
    out = []
    for d in ROOT_DIRS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = sorted(n for n in dns if n not in SKIP_DIRS)
            for fn in fns:
                if fn.endswith(SKIP_SUFFIXES) or fn in SKIP_NAMES:
                    continue
                out.append(os.path.relpath(os.path.join(dp, fn), root)
                           .replace(os.sep, "/"))
    for f in ROOT_FILES:
        if os.path.isfile(os.path.join(root, f)):
            out.append(f)
    return sorted(out)


def tree_hash(root):
    """sha256 over the sorted (relpath, file-sha256) pairs of the
    release file set. Empty string when the root carries none of it."""
    h = hashlib.sha256()
    for rel in _release_files(root):
        with open(os.path.join(root, rel), "rb") as f:
            fh = hashlib.sha256(f.read()).hexdigest()
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(fh.encode("ascii"))
    return h.hexdigest()


def repo_root():
    """The repo root for THIS checkout (parent of tools/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


if __name__ == "__main__":
    print(tree_hash(sys.argv[1] if len(sys.argv) > 1 else repo_root()))
