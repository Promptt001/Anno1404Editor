#!/usr/bin/env python3
"""extras — global economy/military dials in assets.xml.

- EXTRAS are global and independent of AI presets: they are applied to the
  archive alongside whatever AI preset is active. assets.xml has no owner
  flag, so every change applies to the human player and the AI alike.
- Identity follows the aiprofiles shape: <Asset><Template>...<Values>...
  with <Standard><Name>/<GUID> at the asset tail. A tag that occurs several
  times in one asset (e.g. noria radii per ground state) is addressed as
  (asset, tag, occurrence index in file order). Edits rewrite the chosen
  occurrence and never insert a duplicate.
- Inserting a missing tag is only allowed for (tag, asset) pairs with a
  known-good shape (INSERT_ALLOWED / INSERT_PARENT below).
- Values are numbers only; '<', '>' and '&' are refused.

Families (EXTRA_FAMILIES): production, influence, housing, noria, trade,
speed, military, costs.
"""
import re

ASSETS_FILE = "addondata/config/game/assets.xml"

# section -> {tag: help text}. Dict order is the GUI order.
EXTRA_FAMILIES = {
    "production": {
        "ProductionTime": "Production rate (ms per ton; 1000 ms = 60 t/min). "
                          "4 buildings (PrintingHouse, DateGrove, SilkWeavingMill, "
                          "Papermill) lack a vanilla tag: dial INSERTS it.",
    },
    "influence": {
        "InfluenceRadius": "Area of influence radius (need satisfaction, "
                            "market coverage, military towers).",
    },
    "housing": {
        "MaxResidentCount": "Residents per house.",
    },
    "noria": {
        "NoriaTicksPerObject": "Ticks per object (water consumption rhythm).",
        "NoriaRefillCost": "Coin cost to refill a dry noria.",
        "NoriaStartRadius": "Water coverage start radius (per-level, multi-instance).",
        "NoriaEndRadius": "Water coverage end radius (per-level, multi-instance).",
        "NoriaGrowTimePerTile": "Time per tile for the water to spread (per-level).",
        "ProductionCapacity": "On norias: water storage capacity. On monuments: "
                              "monument-internal capacity (leave those alone).",
    },
    # Trade / logistics
    "trade": {
        "PassiveTradeSlots": "Passive trade slots per warehouse (Warehouse01/02/03 "
                             "4/6/8; NOTE Oriental_Warehouse appears as TWO assets "
                             "— select by GUID in the catalog: 35344 has 8, 204391 "
                             "has 6).",
        "Capacity": "Storage capacity (warehouses, markethouses, depot).",
        "SlotCount": "Transport unit load slots (carts 1, caravan 4, ships 2-6).",
        "TradeCooldown": "Orient trader cooldown (ms) at Caravanserai/"
                         "MountainMonastery (vanilla 300000 = 5 min).",
    },
    "speed": {
        "WalkingSpeed": "Unit walking speed (cart/worker/military march speed — "
                        "chain throughput multiplier). Also ships' speed values "
                        "are separate (search ships under this tag).",
    },
    # Military / costs (DPS values are /4096 fixed point: 24576 = 6.0)
    "military": {
        "DamagePerSecond": "Ship damage per second, fixed point /4096 "
                           "(Small 24576=6.0, Large 57344=14.0, Orient 40960=10.0). "
                           "GlobalEnemy* assets = difficulty-bound enemies (two "
                           "GUIDs per name — pick by GUID).",
        "RepairBuildingsPointsPerMinute": "Repair rate (RepairDock 300).",
        "RepairRadius": "Repair coverage radius (only RepairDock is nonzero vanilla).",
    },
    "costs": {
        "MoneyCost": "Coin maintenance per interval (220 assets — largest scope).",
        "ActiveCost": "Maintenance while active (190 assets).",
        "InactiveCost": "Maintenance while inactive (121 assets).",
        "HonorCost": "Honour maintenance (84 assets).",
    },
}


class ExtrasError(Exception):
    """Raised on invalid extras specs or ambiguous asset references."""



# ---------------------------------------------------------------- parsing

_TAG_RE = re.compile(r"<([A-Za-z_][A-Za-z_0-9]*)>")

# Per-text parse cache: {id(text): (hash(text), text, parsed-list)}.
# ModProject replaces the text object on every edit (strings are never
# mutated), so object identity implies freshness. Capped at 8 entries so a
# long GUI session does not accumulate one entry per edit.
_PARSE_CACHE = {}


