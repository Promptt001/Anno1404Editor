#!/usr/bin/env python3
"""model — parse aiprofiles assets into (profile, dials) and edit them byte-safely.

Design grounded in verified data facts:
- CSP assets live in addondata/config/ai/aiprofiles.xml (74 assets) and
  addondata/config/balancing/addon_01_aiprofiles.xml (7 assets, Venice chars).
- Identity = <Standard><Name>/<GUID> at the asset TAIL; <Asset><Template> at head.
- A profile's dials = leaf tags with text values under <Values>, in categories
  (Build, Military, ShipFight, Diplomacy, Espionage, TownAcquisition, Trade,
  Relationships, Reputation, ItemUsage, ...).
- Schema docs + defaults come from addondata/config/ai/properties.xml:
  <Property><Name>Military>...<ValueDefinition>... and <DefaultValues>.
- The core rule: a profile may OMIT a dial the schema defines, in which case
  the game falls back to the DefaultValues entry. Inserting a tag the asset
  already has would create a duplicate and an ambiguous engine read, so the
  edit engine only ever rewrites an existing leaf or inserts a leaf the asset
  lacks (a schema-legal override). Ambiguity is always an error.
"""
import re
import xml.etree.ElementTree as ET

from .i18n import translate

PROFILE_FILES = {
    "aiprofiles.xml": "addondata/config/ai/aiprofiles.xml",
    "addon_01_aiprofiles.xml": "addondata/config/balancing/addon_01_aiprofiles.xml",
}
SCHEMA_FILE = "addondata/config/ai/properties.xml"

CSP_TEMPLATES = {"EasyCSP", "MediumCSP", "HardCSP"}


class EditError(Exception):
    """Raised on uneditable or ambiguous dial paths and XML-unsafe values."""



def mask_markup_comments(text):
    """Mask <!-- comments -->, <![CDATA[...]]> and <?processing?> spans
    with same-length filler so the identity regexes are blind to markup a
    real XML reader never sees. Modded files often contain commented-out
    copies of a character; without masking, an edit could land inside
    the comment and be a silent no-op in game.

    Offsets are preserved exactly, so every span computed on the masked
    text is valid on the raw text. Pure function.
    """
    out = None
    i, n = 0, len(text)
    while i < n:
        c = text.find("<", i)
        if c < 0:
            break
        if text.startswith("<!--", c):
            e = text.find("-->", c + 4)
            e = (n if e < 0 else e + 3)
        elif text.startswith("<![CDATA[", c):
            e = text.find("]]>", c + 9)
            e = (n if e < 0 else e + 3)
        elif text.startswith("<?", c):
            e = text.find("?>", c + 2)
            e = (n if e < 0 else e + 2)
        else:
            i = c + 1
            continue
        if out is None:
            out = list(text)
        # 'x' never appears in the identity tags (<Asset>, <Name>...);
        # the filler keeps tag-name regexes from matching inside
        # masked spans.
        out[c:e] = "x" * (e - c)
        i = e
    return text if out is None else "".join(out)


class _InsertChainHere:
    """Sentinel meaning "this chain link is missing here; insert the
    remaining sub-chain at this level". It is a dedicated object checked
    by identity so it can never be confused with a real dial value."""
    __slots__ = ()


INSERT_CHAIN = _InsertChainHere()


class Profile:
    """One CSP asset: identity fields plus span offsets into its file's text.

    start/end = full <Asset>...</Asset> span; values_start/values_end = the
    <Values>...</Values> span, both offsets into the CURRENT file text."""

    def __init__(self, filekey, name, guid, template, start, end, values_start, values_end):
        self.filekey = filekey
        self.name = name
        self.guid = guid
        self.template = template
        self.start, self.end = start, end            # span in full file text
        self.values_start, self.values_end = values_start, values_end

    def __repr__(self):
        return f"<Profile {self.name!r} {self.template} {self.guid} ({self.filekey})>"


# ---------------------------------------------------------------- parsing

