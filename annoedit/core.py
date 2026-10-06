#!/usr/bin/env python3
"""core — the end-to-end pipeline: read RDA -> profiles -> apply preset ->
patch -> repack -> verify. Used by both the CLI and the GUI.

Guarantees:
- The source RDA on disk is never modified; builds write a new file.
- Scope guard: only the four tracked members (ARCHIVE_MEMBERS: the two AI
  profile files, assets.xml, randommapgenerator.xml) may change.
- Line endings are preserved (edits are byte splices on the raw text).
- Every edit is checked by an independent post-condition oracle before
  it is committed to the working text.
- Output is round-trip verified (pack -> re-read strictly -> compare every
  member and the member name set) before it replaces the target.
"""
import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET

from .rda import read_rda, write_rda
from .model import (PROFILE_FILES, SCHEMA_FILE, EditError, apply_changes,
                   mask_markup_comments,
                         dials_dict, effective_value, parse_profiles,
                         parse_schema)
from .presets import hardened_changes
from .extras import (ASSETS_FILE, EXTRA_FAMILIES,
                     extra_values, parse_assets,
                     set_extra as set_extra_edit)
from .fertility import (FERT_FILE,
                        fertility_catalog as fert_catalog_edit,
                        set_fertility as set_fertility_edit)
from .spans import SpanError, index as _span_index

def _rel_items(ind, eol, guids):
    """One <Profiles> block holding all <Item>s (the vanilla shape; the
    game expects a single list)."""
    if not guids:
        return ""
    inner = "".join(
        f"{ind}    <Item>{eol}"
        f"{ind}      <ProfileGUID>{g}</ProfileGUID>{eol}"
        f"{ind}    </Item>{eol}"
        for g in guids)
    return f"{ind}  <Profiles>{eol}{inner}{ind}  </Profiles>{eol}"


def _relations_node(text):
    """Locate the profile's <Relations> element on the child axis
    (Values > Relationships > Relations) via the span index.
    -> the Relations Node (spans absolute into `text`), None when the
    chain genuinely does not exist, EditError when ambiguous or when the
    structure cannot be indexed.

    The walk is position-independent on purpose: <Relationships> also
    holds scalar dials (FriendState, RivalState, SpecialProfiles), and
    the dial engine may insert a missing one as its FIRST child, so
    <Relations> is not guaranteed to come first.
    """
    def _find_values(node):
        if node.tag == "Values":
            return node
        for c in node.children:
            r = _find_values(c)
            if r is not None:
                return r
        return None

    try:
        root = _span_index(text)
    except SpanError as e:
        # Malformed structure is an error, never a silent empty read
        # (downstream consumers would treat the lists as empty).
        raise EditError(f"profile structure unreadable: {e}")
    vals = _find_values(root)
    if vals is None:
        return None
    rship = [c for c in vals.children if c.tag == "Relationships"]
    if len(rship) > 1:
        raise EditError(f"{len(rship)} <Relationships> blocks — ambiguous")
    if not rship:
        return None
    rels = [c for c in rship[0].children if c.tag == "Relations"]
    if len(rels) > 1:
        raise EditError(f"{len(rels)} <Relations> blocks — ambiguous")
    if not rels:
        return None
    return rels[0]


ARCHIVE_MEMBERS = ["addondata/config/ai/aiprofiles.xml",
                   "addondata/config/balancing/addon_01_aiprofiles.xml",
                   ASSETS_FILE,   # EXTRAS
                   FERT_FILE]     # island fertility


def _canonical(el):
    """Independent canonical form for the oracle: (tag, stripped text,
    [canonical children]). ElementTree drops comments, CDATA sections
    and PIs natively, so this comparison is blind to commented-out
    markup by construction, independently of the span/regex locators."""
    return (el.tag, (el.text or "").strip(),
            [_canonical(c) for c in el])