def parse_assets(text):
    """assets.xml text -> [(name, template, start, end)], Asset spans in file.
    Identity = <Standard><Name> at the asset TAIL (same shape as aiprofiles).

    The scan runs on comment-masked text, so a commented-out <Asset> is
    never treated as a real one (spans are valid on the raw text).

    Cached by text identity: the full-file scan of the ~9 MB assets.xml
    is the most expensive step in the EXTRAS pipeline. Callers must never
    mutate the returned list or the dicts inside it."""
    cached = _PARSE_CACHE.get(id(text))
    if cached is not None and cached[0] == hash(text) \
            and cached[1] is text:
        return cached[2]
    from .model import mask_markup_comments
    out = []
    mtext = mask_markup_comments(text)
    for m in re.finditer(r"<Asset>(.*?)</Asset>", mtext, re.S):
        block = m.group(1)
        im = re.search(r"<Standard>\s*<Name>([^<]+)</Name>(\s*<GUID>(-?\d+)</GUID>)?", block)
        if not im:
            continue
        tp = re.search(r"<Template>([^<]+)</Template>", block)
        out.append({"name": im.group(1).strip(), "template": tp.group(1) if tp else "?",
                    "guid": im.group(3),
                    "start": m.start(), "end": m.end()})
    if len(_PARSE_CACHE) > 8:
        _PARSE_CACHE.clear()
    _PARSE_CACHE[id(text)] = (hash(text), text, out)
    return out


def asset_text(text, asset):
    """Raw text of one asset's span, sliced from the full file text."""
    return text[asset["start"]:asset["end"]]


# A tag must be a plain XML name before it is ever interpolated into a
# regex or into XML text.
_TAG_NAME_RE = __import__("re").compile(r"[A-Za-z_][A-Za-z_0-9]*")


# Insert allow-list: (tag, asset name) pairs with a known-good insert shape.
# Only ProductionTime on the four buildings that lack it in vanilla is
# allowed. Everything else is refused; e.g. inserting <DamagePerSecond>
# into Bakery is exactly the kind of corruption this table prevents.
# Widen it only together with a verified shape.
INSERT_ALLOWED = frozenset({
    ("ProductionTime", "PrintingHouse"),
    ("ProductionTime", "DateGrove"),
    ("ProductionTime", "SilkWeavingMill"),
    ("ProductionTime", "Papermill"),
})

# Where an inserted tag must go. ProductionTime lives in
# Values/WareProduction (71 of 80 vanilla instances; the rest are in
# ShipProduction/Assortment/Item), never directly under <Values>, where the
# game would ignore it. Vanilla shape (Bakery, Apiary, ...): first child of
# <WareProduction>, before <Product>, at the sibling indent.
INSERT_PARENT = {
    "ProductionTime": "WareProduction",
}


class _OccMatch:
    """re.Match-shaped shim over one span-indexed value leaf — extras.py
    callers use only .start()/.end()/.group(1)."""

    __slots__ = ("_s", "_e", "_val")

    def __init__(self, text, node):
        self._s = node.open_start
        self._e = node.close_end
        self._val = text[node.open_end:node.close_start]

    def start(self):
        return self._s

    def end(self):
        return self._e

    def group(self, n=0):
        return self._val if n == 1 else None


def occurrences(block_text, tag):
    """All value-leaf occurrences of <tag>val</tag> inside one asset block,
    in file order: a pre-order walk of the span index, collecting every
    node named <tag> with no element children (at any depth). Because it
    is structure-derived, a match inside a comment, CDATA or attribute
    value is impossible. The catalog and the editor share this function,
    so their numbering can never drift apart. A malformed block
    (SpanError) falls back to a regex scan over comment-masked text."""
    try:
        from .spans import SpanError, index as _span_index
        root = _span_index(block_text)
        out = []

        def walk(n):
            for c in n.children:
                if c.tag == tag and not c.self_closed and not c.children:
                    out.append(_OccMatch(block_text, c))
                if c.children:
                    walk(c)

        walk(root)
        return out
    except SpanError:
        # The fallback also masks comments.
        from .model import mask_markup_comments
        m = mask_markup_comments(block_text)
        return list(re.finditer(rf"<{tag}>([^<>]*)</{tag}>", m))


def parent_paths(block_text, tag):
    """Distinct parent element PATHS of the tag's occurrences in one
    asset block (child-axis walk, same order as occurrences()).

    Multi-instance tags can live under different parents: e.g. noria
    Start/EndRadius and GrowTimePerTile exist once per ground state
    (Green/Moisture/Saturated). The catalog and edit prompts show these
    parent paths so the user edits the intended one.
    -> [path str] in file order (may repeat).
    """
    try:
        from .spans import SpanError, index as _span_index
        root = _span_index(block_text)
        out = []

        def walk(n, path):
            for c in n.children:
                if c.tag == tag and not c.self_closed and not c.children:
                    out.append('/'.join(path))
                if c.children:
                    walk(c, path + [c.tag])

        walk(root, ['Asset'])
        return out
    except SpanError:
        return []