def parse_profiles(filekey, text):
    """Split file text into Profile objects (CSP assets only).

    The <Asset> scan runs on comment-masked text, so a commented-out copy
    of a character never shows up as a second profile. Spans are valid on
    the raw text (masking preserves length). Two live assets with the same
    Name+GUID raise EditError."""
    out = []
    seen = {}
    mtext = mask_markup_comments(text)
    for m in re.finditer(r"<Asset>(.*?)</Asset>", mtext, re.S):
        block = m.group(1)
        tm = re.search(r"<Template>([^<]+)</Template>", block)
        if not tm or tm.group(1) not in CSP_TEMPLATES:
            continue
        template = tm.group(1)
        ident = re.search(r"<Standard>\s*<Name>([^<]+)</Name>\s*<GUID>(-?\d+)</GUID>", block)
        if not ident:
            continue
        vm = re.search(r"<Values>.*?</Values>", block, re.S)
        if not vm:
            continue
        base = m.start(1)
        key = (ident.group(1).strip(), ident.group(2))
        if key in seen:
            raise EditError(
                f"duplicate profile identity {key[0]!r} ({key[1]}) in "
                "{fk} — two assets carry the same Name+GUID; refusing to "
                "guess which one the game reads".format(fk=filekey))
        seen[key] = True
        out.append(Profile(filekey, ident.group(1).strip(), ident.group(2), template,
                            m.start(), m.end(), base + vm.start(), base + vm.end()))
    return out


# List structure, never dials. Item/Profiles are list members even when only
# one sibling exists (a one-item list would otherwise look like a scalar
# dial). Everything under <Relations> is relation data (see set_relations).
_LIST_STRUCTURE_TAGS = frozenset(("Item", "Profiles"))


def _walk_leaves(el, path, out):
    kids = list(el)
    if not kids:
        if el.text and el.text.strip():
            out["/".join(path)] = el.text.strip()
        return
    if "Relations" in path or el.tag in _LIST_STRUCTURE_TAGS:
        return  # list structure, not a simple dial
    counts = {}
    for c in kids:
        counts[c.tag] = counts.get(c.tag, 0) + 1
    for c in kids:
        if counts[c.tag] > 1:
            continue  # list member (Items etc.) — not a simple dial
        _walk_leaves(c, path + [c.tag], out)


def dials_dict(asset_text):
    """-> {'ShipFight/ShipAttackIntervall': '60000', ...} for one <Asset> block."""
    root = ET.fromstring(asset_text)
    values = root.find("Values")
    out = {}
    if values is not None:
        _walk_leaves(values, [], out)
    return out


def parse_schema(schema_text):
    """-> (docs, defaults)
    docs: {'Military': {'MaxUnitCount': {...},
                        'Diplomacy': {'CompetenceUsageRanges/Min': {...}, ...}}}
    Nested ValueDefinitions are walked RECURSIVELY carrying the full path
    (both shapes: direct nested <ValueDefinition> children AND <Items><
    ValueDefinition> — the real properties.xml nests via <Items>). A leaf
    name is added as a SHORT ALIAS only when it is UNIQUE in its category,
    so simple lookups keep working while nested dials can never inherit
    another dial's doc/range (DeclareWar/Min must not get OfferPeace/Min's
    0..5 range).
    defaults: {'Military/MaxUnitCount': '70', ...} (leaf path -> value)"""
    docs, defaults = {}, {}
    root = ET.fromstring(schema_text)
    dv = root.find("DefaultValues")
    if dv is not None:
        for cat in dv:
            _walk_leaves(cat, [cat.tag], defaults)
    # properties.xml also carries <DefaultContainerValues> (53 scalar leaves
    # in vanilla). Without them ~139 profile dial paths would have no schema
    # default. Merge them as a fallback layer: an explicit DefaultValues
    # entry always wins.
    dcv = root.find("DefaultContainerValues")
    if dcv is not None:
        for cat in dcv:
            layer = {}
            _walk_leaves(cat, [cat.tag], layer)
            for path, val in layer.items():
                defaults.setdefault(path, val)
    for prop in root.iter("Property"):
        cat = (prop.findtext("Name") or "").strip()
        if not cat:
            continue
        d = {}
        _walk_vds(prop, [], d)
        # Unique-leaf alias: a leaf name that occurs exactly once in this
        # category also answers to its bare name; duplicated leaf names
        # (nested Min/Max) answer only to the full path.
        leaf_count = {}
        for p in d:
            leaf_count[p.rsplit("/", 1)[-1]] = \
                leaf_count.get(p.rsplit("/", 1)[-1], 0) + 1
        for p in list(d):
            leaf = p.rsplit("/", 1)[-1]
            if leaf != p and leaf_count[leaf] == 1:
                d.setdefault(leaf, d[p])
        if d:
            docs[cat] = d
    return docs, defaults