def _set_leaf(root, path, value):
    """Apply one requested dial edit to an ET tree ABSTRACTLY: set the
    leaf's text, creating the full missing parent chain when the leaf
    is absent (the engine's missing-leaf INSERT shape). -> False when
    the path is ambiguous (multiple same-tag children) — the caller
    then skips the abstract apply, the shared locator checks cover it.
    """
    parts = path.split("/")
    node = root
    for pt in parts[:-1]:
        kids = [c for c in node if c.tag == pt]
        if len(kids) != 1:
            return False
        node = kids[0]
    leaf = parts[-1]
    kids = [c for c in node if c.tag == leaf]
    if len(kids) > 1:
        return False
    val = value[0] if isinstance(value, tuple) else value
    if len(kids) == 1:
        kids[0].text = str(val)
        for sub in list(kids[0]):
            kids[0].remove(sub)   # a scalar leaf never gains children
        return True
    el = ET.Element(leaf)
    el.text = str(val)
    # Mirror the engine's insert position (first child, or after the
    # insert_after anchor): the canonical comparison is order-sensitive.
    pos = 0
    if isinstance(value, tuple):
        anchor = value[1]
        for i, c in enumerate(list(node)):
            if c.tag == anchor:
                pos = i + 1
                break
    node.insert(pos, el)
    return True


def _drop_relations_subtree(root):
    """Remove Values > Relationships > Relations from an ET tree (both
    sides) so relations edits are excluded from the canonical diff.
    The parse root may BE the <Values> element (the span is the full
    element) — handled both ways."""
    vals = ([root] if root.tag == "Values"
            else [c for c in root if c.tag == "Values"])
    if len(vals) != 1:
        return
    rships = [c for c in vals[0] if c.tag == "Relationships"]
    if len(rships) != 1:
        return
    rels = [c for c in rships[0] if c.tag == "Relations"]
    if len(rels) == 1:
        rships[0].remove(rels[0])


