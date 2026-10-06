#!/usr/bin/env bash
# smoke.sh — full user workflow, headless, on a COPY of the archive.
# Verifies the CLI path end-to-end without touching a real game file.
# Usage: tools/smoke.sh [path/to/data1.rda]
set -euo pipefail
cd "$(dirname "$0")/.."

RDA="${1:-${ANN0140_TEST_RDA:-}}"
[ -n "$RDA" ] && [ -f "$RDA" ] || { echo "no test archive (pass a path or set ANN0140_TEST_RDA)"; exit 1; }

TMP=$(mktemp -d)
export ANN0140_SMOKE_HOME="$TMP/home"
mkdir -p "$ANN0140_SMOKE_HOME"
# Redirect both: ANN0140_HOME takes precedence over HOME, so a stray
# exported ANN0140_HOME would otherwise write into the real store.
export HOME="$ANN0140_SMOKE_HOME"
export ANN0140_HOME="$ANN0140_SMOKE_HOME"
trap 'rm -rf "$TMP"' EXIT

cp "$RDA" "$TMP/data1.rda"
ORIG_MD5=$(md5sum "$TMP/data1.rda" | cut -d' ' -f1)
echo "== personas =="
${PYTHON:-python3} -m annoedit.cli personas

echo "== list =="
${PYTHON:-python3} -m annoedit.cli list "$TMP/data1.rda" | head -4

echo "== dial lookup =="
${PYTHON:-python3} -m annoedit.cli dial "$TMP/data1.rda" Leif Military/MaxUnitCount

echo "== apply (dry run) =="
${PYTHON:-python3} -m annoedit.cli apply "$TMP/data1.rda" "$TMP/out.rda" \
    --persona "The Admiral" --char Leif --dry-run | head -8

echo "== flash in place =="
${PYTHON:-python3} -m annoedit.cli flash "$TMP/data1.rda" \
    --persona "The Admiral" --char Leif
FLASH_MD5=$(md5sum "$TMP/data1.rda" | cut -d' ' -f1)
[ "$ORIG_MD5" != "$FLASH_MD5" ] || { echo "FAIL: flash did not change the archive"; exit 1; }

echo "== backup manifest =="
ls "$ANN0140_SMOKE_HOME/backups" | sort | head -5

echo "== restore vanilla =="
${PYTHON:-python3} -m annoedit.cli restore "$TMP/data1.rda"
RESTORED_MD5=$(md5sum "$TMP/data1.rda" | cut -d' ' -f1)
[ "$ORIG_MD5" = "$RESTORED_MD5" ] || { echo "FAIL: restore did not return vanilla"; exit 1; }

echo
echo "SMOKE OK — flash + restore round trip verified (md5 $RESTORED_MD5)"