def _walk_vds(vd, path, out):
    """Recursive ValueDefinition walk carrying the path.
    Handles both nesting shapes: a <ValueDefinition> directly inside another
    one, and <Items><ValueDefinition> (the real properties.xml shape)."""
    subs = [c for c in vd if c.tag == "ValueDefinition"]
    items = vd.find("Items")
    if items is not None:
        subs += [c for c in items if c.tag == "ValueDefinition"]
    for s in subs:
        nm = (s.findtext("Name") or "").strip()
        if nm:
            _walk_vds(s, path + [nm], out)
    if not subs and path:
        entry = {"type": (vd.findtext("DataType") or "").strip(),
                 # English display translation of the German original:
                 "desc": translate((vd.findtext("Description") or "").strip())}
        for bound in ("Min", "Max"):
            b = vd.findtext(bound)
            if b is not None and b.strip():
                entry[bound.lower()] = b.strip()
        # Enumerated types name a <DataSet>; the allowed values are that
        # DataSet's <Item> list in config/game/datasets.xml (e.g. Choice
        # MaxCivilizationLevel -> ResidentLevel -> Outlaw..Nobleman;
        # Flags TreatyForIsCrazy -> Treaty -> None/War/...).
        ds = vd.findtext("DataSet")
        if ds and ds.strip():
            entry["dataset"] = ds.strip()
        out["/".join(path)] = entry


def schema_doc(docs, path):
    """Doc entry for a full dial path: exact sub-path first, then the
    unique-leaf alias, else {}. A nested dial never inherits another
    dial's doc/range."""
    parts = path.split("/")
    if len(parts) < 2:
        return {}
    cat, rest = parts[0], parts[1:]
    d = docs.get(cat) or {}
    return d.get("/".join(rest), d.get(rest[-1], {}))


def effective_value(profile_dials, defaults, path):
    """(value, source) the engine actually uses: profile override, else schema default."""
    if path in profile_dials:
        return profile_dials[path], "profile"
    return defaults.get(path), "default"


# ---------------------------------------------------------------- edit engine

_TAG = r"[A-Za-z_][A-Za-z_0-9]*"




def _insert_subchain(inner, tags, value, eol):
    """Insert chain tags[0] > ... > tags[-2] > leaf as a new sub-block inside
    `inner` (the found parent's inner text), as its first child, mirroring the
    indentation of existing children."""
    fm = re.search(r"\n([ \t]*)<%s>" % _TAG, inner)
    ind = fm.group(1) if fm else "  "  # child indent inside this parent
    def build(i, indent):
        if i == len(tags) - 1:
            return "%s<%s>%s</%s>" % (indent, tags[i], value, tags[i])
        sub = build(i + 1, indent + "  ")
        # The closing tag sits at the chain's own indent, matching the
        # in-game-verified persona build.
        return ("%s<%s>%s%s%s%s</%s>%s"
                % (indent, tags[i], eol, sub, eol, indent, tags[i], eol))
    block = build(0, ind)
    # Insert before the first existing child: cut at the start of that
    # child's line ending (the \r of a CRLF pair) and drop the block's
    # trailing EOL, so exactly one EOL separates the inserted block from
    # the existing first child. This reproduces the persona build's bytes.
    fm = re.search(r"\r?\n([ \t]*)<", inner)
    if fm:
        cut = fm.start()
        blk = block[:-len(eol)] if block.endswith(eol) else block
        return inner[:cut] + eol + blk + inner[cut:]
    return block + inner