def _oracle_check(old_text, new_text, profile, edits, dials_after_fn,
                   relations_after_fn=None):
    """Post-condition oracle: verify each edit actually landed.

    Verifies, for an edit batch applied to ONE profile, that:
    1. the dials (or relations) of the edited asset are EXACTLY the old
       ones with the requested paths set to the requested values —
       anything else (wrong-depth rewrite, duplicate tag insert, list
       member treated as a dial) raises EditError and the text is NOT
       committed;
    2. every byte OUTSIDE the edited asset is identical (head/tail);
    3. an INDEPENDENT ElementTree parse of the whole asset (canonical
       form, the edited surface excluded) is unchanged — damage inside
       <Relations>, list structures or empty leaves during a dial edit
       (or to dials during a relations edit) fails here even though the
       shared locator cannot see it.
    """
    from .model import _locate_values, dials_dict
    old_span = _locate_values(old_text, profile)
    new_span = _locate_values(new_text, profile)
    if old_span is None or new_span is None:
        raise EditError(
            f"oracle: asset for {profile.name} ({profile.guid}) "
            "not found before/after the edit")
    # head/tail byte identity (other assets untouched)
    if old_text[:old_span[0]] != new_text[:new_span[0]]:
        raise EditError("oracle: bytes BEFORE the edited asset changed")
    if old_text[old_span[1]:] != new_text[new_span[1]:]:
        raise EditError("oracle: bytes AFTER the edited asset changed")
    # per-edit post-conditions
    if relations_after_fn is not None:
        rel_old = re_find_relations(old_text[old_span[0]:old_span[1]])
        rel_new = re_find_relations(new_text[new_span[0]:new_span[1]])
        for kind, guids in edits.items():
            if rel_new.get(kind) != list(guids):
                raise EditError(
                    f"oracle: relations {kind} is {rel_new.get(kind)} "
                    f"after the edit, expected {list(guids)}")
        # Kinds that were not requested must be unchanged.
        for kind in set(rel_old) | set(rel_new):
            if kind not in edits and rel_new.get(kind) != rel_old.get(kind):
                raise EditError(
                    f"oracle: relations {kind} changed "
                    f"{rel_old.get(kind)} -> {rel_new.get(kind)} without "
                    "an edit (duplicate kind block?)")
        # Duplicate kind blocks need no separate check: re_find_relations
        # raised above if the edit left one behind.
        # A relations edit must never change a dial.
        dialold = dials_dict("<V>" + old_text[old_span[0]:old_span[1]] + "</V>")
        dialnew = dials_dict("<V>" + new_text[new_span[0]:new_span[1]] + "</V>")
        if dialold != dialnew:
            raise EditError(
                "oracle: a dial changed during a relations edit: "
                f"{ {k: (dialold.get(k), dialnew.get(k)) for k in set(dialold) | set(dialnew) if dialold.get(k) != dialnew.get(k)} }")
        _et_cross_check(old_text, new_text, old_span, new_span, profile,
                        edits, relations=True)
        return
    # Wrap the <Values> span for dials_dict. Edit values may be
    # (value, insert_after) tuples; compare on the value only.
    wrap = lambda s: "<V>" + s + "</V>"
    dials_old = dials_dict(wrap(old_text[old_span[0]:old_span[1]]))
    dials_new = dials_dict(wrap(new_text[new_span[0]:new_span[1]]))
    expected = dict(dials_old)
    expected.update({k: (v[0] if isinstance(v, tuple) else v)
                     for k, v in edits.items()})
    if dials_new != expected:
        missing = {k: (expected.get(k), dials_new.get(k))
                   for k in expected if k not in dials_new}
        wrong = {k: (expected.get(k), dials_new.get(k))
                for k in expected if k in dials_new
                and dials_new[k] != expected[k]}
        extra = {k: v for k, v in dials_new.items() if k not in expected}
        raise EditError(
            f"oracle: dial post-condition violated for "
            f"{profile.name} ({profile.guid}) — "
            f"missing={missing} wrong={wrong} extra={extra}")
    _et_cross_check(old_text, new_text, old_span, new_span, profile,
                    edits, relations=False)


def _et_cross_check(old_text, new_text, old_span, new_span, profile,
                    edits, relations):
    """The independent oracle core (see _oracle_check docstring).

    Dials: expected = the OLD tree with the requested edits applied
    abstractly (_set_leaf, missing chains created); actual = the new
    text's tree. Canonical forms must be EQUAL — damage anywhere else
    (a moved GUID inside Relations, a duplicated sibling, a clobbered
    empty leaf) fails here even though the shared locator cannot see
    it. Relations: the Relations subtree is dropped from both sides —
    the edit only ever rewrites that subtree.
    """
    import copy
    try:
        a = ET.fromstring(old_text[old_span[0]:old_span[1]])
        b = ET.fromstring(new_text[new_span[0]:new_span[1]])
    except ET.ParseError as e:
        raise EditError(
            f"oracle: edited asset for {profile.name} ({profile.guid}) "
            f"no longer parses as XML: {e}")
    if relations:
        _drop_relations_subtree(a)
        _drop_relations_subtree(b)
    else:
        a = copy.deepcopy(a)
        ok = True
        # Reverse dict order, mirroring apply_changes.
        for path, v in reversed(list(edits.items())):
            if not _set_leaf(a, path, v):
                ok = False
                break
        if not ok:
            # Ambiguous path: the dial post-condition above already
            # covers it; skip rather than compare against a half-applied
            # expectation.
            return
    ca, cb = _canonical(a), _canonical(b)
    if ca != cb:
        raise EditError(
            f"oracle: independent parse of {profile.name} "
            f"({profile.guid}) differs from the expected result: "
            f"expected={str(ca)[:180]} actual={str(cb)[:180]}")


class ArchiveMemberMissing(Exception):
    """A required archive member is absent (e.g.
    addondata/config/ai/properties.xml). A dedicated type so callers can
    report it precisely instead of as a generic KeyError."""


