#!/usr/bin/env python3
"""gen_glossary.py — generate docs/technical/dial_glossary.md from the game.

Reads the AI schema (addondata/config/ai/properties.xml) straight out of a
data1.rda using the package's own reader, extracts every ValueDefinition
(dial name, type, range, German description), and writes a grouped markdown
table. Deterministic: same archive -> byte-identical output.

Usage:
    python3 tools/gen_glossary.py <path/to/data1.rda> [output.md]

Regenerate-and-compare (the verification gate)
    python3 tools/gen_glossary.py data1.rda /tmp/g.md && \
    diff /tmp/g.md docs/technical/dial_glossary.md && echo STABLE
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from annoedit.model import SCHEMA_FILE, parse_schema  # noqa: E402

HEADER = """<!--
  GENERATED FILE — do not edit by hand.
  Regenerate with:
      python3 tools/gen_glossary.py <path/to/data1.rda> docs/technical/dial_glossary.md
  The definitions come from the game's own AI schema
  (addondata/config/ai/properties.xml); German descriptions are the
  developers' original text.
-->

# Dial glossary — every AI dial documented by the game itself

Every dial the game defines for AI character profiles, with its type, value
range, schema default, and the developers' (German) description. Grouped by
category. Paths shown as `Category/Dial` (nested: `Category/Sub/Dial`).
"""


def esc(s):
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def category_of(path):
    return path.split("/")[0] if "/" in path else "(root)"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rda = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "docs",
        "technical", "dial_glossary.md")

    from annoedit.rda import read_rda
    entries = read_rda(rda)
    if SCHEMA_FILE not in entries:
        print(f"error: {SCHEMA_FILE} not found in {rda}", file=sys.stderr)
        return 1
    text = entries[SCHEMA_FILE][0].decode("utf-8")
    ET.fromstring(text)   # hard fail on a broken schema
    docs, defaults = parse_schema(text)

    lines = [HEADER]
    lines.append(f"\nSource archive: a vanilla `addon/data1.rda` "
                 f"(local file: {os.path.basename(rda)})\n")
    lines.append(f"Dials documented: **{len(docs)} categories**, "
                 f"**{sum(len(v) for v in docs.values())} dials**.\n")

    for cat in sorted(docs):
        lines.append(f"\n## {cat}\n")
        lines.append("| Dial | Type | Range | Default | Description (German) |")
        lines.append("|---|---|---|---|---|")
        for leaf in sorted(docs[cat]):
            d = docs[cat][leaf]
            path = f"{cat}/{leaf}"
            rng = f"{esc(str(d.get('min', '')))}..{esc(str(d.get('max', '')))}"
            if rng == "..":
                rng = "—"
            lines.append(f"| `{path}` | {esc(d.get('type', ''))} | {rng} | "
                         f"{esc(str(defaults.get(path, '—')))} | "
                         f"{esc(d.get('desc', ''))} |")

    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    n = sum(len(v) for v in docs.values())
    print(f"wrote {out}: {len(docs)} categories, {n} dials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