def find_asset(assets, name):
    """Locate one asset by name, or by 'Name [GUID]' when the name is
    ambiguous (vanilla assets.xml has 17 duplicate-name pairs, e.g.
    Oriental_Warehouse GUID 35344 has 8 passive trade slots, GUID 204391
    has 6)."""
    m = re.match(r"^(.*?)\s*\[(-?\d+)\]$", name)
    base, guid = (m.group(1).strip(), m.group(2)) if m else (name, None)
    hits = [a for a in assets if a["name"] == base
            and (guid is None or str(a.get("guid")) == guid)]
    if len(hits) != 1:
        hint = "" if m else " — ambiguous name, use 'Name [GUID]'"
        raise ExtrasError(f"asset {name!r}: {len(hits)} matches (need exactly 1{hint})")
    return hits[0]


def display_names(assets):
    """-> {id(asset) -> display name}. Names carried by 2+ assets (17 pairs
    in vanilla) get the 'Name [GUID]' suffix on EVERY copy, so both are
    listed in the catalog and addressable by set_extra/find_asset.
    Keyed by id(asset), not by name: a name-keyed dict would collapse the
    two copies onto one key and hide one of them."""
    from collections import Counter
    counts = Counter(a["name"] for a in assets)
    return {id(a): (f"{a['name']} [{a['guid']}]") if counts[a["name"]] > 1
            else a["name"] for a in assets}


def extra_values(text, assets, tag):
    """-> {display name: [vanilla values, file order]} for all assets carrying
    the tag. Dup-name assets are keyed 'Name [GUID]' (both copies listed)."""
    disp = display_names(assets)
    out = {}
    for a in assets:
        vals = [m.group(1) for m in occurrences(asset_text(text, a), tag)]
        if vals:
            out[disp[id(a)]] = vals
    return out


# ---------------------------------------------------------------- edit engine

def set_extra(text, asset_name, tag, value, occ=None):
    """Byte-safe edit of one extras leaf. `occ` = 0-based occurrence index
    in file order when the asset carries the tag several times (e.g. noria
    EndRadius); that occurrence is rewritten, never duplicated.
    Returns (new_text, old_value); old_value is None for an insert.
    Raises ExtrasError on: unknown asset, zero occurrences with occ>0,
    any duplicates when occ unspecified, XML-special value."""
    sval = str(value)
    if any(ch in sval for ch in "<>&"):
        raise ExtrasError(f"value {sval!r} contains an XML-special character — refused")
    if not _TAG_NAME_RE.fullmatch(tag):
        raise ExtrasError(f"tag {tag!r} is not a valid XML name")
    assets = parse_assets(text)
    a = find_asset(assets, asset_name)
    block = asset_text(text, a)
    ms = occurrences(block, tag)
    if not ms:
        # Insert a new leaf: only allow-listed (tag, asset) pairs.
        if (tag, a["name"]) not in INSERT_ALLOWED:
            raise ExtrasError(
                f"insert of {tag!r} into {a['name']!r} is not allow-listed "
                "(only proven insert shapes — e.g. ProductionTime on "
                "PrintingHouse/DateGrove/SilkWeavingMill/Papermill)")
        # Insert as the first child of the recorded parent block
        # (ProductionTime -> <WareProduction>), at the sibling indent.
        parent_tag = INSERT_PARENT.get(tag)
        if parent_tag is None:
            raise ExtrasError(
                f"insert of {tag!r}: no proven parent block recorded in "
                "INSERT_PARENT — refusing")
        # Locate the parent on masked text so a commented-out
        # <WareProduction> can never receive the insert.
        from .model import mask_markup_comments
        mblock = mask_markup_comments(block)
        pm = re.search(rf"<{parent_tag}>", mblock)
        if not pm:
            raise ExtrasError(
                f"{asset_name}: no <{parent_tag}> block — cannot insert "
                f"{tag} at its proven location")
        # Reuse exactly the separator between the parent's opening tag and
        # its first child (EOL + indent in real data), so the inserted leaf
        # mirrors its siblings and the old first child keeps its own.
        cm = re.search(rf"<{parent_tag}>([ \t]*\r?\n[ \t]*)<", block[pm.start():])
        sep = cm.group(1) if cm else ""
        leaf = f"{sep}<{tag}>{sval}</{tag}>"
        new_block = block[:pm.end()] + leaf + block[pm.end():]
        new_text = text[:a["start"]] + new_block + text[a["end"]:]
        return new_text, None
    if occ is None:
        if len(ms) != 1:
            raise ExtrasError(f"{asset_name}/{tag}: {len(ms)} occurrences — "
                              "specify occ (multi-instance tag)")
        occ = 0
    elif not isinstance(occ, int) or isinstance(occ, bool):
        raise ExtrasError(f"{asset_name}/{tag}: occ {occ!r} is not an "
                          "integer index")
    elif occ < 0:
        raise ExtrasError(f"{asset_name}/{tag}: occurrence {occ} is "
                          "negative — occurrences are 0-based file-order "
                          "indices")
    elif occ >= len(ms):
        raise ExtrasError(f"{asset_name}/{tag}: occurrence {occ} out of range "
                          f"(asset has {len(ms)})")
    m = ms[occ]
    abs_start = a["start"] + m.start()
    abs_end = a["start"] + m.end()
    new_text = text[:abs_start] + f"<{tag}>{sval}</{tag}>" + text[abs_end:]
    return new_text, m.group(1)