def _self_closed(text, tag):
    """Find <Tag /> in text. -> dict(start, end, indent) | None.
    Errors if multiple (ambiguous)."""
    ms = list(re.finditer(r"([ \t]*)<%s(\s*/)" % tag, text))
    real = [m for m in ms if m.group(2).strip() == "/"]
    if len(real) != 1:
        return None
    m = real[0]
    end = text.find(">", m.end(1)) + 1
    return {"start": m.start(), "end": end, "indent": m.group(1)}


def _build_subchain(tags, value, eol, indent):
    """Build tags[0] > ... > tags[-1](value) block with given base indent."""
    def build(i, ind):
        if i == len(tags) - 1:
            return "%s<%s>%s</%s>" % (ind, tags[i], value, tags[i])
        sub = build(i + 1, ind + "  ")
        return "%s<%s>%s%s%s</%s>" % (ind, tags[i], eol, sub, eol, tags[i])
    return build(0, indent)


def _insert_chain(vtext, tags, value, eol):
    """Insert the full chain tags[0] > ... > leaf as a new block under <Values>.
    Used when a whole category is absent (e.g. a profile without <Espionage>).
    Indentation mirrors the sibling categories (first existing category tag)."""
    fm = re.search(r"\n([ \t]*)<%s>" % _TAG, vtext)
    if fm:
        ind = fm.group(1)          # indent of existing categories
    else:
        ind = "                "  # 16 spaces = vanilla category indent
    # inner indents step by 2
    def build(i, indent):
        if i == len(tags) - 1:
            return "%s%s<%s>%s</%s>%s%s" % (eol, indent, tags[i], value, tags[i], eol, indent)
        inner = build(i + 1, indent + "  ")
        return "%s%s<%s>%s%s%s</%s>%s" % (eol, indent, tags[i], inner, eol, indent, tags[i], eol)
    body = build(0, ind)
    # insert before </Values>, after the last existing child
    cm = re.search(r"\s*</Values>\s*$", vtext)
    if not cm:
        # vtext includes <Values>...</Values>; insert before its close
        cm = re.search(r"</Values>\s*$", vtext)
    cut = vtext[:cm.start()] + body + eol + ind[:-2] + vtext[cm.start():]
    return cut




# ---------------------------------------------------------------- span engine
# The span index (annoedit/spans.py) walks the child axis only, so a path
# like Military/Min can never match a same-name tag nested deeper down. The
# walk only LOCATES the right parent at the right depth; the actual splices
# use the byte-shape helpers above (_insert_subchain, _insert_chain,
# _build_subchain), which reproduce the in-game-verified persona build.

from .spans import (SpanError, index as _span_index, child as _span_child,
                    text_span as _span_text)


def _spans_validate_value(path, new_value):
    """Path + value check: refuse XML-special characters early."""
    tags = path.split("/")
    if not tags or any(not re.fullmatch(_TAG, t) for t in tags):
        raise EditError(f"bad dial path: {path!r}")
    sval = str(new_value)
    if any(ch in sval for ch in "<>&"):
        raise EditError(
            f"value {sval!r} contains an XML-special character (<, > or &) "
            "— AI dial values are numbers; refusing to write ill-formed XML")


def _indent_of(text, node):
    """Indent string of node's opening line (for built sibling blocks)."""
    line_start = text.rfind("\n", 0, node.open_start) + 1
    return text[line_start:node.open_start]


def set_dial(file_text, profile, path, new_value, insert_after=None):
    """Byte-safe edit of ONE leaf dial (span engine).

    Child-axis walk: a link missing at the right depth is inserted there,
    never satisfied by a same-name tag deeper down. A container at the
    leaf position is refused. Self-closed links and leaves are expanded
    in place. Insert shapes (first child + sibling indent) match the
    in-game-verified persona build byte for byte.

    insert_after (optional): sibling tag to insert a missing leaf after
    (reproduces the persona build's mid-list insert positions); first
    child is the default when unset or the anchor is absent.
    """
    _spans_validate_value(path, new_value)
    tags = path.split("/")
    value = str(new_value)
    span = _locate_values(file_text, profile)
    if span is None:
        raise EditError(
            f"asset for {profile.name} ({profile.guid}) not found")
    vstart, vend = span
    vtext = file_text[vstart:vend]
    eol = "\r\n" if "\r\n" in vtext[:400] else "\n"
    new_v = _span_apply(vtext, tags, value, eol, profile, path, insert_after)
    return file_text[:vstart] + new_v + file_text[vend:]