class ModProject:
    """One editing session over a source data1.rda.

    Pipeline: read RDA -> parse profiles/schema/extras/fertility -> apply
    edits via set_* methods -> verify_xml + scope guard -> build (pack,
    round-trip verify). The source archive on disk is never modified."""

    def __init__(self, source_rda, entries=None):
        """entries=None -> read the archive from disk; pass IN-MEMORY entries
        (a session build must never re-read a possibly-changed source;
        it builds from the exact entries the user opened and reviewed)."""
        self.source_rda = source_rda
        self.entries = dict(entries) if entries is not None \
            else read_rda(source_rda, strict=True)  # name -> (data, ts)
        # Reads are strict: a ModProject is the base of every write-back
        # build, so a corrupt archive must fail the open instead of
        # producing a save that silently drops unreadable members.
        self.schema_text = self._read(SCHEMA_FILE)
        self.docs, self.defaults = parse_schema(self.schema_text)
        self.filetexts = {}      # filekey -> current text (mutable)
        self.profiles = {}       # filekey -> [Profile]
        for fk, rel in PROFILE_FILES.items():
            # Parsing happens once, in _resync_offsets below.
            self.filetexts[fk] = self._read(rel).decode("utf-8")
        # EXTRAS: assets.xml working text + applied-change log.
        # The file is cp1252, but Python's cp1252 codec leaves five bytes
        # undefined (0x81/0x8D/0x8F/0x90/0x9D) that can appear in binary
        # blocks. latin-1 maps every byte to exactly one char and back, and
        # all engine edits are ASCII, so decoding as latin-1 is lossless.
        self.assets_text = self._read(ASSETS_FILE).decode("latin-1")
        self.extras_changes = []   # [{asset, tag, occ, old, new}]
        # Fertility: randommapgenerator.xml working text + change log.
        # Same latin-1 rule. The file is not well-formed XML overall
        # (binary head), so only span-safe edits are made.
        self.fert_text = self._read(FERT_FILE).decode("latin-1")
        self.fert_changes = []      # [{tier, crop, old, new}]
        # Profiles, dials and the by_name/by_guid indexes.
        self._resync_offsets()
        # Cached catalogs (the extras catalog is expensive on real data).
        # The set_* methods invalidate them; builds always use a fresh
        # project, so staleness can never leak into a build.
        self._extras_cat = None
        self._fert_cat = None

    @classmethod
    def from_entries(cls, entries, source_rda=None):
        """Seed from in-memory entries."""
        return cls(source_rda, entries=entries)

    # ---------------------------------------------------------------- helpers

    def _read(self, rel):
        if rel not in self.entries:
            # A missing member gets its own exception type.
            raise ArchiveMemberMissing(rel)
        return self.entries[rel][0]

    def text_of(self, profile):
        """Asset block text of profile, sliced by its CURRENT stored offsets."""
        t = self.filetexts[profile.filekey]
        return t[profile.start:profile.end]

    def _resync_offsets(self, only_filekey=None):
        """Refresh stale profile offsets/dials after an edit (re-parse
        ONLY the edited file — another file's spans cannot have moved)."""
        keys = [only_filekey] if only_filekey is not None else list(self.filetexts)
        for fk in keys:
            text = self.filetexts[fk]
            ps = parse_profiles(fk, text)
            self.profiles[fk] = ps
            for p in ps:
                p.dials = dials_dict(self.text_of(p))
        # Rebuild the indexes from the already-parsed profiles.
        self.by_name, self.by_guid = {}, {}
        for fk, ps in self.profiles.items():
            for p in ps:
                self.by_name.setdefault(p.name, p)
                self.by_guid[p.guid] = p

    def lookup(self, profile, path):
        """(value, source) for a dial: profile override else schema default."""
        return effective_value(profile.dials, self.defaults, path)

    def defaults_by_cat(self):
        """{category: [dial paths with a schema default]} (the GUI dial
        tables add these to the visible/editable set)."""
        out = {}
        for path in self.defaults:
            cat = path.split("/")[0]
            out.setdefault(cat, []).append(path)
        return out

    # ---------------------------------------------------------------- editing

    def set_dials(self, profile, changes):
        """Apply changes {path: value} to one profile.
        Returns (applied list, refreshed Profile object)."""
        text = self.filetexts[profile.filekey]
        new_text, applied, errors = apply_changes(text, profile, changes)
        if errors:
            raise EditError("; ".join(f"{p}: {e}" for p, e in errors))
        # Verify the edit produced exactly old dials + requested changes
        # and nothing outside this asset changed, before committing.
        _oracle_check(text, new_text, profile, changes, None)
        self.filetexts[profile.filekey] = new_text
        # Re-parse only the edited file (offsets elsewhere still valid)
        self._resync_offsets(profile.filekey)
        return applied, self.by_guid[profile.guid]

    # ---------------------------------------------------------------- relations

    def relations(self, profile):
        """-> {'War': [guid,...], 'Ally': [...], 'Trade': [...], 'AvoidWar': [...]}"""
        rel = {}
        pm = re_find_relations(self.text_of_fresh(profile))
        for kind, guids in pm.items():
            rel[kind] = guids
        return rel

    def text_of_fresh(self, profile):
        """Asset text of THIS profile, re-located by identity (Name+GUID) in
        the CURRENT file text, not by stored offsets. Stored offsets go
        stale after any edit to an earlier asset in the same file, and a
        stale span could cover a different profile's block. All public
        read/edit entry points use this (set_dial re-locates internally)."""
        from .model import _locate_values
        text = self.filetexts[profile.filekey]
        span = _locate_values(text, profile)
        if span is None:
            raise EditError(f"asset for {profile.name} ({profile.guid}) not found")
        return text[span[0]:span[1]]

    def set_relations(self, profile, war=None, ally=None, trade=None, avoidwar=None):
        """Rewrite the profile's Relations lists. None = leave that list
        EXACTLY as-is (byte-identical); a list value REPLACES the list;
        () = clear the list (empty block kept, engine-legal).
        Byte-safety: each kind's existing span is preserved verbatim when
        None; only requested kinds are rewritten, one innermost block each."""
        import re
        text = self.filetexts[profile.filekey]
        # Re-locate this profile's <Values> span by identity (Name+GUID);
        # stored offsets may be stale (see text_of_fresh).
        from .model import _locate_values
        span = _locate_values(text, profile)
        if span is None:
            raise EditError(f"asset for {profile.name} ({profile.guid}) not found")
        vstart, vend = span
        v = text[vstart:vend]
        # Child-axis locate (see _relations_node).
        rnode = _relations_node(v)
        if rnode is None:
            raise EditError(f"{profile.name}: no Relations block")
        body = v[rnode.open_end:rnode.close_start]
        # Per-kind blocks: <War>...</War> etc. (non-greedy, so a span never
        # swallows a sibling kind block), plus self-closed kinds such as
        # <Trade/> (present but empty), which are replaced in place.
        eol = "\r\n" if "\r\n" in body[:200] else "\n"

        def _reindex(b):
            # Scan the comment-masked body, so a commented-out kind block
            # is invisible here exactly as it is to the reader.
            mb = mask_markup_comments(b)
            ks, scs, counts = {}, {}, {}
            for km2 in re.finditer(
                    r"([ \t]*)(<(War|Ally|Trade|AvoidWar)>)(.*?)(</\3>)", mb, re.S):
                counts[km2.group(3)] = counts.get(km2.group(3), 0) + 1
                if km2.group(3) not in ks:
                    ks[km2.group(3)] = km2
            for km2 in re.finditer(r"([ \t]*)<(War|Ally|Trade|AvoidWar)\s*/>", mb):
                counts[km2.group(2)] = counts.get(km2.group(2), 0) + 1
                if km2.group(2) not in scs:
                    scs[km2.group(2)] = km2
            for k2, n2 in counts.items():
                if n2 > 1:
                    raise EditError(
                        f"{profile.name}: duplicate {k2} block in "
                        "Relations — refusing to guess which one the "
                        "game reads")
            return ks, scs

        kind_spans, sc_spans = _reindex(body)
        for kind, guids in (("War", war), ("Ally", ally),
                             ("Trade", trade), ("AvoidWar", avoidwar)):
            if guids is None:
                continue  # leave exactly as-is
            km = kind_spans.get(kind)
            scm = sc_spans.get(kind)
            if km is None and scm is not None:
                # Self-closed kind <Trade/>: replace it in place at its own
                # indent rather than adding a second block beside it.
                ind = scm.group(1)
                items = _rel_items(ind, eol, guids)
                new_block = (f"{ind}<{kind}>{eol}{items}{ind}</{kind}>" if items
                              else f"{ind}<{kind}>{eol}{ind}</{kind}>")
                body = body[:scm.start()] + new_block + body[scm.end():]
                kind_spans, sc_spans = _reindex(body)
                continue
            if km is None:
                # Missing kind: insert a new block after <Relations>.
                ind = "                    "  # vanilla sibling indent (20 sp)
                fm = re.search(r"([ \t]*)(<(?:War|Ally|Trade|AvoidWar)>)", body)
                if fm:
                    ind = fm.group(1)
                items = _rel_items(ind, eol, guids)
                block = (f"{ind}<{kind}>{eol}{items}{ind}</{kind}>{eol}" if items
                         else f"{ind}<{kind}>{eol}{ind}</{kind}>{eol}")
                # Insert at the front of the body, right after its leading
                # EOL, so the existing first kind keeps its own indent. This
                # matches the in-game-verified persona build's shape.
                if body.startswith(eol):
                    body = eol + block + body[len(eol):]
                else:
                    body = block + body
                # The front insert shifted every offset: re-index.
                kind_spans, sc_spans = _reindex(body)
                continue
            ind = km.group(1)
            items = _rel_items(ind, eol, guids)
            new_block = (f"{ind}<{kind}>{eol}{items}{ind}</{kind}>" if items
                          else f"{ind}<{kind}>{eol}{ind}</{kind}>")
            body = body[:km.start()] + new_block + body[km.end():]
            # Offsets shifted: re-index.
            kind_spans, sc_spans = _reindex(body)
        new_v = v[:rnode.open_end] + body + v[rnode.close_start:]
        new_text = text[:vstart] + new_v + text[vend:]
        # Verify each requested kind now carries exactly the requested
        # list and nothing outside this asset changed, before committing.
        requested = {k: list(v2) for k, v2 in
                     (("War", war), ("Ally", ally),
                      ("Trade", trade), ("AvoidWar", avoidwar))
                     if v2 is not None}
        _oracle_check(text, new_text, profile, requested, None,
                      relations_after_fn=True)
        self.filetexts[profile.filekey] = new_text
        # Re-parse only the edited file (offsets elsewhere still valid)
        self._resync_offsets(profile.filekey)

    # ---------------------------------------------------------------- extras

    def set_extra(self, asset_name, tag, value, occ=None):
        """Apply one EXTRAS change to the assets.xml working text immediately
        and record it in the session change log. occ=None -> single-instance
        rule (multi-instance tags like noria radii REQUIRE an explicit occ)."""
        new_text, old = set_extra_edit(self.assets_text, asset_name, tag, value, occ)
        self.assets_text = new_text
        self._extras_cat = None   # invalidate the cached catalog
        self.extras_changes.append({"asset": asset_name, "tag": tag, "occ": occ,
                                    "old": old, "new": str(value)})
        return old

    def extras_catalog(self):
        """-> {section: {tag: {asset name: [values, file order]}}} for GUI
        tables, over THIS project's working text (cached — the same
        project object returns the same dict; treat it as read-only)."""
        if self._extras_cat is None:
            assets = parse_assets(self.assets_text)
            out = {}
            for section, fam in EXTRA_FAMILIES.items():
                out[section] = {tag: extra_values(self.assets_text, assets, tag)
                                for tag in fam}
            self._extras_cat = out
        return self._extras_cat

    # ---------------------------------------------------------------- fertility

    def set_fertility(self, tier, crop, north=None, south=None):
        """Apply one fertility change to the randommapgenerator.xml working
        text immediately and record it in the change log.
        -> old {'north','south'} dict (only requested fields)."""
        new_text, old = set_fertility_edit(self.fert_text, tier, crop, north, south)
        self.fert_text = new_text
        self._fert_cat = None      # invalidate the cached catalog
        self.fert_changes.append({"tier": tier, "crop": crop, "old": old,
                                  "new": {"north": north, "south": south}})
        return old

    def fertility_catalog(self):
        """-> [{crop,tier,north,south}] rows for the GUI fertility table,
        over THIS project's working text (cached)."""
        if self._fert_cat is None:
            self._fert_cat = fert_catalog_edit(self.fert_text)
        return self._fert_cat

    # ---------------------------------------------------------------- build

    def verify_xml(self):
        """Parse every profile file text; -> list of parse error strings."""
        errs = []
        for fk, text in self.filetexts.items():
            try:
                ET.fromstring(text)
            except ET.ParseError as e:
                errs.append(f"{fk}: {e}")
        return errs

    def changed_files(self):
        """-> archive members whose current text differs from the source."""
        out = []
        for fk, rel in PROFILE_FILES.items():
            if self.filetexts[fk].encode("utf-8") != self.entries[rel][0]:
                out.append(rel)
        return out

    def build(self, out_path):
        """Write the patched archive. Returns report dict. Round-trip verified."""
        errs = self.verify_xml()
        if errs:
            raise EditError("XML parse failed: " + "; ".join(errs))
        # extras working text must be well-formed before packing
        import xml.etree.ElementTree as ET2
        try:
            ET2.fromstring(self.assets_text)
        except ET2.ParseError as e:
            raise EditError(f"assets.xml parse failed: {e}")
        changed = self.changed_files()
        if self.assets_text.encode("latin-1") != self.entries[ASSETS_FILE][0]:
            changed.append(ASSETS_FILE)
        if self.fert_text.encode("latin-1") != self.entries[FERT_FILE][0]:
            changed.append(FERT_FILE)
        if not (set(changed) <= set(ARCHIVE_MEMBERS)):
            raise EditError(f"scope guard: unexpected files changed: {changed}")
        entries = dict(self.entries)
        for fk, rel in PROFILE_FILES.items():
            data = self.filetexts[fk].encode("utf-8")
            ts = self.entries[rel][1]
            entries[rel] = (data, ts)
        if self.assets_text.encode("latin-1") != self.entries[ASSETS_FILE][0]:
            entries[ASSETS_FILE] = (self.assets_text.encode("latin-1"),
                                    self.entries[ASSETS_FILE][1])
        if self.fert_text.encode("latin-1") != self.entries[FERT_FILE][0]:
            entries[FERT_FILE] = (self.fert_text.encode("latin-1"),
                                  self.entries[FERT_FILE][1])
        # Build to a temp path next to the target, verify it, and only then
        # atomically replace out_path, so an unverified file never sits at
        # the user's path. The round-trip check compares every member's
        # bytes and the member name set.
        _fd, tmp_path = tempfile.mkstemp(
            prefix=".annoedit-", suffix=".verifytmp",
            dir=os.path.dirname(os.path.abspath(out_path)) or ".")
        os.close(_fd)
        os.unlink(tmp_path)
        try:
            n, nb = write_rda(entries, tmp_path)
            rt = read_rda(tmp_path, strict=True)
            mismatch = [k for k in entries if rt.get(k, (b"",))[0] != entries[k][0]]
            missing = [k for k in entries if k not in rt]
            extra = [k for k in rt if k not in entries]  # name-set equality
            if mismatch or missing or extra:
                raise EditError(f"round-trip failed: mismatch={mismatch} "
                                f"missing={missing} extra={extra}")
            # Give the temp file the existing target's mode, or
            # 0o666 & ~umask for a new file (mkstemp creates 0600).
            try:
                os.chmod(tmp_path, os.stat(out_path).st_mode & 0o7777)
            except OSError:
                um = os.umask(0); os.umask(um)
                os.chmod(tmp_path, 0o666 & ~um)
            os.replace(tmp_path, out_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _fsync_parent(out_path)
        with open(out_path, "rb") as f:
            md5 = hashlib.md5(f.read()).hexdigest()
        report = {"out": out_path, "files": n, "blocks": nb,
                  "changed": changed, "md5": md5,
                  # The exact entry map written, so callers can rebuild an
                  # in-memory project without re-reading the file after
                  # the (irreversible) replace.
                  "entries": entries}
        return report


def _fsync_parent(path):
    """Fsync the parent directory after an atomic replace so the rename
    is durable (POSIX). Best-effort, never raises. Kept local rather than
    importing backup, to avoid an import cycle."""
    try:
        dfd = os.open(os.path.dirname(os.path.abspath(path)) or ".",
                      os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def re_find_relations(asset_text):
    """-> {kind: [guid, ...]} from a profile's Relations block ({} if none).

    A child-axis span walk over the <Relations> node (see
    _relations_node). The tokenizer skips comments/CDATA/PIs, so a
    commented-out kind block is invisible to the reader exactly as it is
    to the writer. Duplicate live kind blocks raise. Structural errors
    raise EditError; {} means the Relations chain genuinely does not
    exist.
    """
    rnode = _relations_node(asset_text)   # raises EditError, never swallows
    if rnode is None:
        return {}
    out = {}
    for c in rnode.children:
        if c.tag not in ("War", "Ally", "Trade", "AvoidWar"):
            continue
        if c.tag in out:
            raise EditError(
                f"duplicate {c.tag} block in Relations — refusing to "
                "guess which one the game reads")
        if c.self_closed:
            out[c.tag] = []       # present but empty (<Trade/>)
            continue
        profs = [g for g in c.children if g.tag == "Profiles"]
        if len(profs) > 1:
            raise EditError(f"duplicate <Profiles> block in {c.tag}")
        if not profs:
            out[c.tag] = []       # empty open kind block (<War></War>)
            continue
        guids = []
        for it in profs[0].children:
            if it.tag != "Item":
                continue
            for g in it.children:
                if g.tag == "ProfileGUID" and g.close_start >= 0:
                    t = asset_text[g.open_end:g.close_start].strip()
                    if re.fullmatch(r"-?\d+", t):
                        guids.append(t)
        out[c.tag] = guids
    return out


# ---------------------------------------------------------------- usage

def hardened_build(source_rda, out_path, exclude_guids=()):
    """Apply 'hardened' to every profile not in exclude_guids. -> (report, applied)
    Never makes a dial easier: hardened_changes skips any dial already
    at/beyond the hardest vanilla value."""
    proj = ModProject(source_rda)
    allp = [p for ps in proj.profiles.values() for p in ps]
    applied = {}
    for fk, ps in proj.profiles.items():
        for p in ps:
            if p.guid in exclude_guids:
                continue
            changes = hardened_changes(p, allp, proj.defaults)
            if changes:
                proj.set_dials(p, changes)
                applied[f"{p.name} ({p.guid})"] = changes
    return proj.build(out_path), applied