def set_extras(text, edits):
    """Apply MANY extras edits to `text` in ONE pass.

    edits = [{asset, tag, value, occ}, ...] (occ optional, the
    set_extra semantics). Every splice position is computed on the
    original text and applied in descending position order in a single
    pass, which is byte-identical to calling set_extra per edit as long
    as the edits touch disjoint leaves (ChangeSet keys are unique, so
    they always do).

    -> (new_text, results) where results[i] is the OLD value of
    edits[i] (None for INSERTs), aligned with the input order.
    """
    from .model import mask_markup_comments
    assets = parse_assets(text)
    plan = []          # (abs_start, abs_end, replacement)
    results = [None] * len(edits)
    for i, ed in enumerate(edits):
        asset_name = ed['asset']
        tag = ed['tag']
        sval = str(ed['value'])
        occ = ed.get('occ')
        if any(ch in sval for ch in '<>&'):
            raise ExtrasError(
                'value %r contains an XML-special character — refused' % sval)
        if not _TAG_NAME_RE.fullmatch(tag):
            raise ExtrasError('tag %r is not a valid XML name' % tag)
        a = find_asset(assets, asset_name)
        block = asset_text(text, a)
        ms = occurrences(block, tag)
        if not ms:
            if (tag, a['name']) not in INSERT_ALLOWED:
                raise ExtrasError(
                    'insert of %r into %r is not allow-listed'
                    % (tag, a['name']))
            parent_tag = INSERT_PARENT.get(tag)
            if parent_tag is None:
                raise ExtrasError(
                    'insert of %r: no proven parent block recorded in'
                    ' INSERT_PARENT — refusing' % tag)
            mblock = mask_markup_comments(block)
            pm = re.search(rf'<{parent_tag}>', mblock)
            if not pm:
                raise ExtrasError(
                    '%s: no <%s> block — cannot insert at the proven'
                    ' location' % (asset_name, parent_tag))
            cm = re.search(rf'<{parent_tag}>([ \t]*\r?\n[ \t]*)<',
                           block[pm.start():])
            sep = cm.group(1) if cm else ''
            pos = a['start'] + pm.end()
            plan.append((pos, pos, '%s<%s>%s</%s>'
                         % (sep, tag, sval, tag)))
            continue
        if occ is None:
            if len(ms) != 1:
                raise ExtrasError(
                    '%s/%s: %d occurrences — specify occ'
                    % (asset_name, tag, len(ms)))
            occ = 0
        elif not isinstance(occ, int) or isinstance(occ, bool):
            raise ExtrasError(
                '%s/%s: occ %r is not an integer index'
                % (asset_name, tag, occ))
        elif occ < 0:
            raise ExtrasError(
                '%s/%s: occurrence %d is negative'
                % (asset_name, tag, occ))
        elif occ >= len(ms):
            raise ExtrasError(
                '%s/%s: occurrence %d out of range (asset has %d)'
                % (asset_name, tag, occ, len(ms)))
        m = ms[occ]
        plan.append((a['start'] + m.start(), a['start'] + m.end(),
                     '<%s>%s</%s>' % (tag, sval, tag)))
        results[i] = m.group(1)
    for abs_start, abs_end, repl in sorted(plan, key=lambda t: t[0],
                                           reverse=True):
        text = text[:abs_start] + repl + text[abs_end:]
    return text, results