def _span_apply(vtext, tags, value, eol, profile, path, insert_after=None):
    """Walk tags under the <Values> element of vtext; splice the edit.

    vtext is the full <Values>...</Values> element text (what
    _locate_values returns and what the insert helpers expect).
    """
    root = _span_index(vtext)
    vnodes = _span_child(root, "Values")
    if len(vnodes) != 1:
        raise EditError(
            f"asset for {profile.name} ({profile.guid}): no unique "
            "<Values> block")
    cur = vnodes[0]
    for i, tag in enumerate(tags[:-1]):
        kids = _span_child(cur, tag)
        if len(kids) > 1:
            raise EditError(
                f"dial {path!r} in {profile.name}: ambiguous — "
                f"{len(kids)} <{tag}> blocks at the same level")
        if not kids:
            # Missing link at this depth: insert the remaining chain here.
            # Directly under <Values> a whole category is built; deeper
            # down a sub-chain goes in as the parent's first child.
            if cur.tag == "Values":
                return _insert_chain(vtext, tags[i:], value, eol)
            pstart, pend = _span_text(cur)
            new_inner = _insert_subchain(
                vtext[pstart:pend], tags[i:], value, eol)
            return vtext[:pstart] + new_inner + vtext[pend:]
        k = kids[0]
        if k.self_closed:
            # Self-closed link <Tag/>: replace it in place with the built
            # remaining chain. Splice from the start of the indent (not
            # from '<'), otherwise the indent would be doubled.
            ind = _indent_of(vtext, k)
            block = _build_subchain(tags[i:], value, eol, ind)
            cut = k.open_start - len(ind)
            return vtext[:cut] + block + vtext[k.close_end:]
        if not k.children:
            inner = vtext[_span_text(k)[0]:_span_text(k)[1]]
            if inner.strip():
                raise EditError(
                    f"dial {path!r} in {profile.name}: <{tag}> exists as a "
                    "scalar leaf, not a container")
        cur = k
    leaf = tags[-1]
    kids = _span_child(cur, leaf)
    if len(kids) > 1:
        raise EditError(
            f"dial {path!r} in {profile.name}: ambiguous — {len(kids)} "
            f"<{leaf}> blocks at the same level")
    if len(kids) == 1:
        k = kids[0]
        if k.self_closed:
            # Self-closed leaf <Leaf/>: expand it in place with the value
            # rather than inserting a duplicate beside it. Same indent rule
            # as the link case above.
            ind = _indent_of(vtext, k)
            block = _build_subchain([leaf], value, eol, ind)
            cut = k.open_start - len(ind)
            return vtext[:cut] + block + vtext[k.close_end:]
        if k.children:
            raise EditError(
                f"dial {path!r} in {profile.name}: <{leaf}> is a container "
                "(or list), not a dial — refusing to duplicate it")
        s, e = _span_text(k)
        return vtext[:s] + value + vtext[e:]
    # Missing leaf: the walk above proved there is no direct <Leaf> child,
    # so insert one as the FIRST child of cur, or right AFTER the
    # insert_after sibling when an anchor is given.
    pstart, pend = _span_text(cur)
    inner = vtext[pstart:pend]
    leafxml = "<%s>%s</%s>" % (leaf, value, leaf)
    anchor = None
    if insert_after:
        # Only a direct child can serve as the anchor.
        for c in cur.children:
            if c.tag == insert_after:
                anchor = c
                break
    if anchor is not None:
        # EOL + the anchor's indent + leaf, right after the anchor closes.
        ind = _indent_of(vtext, anchor)
        cut = anchor.close_end - pstart
        new = inner[:cut] + eol + ind + leafxml + inner[cut:]
        return vtext[:pstart] + new + vtext[pend:]
    if cur.children:
        fc = cur.children[0]
        cut = fc.open_start - pstart
        lead = inner[:cut]
        # The indent is only the whitespace after the LAST EOL in the
        # lead. Vanilla files sometimes have a comment before the first
        # child; it must stay where it is and not be copied as "indent".
        if lead.startswith(eol) or eol in lead:
            tail = lead[lead.rfind(eol) + len(eol):] \
                if eol in lead else lead[len(eol):]
            if not tail.strip():
                ind = tail
                new = lead + leafxml + eol + ind + inner[cut:]
            else:
                # something non-ws after the last EOL (a comment directly
                # before the first child): keep the comment, insert the
                # leaf after it at the child's indent
                ind = _indent_of(vtext, fc)
                new = lead + leafxml + eol + ind + inner[cut:]
        elif not lead.strip():
            new = lead + leafxml + inner[cut:]
        else:
            new = leafxml + inner
    else:
        # Parent has no element children (empty): prepend the leaf.
        new = leafxml + inner
    return vtext[:pstart] + new + vtext[pend:]


