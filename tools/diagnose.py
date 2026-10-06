#!/usr/bin/env python3
"""diagnose — check the engine's assumptions against a real data1.rda.

Some properties of the game data can only be confirmed on a real archive
(which this project does not ship). Run this against your vanilla
addon/data1.rda and include the output with any bug report.

    python3 tools/diagnose.py /path/to/data1.rda

Checks:
  V1  Are Relations <ProfileGUID> values CSP GUIDs (1645xxx, the by_guid
      keys) rather than PlayerProfile GUIDs (1650xxx)? Relations edits
      write CSP GUIDs (see docs/technical/ai-profiles-anatomy.md).
  V2 How often does the wrong-depth trigger fire across KEY_DIALS and
      persona paths (chain missing at the right depth, present deeper)?
  V3  Do self-closed relation kinds (<Trade/>) or self-closed leaves exist
      in vanilla?
  V4  Does properties.xml have per-<Group> default blocks beyond
      <DefaultValues>? (parse_schema reads only DefaultValues — if
      templates have their own group defaults, every "effective value"
      for an omitted dial is wrong.)
  V5  Do several CSP assets share one <Name>? (by_name.setdefault keeps
      the first; persona targeting picks it silently.)
  V6  Do any data1.rda blocks use flag 4 (memory-resident) or flag 2
      (encrypted)? (The reader treats flag-4 offsets as absolute.)
  V7  Does zlib.compress on this machine reproduce the reference
      hardened-build md5? (zlib-ng / other zlib builds produce different
      compressed bytes; the content hash is zlib-independent.)
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from annoedit.core import ModProject  # noqa: E402
from annoedit.presets import KEY_DIALS  # noqa: E402


def hr(title):
    print(f"\n== {title} " + "=" * max(0, 66 - len(title)))


def v1_guid_class(proj):
    hr("V1 Relations GUID class (CSP 1645xxx vs PlayerProfile 1650xxx)")
    csp = set(proj.by_guid)
    # collect every <Asset> GUID whose <Template> is PlayerProfile
    player = set()
    for fk, text in proj.filetexts.items():
        for m in re.finditer(r"<Asset>(.*?)</Asset>", text, re.S):
            b = m.group(1)
            t = re.search(r"<Template>([^<]+)</Template>", b)
            g = re.search(r"<GUID>(-?\d+)</GUID>", b)
            if t and g and t.group(1) == "PlayerProfile":
                player.add(g.group(1))
    counts = {"csp": 0, "player": 0, "other": 0}
    examples = {"csp": [], "player": [], "other": []}
    for fk, text in proj.filetexts.items():
        for m in re.finditer(r"<ProfileGUID>(-?\d+)</ProfileGUID>", text):
            g = m.group(1)
            k = "csp" if g in csp else ("player" if g in player else "other")
            counts[k] += 1
            if len(examples[k]) < 5:
                examples[k].append(g)
    print(f"  CSP roster GUIDs: {len(csp)}; PlayerProfile GUIDs: {len(player)}")
    for k in ("csp", "player", "other"):
        print(f"  ProfileGUID values in {k}: {counts[k]}  e.g. {examples[k]}")
    if counts["player"]:
        print("  -> Relations reference PlayerProfile GUIDs: the code and the")
        print("personas must be retargeted.")
    else:
        print("-> Relations reference CSP GUIDs: the anatomy doc is wrong.")
    return counts


def _chain_depth_text(vtext, tags):
    """Child-axis walk of tags under the Values text: -> status string."""
    cur = vtext
    for i, tag in enumerate(tags):
        kids = list(re.finditer(r"<%s(\s[^>]*)?>(.*?)(</%s>|)" % (tag, tag),
                                cur, re.S))
        # count all-depth matches (descendant axis) for the trigger report
        if not kids:
            deeper = re.search(r"<%s(\s[^>]*)?>" % tag, cur, re.S)
            return (f"missing at depth {i} ({'/'.join(tags[:i + 1])})"
                    + ("BUT present deeper (TRIGGER)" if deeper else ""))
        # descend into the FIRST direct-child-shaped match
        m = re.search(r"<%s(\s[^>]*)?>(.*?)(</%s>|)" % (tag, tag), cur, re.S)
        cur = m.group(2)
    return "ok"


def v2_e1_triggers(proj):
    hr("V2 wrong-depth triggers across KEY_DIALS + persona paths")
    from annoedit.model import _locate_values
    paths = [p for p, _d in KEY_DIALS]
    # persona paths (repo presets)
    pdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "presets")
    if os.path.isdir(pdir):
        import json
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".json"):
                continue
            try:
                data = json.load(open(os.path.join(pdir, fn),
                                      encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for who, spec in (data.get("characters") or {}).items():
                for pth in ((spec or {}).get("dials") or {}):
                    if pth not in paths:
                        paths.append(pth)
    hits = 0
    checked = 0
    for fk, ps in proj.profiles.items():
        for p in ps:
            span = _locate_values(proj.filetexts[fk], p)
            if span is None:
                continue
            vtext = proj.filetexts[fk][span[0]:span[1]]
            for path in paths:
                checked += 1
                status = _chain_depth_text(vtext, path.split("/"))
                if "TRIGGER" in status:
                    hits += 1
                    if hits <= 8:
                        print(f"  {p.name} ({p.guid}) {path}: {status}")
    print(f"  checked {checked} profile x dial-path combinations: "
          f"{hits} wrong-depth triggers")


def v3_self_closed(proj):
    hr("V3 self-closed kinds / leaves in vanilla")
    for fk, text in proj.filetexts.items():
        kinds = re.findall(r"<(?:War|Ally|Trade|AvoidWar)\s*/>", text)
        if kinds:
            print(f"  {fk}: {len(kinds)} self-closed relation kinds")
        inner = 0
        for m in re.finditer(r"<Values>(.*?)</Values>", text, re.S):
            inner += len(re.findall(r"<(\w+)\s*/>", m.group(1)))
        if inner:
            print(f"  {fk}: {inner} self-closed leaves under <Values>")


def v4_group_defaults(proj):
    hr("V4 properties.xml structure (DefaultValues vs per-Group blocks)")
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(proj.schema_text)
    except Exception as e:
        print(f"  schema does not parse with ET: {e}")
        return
    def dump(el, depth=0, max_depth=3):
        if depth > max_depth:
            return
        for c in el:
            txt = (c.text or "").strip()
            if c.tag in ("DefaultValues", "Group", "Property"):
                print("  " + "  " * depth + f"<{c.tag}>"
                      + (f" ({txt[:30]})" if txt else ""))
                dump(c, depth + 1, max_depth)
            elif depth <= 1:
                print("  " + "  " * depth + f"<{c.tag}>"
                      + (f" = {txt[:40]}" if txt else "") + "  [top-level!]")
    dump(root)
    # any element other than DefaultValues carrying leaf values?
    for c in root:
        if c.tag == "DefaultValues":
            continue
        has_leaf = any((g.text or "").strip() for g in c.iter()
                       if len(list(g)) == 0 and g.text and g.text.strip())
        if has_leaf:
            print(f"  !! <{c.tag}> carries leaf values OUTSIDE DefaultValues")


def v5_duplicate_names(proj):
    hr("V5 duplicate CSP <Name>s (persona targeting picks first silently)")
    from collections import Counter
    names = Counter(p.name for ps in proj.profiles.values() for p in ps)
    dups = {n: c for n, c in names.items() if c > 1}
    if dups:
        for n, c in sorted(dups.items()):
            guids = [p.guid for ps in proj.profiles.values() for p in ps
                     if p.name == n]
            print(f"  {n!r}: {c} assets, GUIDs {guids}")
    else:
        print("  no duplicate CSP names")


def v6_block_flags(path):
    hr("V6 block flags (4 = memory-resident, 2 = encrypted)")
    import struct
    with open(path, "rb") as f:
        f.seek(36 + 1008)
        first = struct.unpack("<I", f.read(4))[0]
        fsize = os.path.getsize(path)
        off, seen = first, set()
        flag_counts = {}
        while off < fsize and off != 0 and off not in seen:
            seen.add(off)
            f.seek(off)
            flags, _count = struct.unpack("<II", f.read(8))
            flag_counts[flags] = flag_counts.get(flags, 0) + 1
            _ds, _dc, off = struct.unpack("<III", f.read(12))
        for flags, c in sorted(flag_counts.items()):
            names = []
            if flags & 1:
                names.append("compressed")
            if flags & 2:
                names.append("ENCRYPTED")
            if flags & 4:
                names.append("MEMORY-RESIDENT")
            print(f"  flags={flags} ({'+'.join(names) or 'plain'}): "
                  f"{c} blocks")


def v7_zlib_pin(proj, src):
    hr("V7 hardened-build md5 pin vs this machine's zlib")
    import hashlib
    from annoedit.core import hardened_build
    from annoedit.presets import HARD_GUIDS
    out = os.path.join(tempfile.mkdtemp(prefix="diagnose_"), "h.rda")
    rep, _ = hardened_build(src, out, exclude_guids=HARD_GUIDS)
    # Reference md5 of the hardened build on a stock-zlib machine.
    pin = "805c1bc9e8b7ccac5c6580e9f4e30d17"
    match = "MATCHES the pinned md5" if rep["md5"] == pin \
        else f"DIFFERS from the pinned {pin} (zlib-build dependent)"
    print(f"  hardened build md5: {rep['md5']}  -> {match}")
    # content hash (zlib-independent): md5 over sorted (name, data)
    from annoedit.rda import read_rda
    e = read_rda(out)
    h = hashlib.md5()
    for name in sorted(e):
        h.update(name.encode() + b"\x00" + e[name][0])
    print(f"  content hash (zlib-independent): {h.hexdigest()}")
    os.unlink(out)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    src = argv[1]
    if not os.path.isfile(src):
        print(f"error: no such archive: {src}", file=sys.stderr)
        return 2
    print(f"diagnose: {src} "
          f"(md5-checked, read-only — nothing is modified)")
    proj = ModProject(src)
    v1_guid_class(proj)
    v2_e1_triggers(proj)
    v3_self_closed(proj)
    v4_group_defaults(proj)
    v5_duplicate_names(proj)
    v6_block_flags(src)
    v7_zlib_pin(proj, src)
    print("\ndiagnose complete — paste this output back into the chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
