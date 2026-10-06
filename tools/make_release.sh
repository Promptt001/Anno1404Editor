#!/usr/bin/env bash
# make_release.sh — build the release zip (code + presets + docs, NO game data).
# Verifies the zip is self-contained: unpacks to a temp dir and runs the
# pure-logic tests + CLI smoke from inside the unpacked tree.
# Usage: tools/make_release.sh [version]   (default: from annoedit/__init__.py)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"   # absolute repo root (the cwd changes during the smoke)

# Configurable interpreter — on some boxes python3 (e.g. 3.13) lacks tk
# while python3.12 has it; ANN0140_PY selects the binary the gate uses.
PY="${ANN0140_PY:-python3}"

VERSION="${1:-$($PY -c "from annoedit import __version__; print(__version__)")}"
NAME="annoedit-$VERSION"
OUT="$NAME.zip"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME"
# (personas ship inside the package: annoedit/presets/)
for d in annoedit tools tests docs pyproject.toml; do
  cp -r "$d" "$STAGE/$NAME/$d"
done
find "$STAGE/$NAME" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
# The transient suite-results file never ships — it is per-run evidence
# for the gate, not part of the release.
rm -f "$STAGE/$NAME/tests/results.json"
rm -rf "$STAGE/$NAME"/.git*
cp README.md LICENSE CHANGELOG.md .gitignore "$STAGE/$NAME/"
if [ ! -f pyproject.toml ]; then
  echo "WARNING: no pyproject.toml to ship"
fi

(cd "$STAGE" && zip -qr "$OUT" "$NAME")
# STAGED zip (NOT yet the release artifact): a gate refusal must not
# leave a releasable zip behind — the artifact is promoted to $PWD only
# AFTER the smoke + gates pass. The staged copy also stays out of the
# tree hash (SKIP_SUFFIXES .zip).
SMOKE=$(mktemp -d)
trap 'rm -rf "$STAGE" "$SMOKE"' EXIT
unzip -q "$STAGE/$OUT" -d "$SMOKE"
cd "$SMOKE/$NAME"

# --- self-containment smoke: unpack and run the tests + CLI ----------------
# The GUI gate: cut a release ONLY after a GUI-capable run of THIS tree.
# When xvfb-run + tkinter are available the full suite (GUI classes
# included) runs here under xvfb with --require-gui, which FAILS if any
# GUI test skipped. On a headless box the release can ONLY be cut with
# EVIDENCE: ANN0140_GUI_RESULTS must point at a results.json written by
# a --require-gui run of the SAME tree (verified via the content tree
# hash — tools/tree_hash.py). There is deliberately no bare bypass.
# Flow on the gaming machine (or any display-capable box):
#   xvfb-run -a python3 tests/run_tests.py --require-gui
#   -> writes tests/results.json carrying this tree's hash
# then on this box:  ANN0140_GUI_RESULTS=<repo>/tests/results.json $0
if command -v xvfb-run >/dev/null 2>&1 && $PY -c "import tkinter" 2>/dev/null; then
    xvfb-run -a $PY tests/run_tests.py --require-gui
else
    # Headless box: the headless suite still runs (failures/errors can
    # never ship), and the GUI half must be covered by EVIDENCE from a
    # GUI-capable run of THIS SAME tree.
    if ! $PY tests/run_tests.py > "$SMOKE/suite.log" 2>&1; then
        echo "FAIL: test suite failed (a GUI-results excuse never covers failures/errors)."
        grep -E "^Ran |^OK|^FAILED|errors=[0-9]+|failures=[0-9]+" "$SMOKE/suite.log" || true
        tail -5 "$SMOKE/suite.log"
        exit 1
    fi
    grep -E "^Ran |^OK" "$SMOKE/suite.log" || true
    # NOTE: tests/results.json written by THAT headless run lives in the
    # SOURCE tree (repo/tests/results.json) — the results file this gate
    # verifies must come from a GUI run; verify it below.
    RES="${ANN0140_GUI_RESULTS:-}"
    if [ -z "$RES" ]; then
        RES="$PWD/results.json"   # legacy location convenience
    fi
    if [ ! -f "$RES" ]; then
        echo "FAIL: no GUI evidence — no xvfb-run + tkinter here, and ANN0140_GUI_RESULTS"
        echo "      is unset. Run the GUI suite on a display-capable box (e.g. the gaming"
        echo "      machine) from THE SAME TREE and point ANN0140_GUI_RESULTS at the"
        echo "      tests/results.json it writes."
        exit 1
    fi
    $PY tools/gate_verify.py "$RES" "$PWD" || exit 1
    echo "GUI gate: satisfied by evidence ($RES, same-tree --require-gui run)."
fi
$PY -m annoedit.cli --version
$PY -m annoedit.cli personas >/dev/null
$PY -m py_compile annoedit/gui/app.py annoedit/gui/editor.py
echo "zip smoke OK"

# All gates passed — promote the staged zip to the release artifact.
# Keep the newest two release zips (the new one + its immediate prior);
# older ones are removed. The `|| true` matters: with no earlier zip, ls
# fails and pipefail would otherwise abort the script right here.
{ ls -1v "$ROOT"/annoedit-*.zip 2>/dev/null || true; } \
    | { grep -vxF "$ROOT/$OUT" || true; } | head -n -1 | while read -r _old; do
    rm -f "$_old"
done
mv "$STAGE/$OUT" "$ROOT/$OUT"
echo
echo "release artifact: $ROOT/$OUT"
md5sum "$ROOT/$OUT"
sha256sum "$ROOT/$OUT"