def _span_apply_dial(vtext, profile, path, new_value, insert_after=None):
    """set_dial's per-edit core, operating on the <Values> substring
    only. Same walk, same byte shapes; the caller splices the result
    back into the file once per batch instead of once per dial."""
    _spans_validate_value(path, new_value)
    tags = path.split("/")
    value = str(new_value)
    eol = "\r\n" if "\r\n" in vtext[:400] else "\n"
    return _span_apply(vtext, tags, value, eol, profile, path, insert_after)


def apply_changes(file_text, profile, changes):
    """Apply changes {path: value} to one profile (span engine).

    -> (new_text, applied, errors). A failing edit is reported in
    `errors` and does not stop the others.
    """
    applied, errors = [], []
    # Locate the <Values> span once, run every edit on that substring,
    # and splice it back once. Every edit stays inside the span, so the
    # result is byte-identical to calling set_dial per dial, at a
    # fraction of the cost on a 2 MB profile file.
    span = _locate_values(file_text, profile)
    if span is None:
        raise EditError(
            f"asset for {profile.name} ({profile.guid}) not found")
    vstart, vend = span
    head, tail = file_text[:vstart], file_text[vend:]
    vtext = file_text[vstart:vend]
    # Apply in REVERSE dict order (not sorted): missing leaves are inserted
    # as the first child of their parent, so reverse application leaves
    # each inserted group in the caller's order. Sorting would change
    # sibling order and break the byte contract.
    # A value may be a (value, insert_after) tuple; the second element is
    # the sibling anchor for a missing-leaf insert.
    for path, val in reversed(list(changes.items())):
        ia = None
        if isinstance(val, tuple):
            val, ia = val[0], (val[1] if len(val) > 1 else None)
        try:
            vtext = _span_apply_dial(vtext, profile, path, val, ia)
            applied.append(path)
        except EditError as e:
            errors.append((path, str(e)))
        except SpanError as e:
            # Report span-level problems as per-edit errors too, so
            # callers only ever deal with one error shape.
            errors.append((path, str(e)))
    return head + vtext + tail, applied, errors


def _locate_values(text, profile):
    """Fresh (vstart, vend) for the profile's <Values> span, located by IDENTITY
    (Standard Name+GUID), not by stored offsets, which go stale after every
    edit. Returns None if not found."""
    # Same identity definition as parse_profiles: the <Standard> block.
    ident = (r"<Standard>\s*<Name>\s*" + re.escape(profile.name)
             + r"\s*</Name>\s*<GUID>" + re.escape(profile.guid) + r"</GUID>")
    # Locate on masked text so a commented-out copy can never capture
    # the edit (offsets are identical on the raw text).
    mtext = mask_markup_comments(text)
    hits = []
    for m in re.finditer(r"<Asset>(.*?)</Asset>", mtext, re.S):
        block = m.group(1)
        if not re.search(ident, block):
            continue
        vm = re.search(r"<Values>.*?</Values>", block, re.S)
        if not vm:
            continue
        hits.append((m.start(1) + vm.start(), m.start(1) + vm.end()))
    if len(hits) > 1:
        # Two live assets with the same identity. parse_profiles refuses
        # this first; this is the defensive second check.
        raise EditError(
            f"ambiguous asset identity {profile.name!r} ({profile.guid}) "
            f"— {len(hits)} assets match; refusing to guess")
    if not hits:
        return None
    return hits[0]
