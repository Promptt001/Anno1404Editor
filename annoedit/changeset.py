#!/usr/bin/env python3
"""changeset — the canonical, validated pending-change model.

One ChangeSet owns ALL pending edits. Edit RECORDS are frozen
dataclasses; the ChangeSet itself is a mutable container — records
are added/replaced ONLY through its add/drop methods, which validate
types (schema DataType when known), canonicalise keys (asset names
resolved to GUIDs, duplicate keys collapse onto one) and normalise
values (ASCII-digit integers str(int(s))). snapshot() returns a
frozen copy a background build can safely chew on while the Tk thread
keeps editing.

The Session remains the safety layer around this: it dry-runs engine
edits and owns the modes/personas bookkeeping. The GUI and CLI talk to
the ChangeSet through Session methods only (no direct dict writes
anywhere; a test enforces this).
"""
from dataclasses import dataclass, field
import re


class ChangeSetError(Exception):
    """Validation failure at queue time (bad path/value/key)."""


# ------------------------------------------------------------- value rules

_ASCII_INT = re.compile(r"-?[0-9]+")


# The game reads these fields as 32-bit integers; an out-of-range value
# wraps or is clamped unpredictably. This is a hard bound at queue time.
# Schema Min/Max is only a warning: the in-game-verified personas
# deliberately exceed some schema maxima.
_INT32_MIN = -(2 ** 31)
_INT32_MAX = 2 ** 31 - 1


def normalize_int(raw, what="value"):
    """An int value must be ASCII digits only ('1_000' and
    full-width digits are NOT ints here) — normalised to str(int(s)).
    Hard int32 bound — the game reads these as 32-bit."""
    s = str(raw).strip()
    if not _ASCII_INT.fullmatch(s):
        raise ChangeSetError(
            f"{what} {s!r} is not a whole number (ASCII digits only) — "
            "AI/extras dial values are integers")
    n = int(s)
    if not (_INT32_MIN <= n <= _INT32_MAX):
        raise ChangeSetError(
            f"{what} {s!r} is out of 32-bit integer range "
            f"({_INT32_MIN}..{_INT32_MAX}) — the game reads these fields "
            "as int32")
    return str(n)           # drops leading zeros / '+' spellings


def normalize_pct(raw, what="value"):
    """A fertility percentage, normalised to an int 0..100 at the
    ChangeSet boundary. The GUI passes strings while catalogs carry ints;
    normalising here keeps every later comparison type-safe."""
    s = str(raw).strip()
    if not re.fullmatch(r"[0-9]+", s):
        raise ChangeSetError(f"{what} {s!r} must be a whole number 0-100")
    n = int(s)
    if not 0 <= n <= 100:
        raise ChangeSetError(f"{what} {s!r} out of range 0-100")
    return n


def normalize_bool(raw, what="value", cur_value=None):
    """Boolean dials accept 0/1 or true/false. cur_value (the dial's
    CURRENT file value, when the caller knows it) preserves the file's
    spelling: '1' stays '1', 'true' stays 'true'. Without cur_value the
    default spelling is digits ('1'/'0'), which is what vanilla AI
    profiles use (e.g. BuildSupplyDepot, ShareAttackingShips)."""
    s = str(raw).strip().lower()
    cur = str(cur_value).strip().lower() if cur_value is not None else None
    if s in ("1", "true"):
        # Preserve the file's spelling: a word-spelled current value
        # keeps words ('1' -> 'true'); digits stay digits.
        if cur in ("true", "false") or (cur is None and s == "true"):
            return "true"
        return "1"
    if s in ("0", "false"):
        if cur in ("true", "false") or (cur is None and s == "false"):
            return "false"
        return "0"
    raise ChangeSetError(f"{what} {s!r} is not a boolean (0/1, true/false)")



# ------------------------------------------------------------- DataType rules

# DataType census of vanilla properties.xml: Integer 154, Time 64, Array 41, Boolean 37, Choice 21,
# Vector 14, Flags 13, RealInt 12, Quest 12, Text 11, Asset 7, FileName 6,
# AIProfile 4, Matrix/Struct/QuestGroup/String/Color 1 each.
# Enumerated types (Choice/Flags) carry <DataSet>Name</DataSet> — the
# allowed values are the <Item><Name> list of that DataSet in
# config/game/datasets.xml (e.g. ResidentLevel = Outlaw..Nobleman,
# Treaty = None/War/PeaceTreaty/PeacePact/TradeTreaty/AllianceTreaty/...).
_READ_ONLY_TYPES = frozenset(("text", "filename", "vector", "array",
                              "quest", "questgroup", "struct", "matrix",
                              "color", "string"))


def normalize_choice(raw, choices, what="value"):
    """A Choice value must be an enumerated item (datasets.xml)."""
    s = str(raw).strip()
    if choices and s not in choices:
        raise ChangeSetError(
            f"{what} {s!r} is not one of the allowed choices {sorted(choices)}")
    if not choices and not re.fullmatch(r"[A-Za-z0-9_]+", s):
        raise ChangeSetError(
            f"{what} {s!r} is not a valid choice token (no enumeration "
            "available for this dial)")
    return s


def normalize_flags(raw, choices, what="value"):
    """A Flags value is a ';'-joined subset of the enumerated items
    (vanilla spells 'War;PeaceTreaty' etc.). Empty = 'None' or ''."""
    s = str(raw).strip()
    # 'None' is a legitimate flags item; an EMPTY string cannot reach
    # here (add_dial treats ''/None as delete-the-edit).
    if s == "None":
        return s
    toks = [t.strip() for t in s.split(";") if t.strip()]
    if not toks:
        return s
    for t in toks:
        if choices and t not in choices:
            raise ChangeSetError(
                f"{what} {t!r} (of {s!r}) is not one of the allowed flags "
                f"{sorted(choices)}")
        if not choices and not re.fullmatch(r"[A-Za-z0-9_]+", t):
            raise ChangeSetError(
                f"{what} {t!r} is not a valid flag token (no enumeration "
                "available for this dial)")
    return ";".join(toks)


# ------------------------------------------------------------- edit records

@dataclass(frozen=True)
class DialEdit:
    """One pending AI-profile dial edit (path canonical, value normalised).

    insert_after (optional): sibling tag to insert this leaf after when
    it is missing, reproducing the persona build's insert positions
    exactly (first child is the default when unset or the anchor is
    absent).

    rule: how the build treats a no-op against the BASE being written
    (live for save-to-live, opened for in-place saves/exports):
      * None    — a manual edit: kept as queued (the review and
                  build apply it verbatim; a no-op manual edit is
                  visible as such in the review and harmless at build);
      * 'reset' — queued by set_mode('vanilla') for every key in scope
                  (not just where the opened archive differs); dropped
                  when value == the base's effective value;
      * 'harden' — queued by set_mode('hardened') for every key in
                  scope; dropped when the base is already at/beyond the
                  target in the dial's direction. "Never easier" is
                  judged against the base being written, not the
                  opened archive.
      * 'revert' — queued by the write ledger to undo a cleared edit.

    from_reference: the value was copied verbatim from the verified
    vanilla reference and skipped re-validation.
    """
    guid: str
    path: str
    value: str
    insert_after: object = None
    rule: object = None
    from_reference: object = False


@dataclass(frozen=True)
class RelEdit:
    """One pending relations kind edit (full-list replacement).

    rule: 'reset' = queued by set_mode('vanilla') for all four kinds
    (the reference lists); the build/review drop it when it is a no-op
    against the base being written. That drop matters: applying an empty
    reference list to a base that lacks the block would insert an empty
    <War> block. rule=None (manual/persona) edits are never dropped.
    """
    guid: str
    kind: str          # War | Ally | Trade | AvoidWar
    guids: tuple
    rule: object = None


@dataclass(frozen=True)
class ExtraEdit:
    """One pending EXTRAS edit (occ None = single-instance or insert).

    expected_old = the value this occurrence held in the opened archive
    at queue time; occ_count = how many occurrences the asset had then.
    When replaying onto the live file, the build refuses if the live leaf
    differs from expected_old or the occurrence count changed (e.g.
    another mod added a level), so an edit can never land on the wrong
    occurrence.
    """
    asset: str        # canonical: resolved display name ('Name [GUID]')
    tag: str
    occ: object = None
    value: str = ""
    expected_old: object = None
    occ_count: object = None
    # 'reset' = queued by revert-globals for every reference leaf. No-ops
    # are dropped against the base being written, and the replay guard
    # expects no particular old value (the intent is the reference value
    # itself; consent comes from the review row).
    rule: object = None


@dataclass(frozen=True)
class FertEdit:
    """One pending fertility edit (None side = leave that side as-is).

    rule: 'reset' = queued by revert-globals absolutely; 'revert' =
    queued by the write ledger (an earlier save wrote this pair, the
    edit was cleared — the save writes the recorded base back). Rule
    rows that cannot locate their leaf in the build base are DROPPED
    at build time (nothing to reset/revert in the target), manual rows
    keep raising.
    """
    tier: str
    crop: str
    north: object = None
    south: object = None
    rule: object = None


# ------------------------------------------------------------- the set

def _norm_rel_list(guid, kind, guids):
    """Normalise one kind's GUID list: order-preserving dedupe, and the
    profile's own GUID is refused in War (a character cannot be at war
    with itself)."""
    items, seen = [], set()
    for g in guids:
        s = str(g).strip()
        if not s:
            continue
        if not _ASCII_INT.fullmatch(s):
            raise ChangeSetError(f"relations {kind} item {s!r} is not a GUID")
        if s in seen:
            continue                    # dedupe, keep first position
        seen.add(s)
        items.append(s)
    if kind == "War" and guid in items:
        raise ChangeSetError(
            f"relations War for {guid} includes the character itself — "
            "a profile cannot be at war with itself")
    return tuple(items)


@dataclass
class ChangeSet:
    """All pending edits, validated on add(); snapshot() for builds.

    Every mutation bumps `version` (Session's cached views key off it)
    and keeps a per-GUID dial index in sync, so dial_map() never rescans
    the full dict. Callers treat views as read-only."""
    dials: dict = field(default_factory=dict)     # (guid, path) -> DialEdit
    rels: dict = field(default_factory=dict)       # (guid, kind) -> RelEdit
    extras: dict = field(default_factory=dict)    # (asset, tag, occ) -> ExtraEdit
    fert: dict = field(default_factory=dict)      # (tier, crop) -> FertEdit
    version: int = field(default=0)   # bumped on every mutation

    def __post_init__(self):
        self._dials_by_guid = {}   # guid -> [(path, DialEdit)] in order
        for (_g, p), e in self.dials.items():
            self._dials_by_guid.setdefault(_g, []).append((p, e))

    # -- generic container behaviour -------------------------------------
    def __bool__(self):
        return bool(self.dials or self.rels or self.extras or self.fert)

    def _bump(self):
        self.version += 1

    def clear(self):
        """Drop every pending edit (after an in-place flash)."""
        self.dials.clear()
        self.rels.clear()
        self.extras.clear()
        self.fert.clear()
        self._dials_by_guid.clear()
        self._bump()

    # -- dials --------------------------------------------------------------
    def add_dial(self, guid, path, value, schema=None, insert_after=None,
                 rule=None, from_reference=False):
        """Validate + queue one dial edit. schema = {path: doc-entry} for
        typed validation: Boolean -> 0/1|true/false, Choice/Flags ->
        enumerated items, text-like types refused, everything else
        (Integer/Time/RealInt/unknown) -> int32. value None/'' removes
        the edit. insert_after = sibling anchor tag for a missing leaf.
        rule: None | 'reset' | 'harden' | 'revert' (see DialEdit).
        A re-add REPLACES the record, so a manual edit over a queued
        reset/harden wins for that key."""
        if value is None or str(value).strip() == "":
            if self.dials.pop((guid, path), None) is not None:
                self._unindex_dial(guid, path)
                self._bump()
            return None
        if from_reference:
            # Copied verbatim from the verified vanilla reference, which
            # was strictly parsed when it was stored. Re-validating it
            # against the opened archive's schema would let a broken
            # datasets.xml (from another mod) abort the whole Vanilla
            # action. Read-only types are filtered out upstream.
            val = str(value)
        else:
            val = self._validate_dial_value(path, value, schema)
        e = DialEdit(guid, path, val, str(insert_after) if insert_after else None,
                     rule=rule, from_reference=from_reference)
        self.dials[(guid, path)] = e
        # A re-queue keeps the original insertion position (as the main
        # dict does); the index must match because apply order is part
        # of the byte contract.
        lst = self._dials_by_guid.setdefault(guid, [])
        for i, (p, _x) in enumerate(lst):
            if p == path:
                lst[i] = (path, e)
                break
        else:
            lst.append((path, e))
        self._bump()
        return e

    def _unindex_dial(self, guid, path):
        lst = self._dials_by_guid.get(guid)
        if lst is not None:
            self._dials_by_guid[guid] = [(p, e) for p, e in lst if p != path]

    def _validate_dial_value(self, path, value, schema):
        """Typed validation against the REAL DataType strings. The
        schema doc-entry may carry 'dataset' (Choice/Flags enumerations,
        captured by parse_schema) and 'cur_value' (to preserve the
        file's 0/1 vs true/false Boolean spelling).
        """
        entry = (schema or {}).get(path) or {}
        dtype = (entry.get("type") or "").strip().lower()
        if dtype in ("boolean", "bool"):
            return normalize_bool(value, f"dial {path}",
                                  entry.get("cur_value"))
        if dtype == "choice":
            # datasets.xml unreadable: the enumeration cannot be checked,
            # so fail closed instead of accepting any word token.
            if entry.get("choices_unavailable"):
                raise ChangeSetError(
                    f"dial {path}: the choice enumeration could not be "
                    "loaded (datasets.xml unreadable) — refusing rather "
                    "than guessing")
            return normalize_choice(value, entry.get("choices"),
                                    f"dial {path}")
        if dtype == "flags":
            if entry.get("choices_unavailable"):
                raise ChangeSetError(
                    f"dial {path}: the flags enumeration could not be "
                    "loaded (datasets.xml unreadable) — refusing rather "
                    "than guessing")
            return normalize_flags(value, entry.get("choices"),
                                   f"dial {path}")
        if dtype in _READ_ONLY_TYPES:
            raise ChangeSetError(
                f"dial {path} is a {entry.get('type') or 'read-only'} value "
                "— the engine never edits it; refusing")
        # Integer / Time / RealInt / AIProfile / Asset / unknown: whole
        # numbers. RealInt values are fixed-point ints (e.g. 204800),
        # never decimals. 'abc', '1.5', '1e5' and '1_000' are refused.
        return normalize_int(value, f"dial {path}")

    def dial_map(self, guid, anchors=False):
        """{path: value} of one profile's pending dial edits.

        anchors=True carries the insert_after anchor as (value, anchor)
        tuples, the shape apply_changes expects.
        """
        out = {}
        for p, e in self._dials_by_guid.get(guid, ()):
            out[p] = ((e.value, e.insert_after) if e.insert_after else e.value) \
                if anchors else e.value
        return out

    def dial_guids(self):
        """Guids with pending dial edits, in INSERTION order (stable
        application order — see apply_changes' reverse-order rule)."""
        out = []
        for (g, _p) in self.dials:
            if g not in out:
                out.append(g)
        return out

    def dial_items(self, guid):
        """[(path, DialEdit)] of one profile's pending dials, INSERTION
        order (the no-op drop needs each record's rule, which dial_map
        does not carry)."""
        return list(self._dials_by_guid.get(guid, ()))

    def dial_value(self, guid, path):
        e = self.dials.get((guid, path))
        return e.value if e else None

    def drop_dial_if(self, guid, path, expected):
        """Drop a saved dial only if the current pending record still
        equals the one the build consumed. A re-edit made while the build
        was running (50, then 77) therefore stays pending.
        -> bool dropped."""
        if self.dials.get((guid, path)) == expected and expected is not None:
            self.drop_dial(guid, path)
            return True
        return False

    def drop_dial(self, guid, path):
        if self.dials.pop((guid, path), None) is not None:
            self._unindex_dial(guid, path)
            self._bump()

    def drop_profile(self, guid):
        """Drop ALL pending edits for one profile (dials + relations)."""
        hit = False
        for k in [k for k in self.dials if k[0] == guid]:
            del self.dials[k]
            hit = True
        self._dials_by_guid.pop(guid, None)
        for k in [k for k in self.rels if k[0] == guid]:
            del self.rels[k]
            hit = True
        if hit:
            self._bump()

    # -- relations ------------------------------------------------------------
    def add_rel(self, guid, kind, guids, rule=None):
        """Queue one kind's full-list replacement. rule: None | 'reset'
        (see RelEdit). The profile's pending relations are validated as
        a whole: order-preserving dedupe, no self-war, and a GUID may not
        be pending in AvoidWar and in War/Ally at the same time."""
        if kind not in ("War", "Ally", "Trade", "AvoidWar"):
            raise ChangeSetError(f"unknown relations kind {kind!r}")
        items = _norm_rel_list(guid, kind, guids)
        # Exclusivity is War/Ally vs AvoidWar only. War+Ally overlap is
        # allowed (the in-game-verified Spider persona has one GUID in
        # both), and so is any Trade overlap (vanilla Giovanni trades
        # with his War targets).
        if kind in ("War", "Ally", "AvoidWar"):
            avoid = {x for (og, k2), r in self.rels.items()
                    if og == guid and k2 == "AvoidWar" for x in r.guids}
            if kind == "AvoidWar":
                clash = [g for g in items if g in
                         ({x for (og, k2), r in self.rels.items()
                           if og == guid and k2 == "War" for x in r.guids}
                          | {x for (og, k2), r in self.rels.items()
                             if og == guid and k2 == "Ally" for x in r.guids})]
            else:
                clash = [g for g in items if g in avoid]
        else:
            clash = []
        if clash:
            # Name both conflicting kinds in the message.
            other = "War/Ally" if kind == "AvoidWar" else "AvoidWar"
            raise ChangeSetError(
                f"relations for {guid}: {clash[0]} is pending in both "
                f"{kind} and {other} — pick one side")
        e = RelEdit(guid, kind, tuple(items), rule=rule)
        self.rels[(guid, kind)] = e
        self._bump()
        return e

    def rel_map(self, guid):
        """{kind: [guid]} of one profile's pending relation edits."""
        return {k: list(e.guids) for (g, k), e in self.rels.items()
                if g == guid}

    def drop_rel_if(self, guid, kind, expected):
        """Value-equality drop for one relations kind (see drop_dial_if)."""
        if self.rels.get((guid, kind)) == expected and expected is not None:
            self.drop_rel(guid, kind)
            return True
        return False

    def drop_rel(self, guid, kind=None):
        hit = False
        if kind is None:
            for k in [k for k in self.rels if k[0] == guid]:
                del self.rels[k]
                hit = True
        elif (guid, kind) in self.rels:
            del self.rels[(guid, kind)]
            hit = True
        if hit:
            self._bump()

    # -- extras ------------------------------------------------------------
    def add_extra(self, asset, tag, value, occ=None,
                  expected_old=None, occ_count=None, rule=None):
        """Canonical key = (asset, tag, occ) with the asset name
        already display-canonical, so the same leaf queued via different
        spellings collapses onto one edit.

        expected_old/occ_count record the queue-time leaf state for the
        replay guard (None = not recorded).
        rule: None | 'reset' (see ExtraEdit)."""
        if value is None or str(value).strip() == "":
            hit = False
            for k in [k for k in self.extras
                      if k[0] == asset and k[1] == tag]:
                del self.extras[k]
                hit = True
            if hit:
                self._bump()
            return None
        # Occurrences are 0-based file-order indices; refuse anything
        # else before it becomes a pending key.
        if occ is not None:
            try:
                oi = int(occ)
            except (TypeError, ValueError):
                raise ChangeSetError(
                    f"extras occurrence {occ!r} is not an integer index")
            if oi < 0:
                raise ChangeSetError(
                    f"extras occurrence {occ!r} is negative — occurrences "
                    "are 0-based file-order indices")
            occ = oi
        val = normalize_int(value, f"extras {asset}/{tag}")
        prev = self.extras.get((asset, tag, occ))
        # A re-queue with the SAME rule (e.g. a manual re-edit over a
        # manual edit) keeps the original queue-time guard records. A
        # different rule inherits nothing: a 'reset' replaces whatever is
        # there, and a stale manual expected_old would wrongly refuse it.
        same_rule = (prev is not None and rule == prev.rule)
        e = ExtraEdit(asset, tag, occ, val,
                      expected_old=(expected_old if expected_old is not None
                                    else (prev.expected_old
                                          if same_rule else None)),
                      occ_count=(occ_count if occ_count is not None
                                 else (prev.occ_count if same_rule
                                       else None)),
                      rule=rule)
        self.extras[(asset, tag, occ)] = e
        self._bump()
        return e

    def drop_extra(self, asset, tag):
        hit = False
        for k in [k for k in self.extras if k[0] == asset and k[1] == tag]:
            del self.extras[k]
            hit = True
        if hit:
            self._bump()

    def drop_extra_if(self, key, expected):
        """Value-equality drop for one exact (asset, tag, occ) extras key."""
        if self.extras.get(key) == expected and expected is not None:
            self.drop_extra_exact(*key)
            return True
        return False

    def drop_extra_exact(self, asset, tag, occ):
        """Remove one exact (asset, tag, occ) key and bump the version."""
        if self.extras.pop((asset, tag, occ), None) is not None:
            self._bump()

    def drop_all_extras(self):
        """Clear every extras edit and bump the version (a raw dict
        .clear() would leave cached views stale)."""
        if self.extras:
            self.extras.clear()
            self._bump()

    def extra_value(self, asset, tag, occ=None):
        e = self.extras.get((asset, tag, occ))
        return e.value if e else None

    # -- fertility ------------------------------------------------------------
    def add_fert(self, tier, crop, north=None, south=None, rule=None):
        """Queue one fertility edit; None side = keep the current side.
        Both sides are normalised to ints 0-100 here (see
        normalize_pct)."""
        cur = self.fert.get((tier, crop))
        n = north if north is not None else (cur.north if cur else None)
        s = south if south is not None else (cur.south if cur else None)
        if n is None and s is None:
            raise ChangeSetError(
                f"fertility {tier}/{crop}: nothing to edit — north and "
                "south both None")
        if n is not None:
            n = normalize_pct(n, f"fertility {tier}/{crop} North")
        if s is not None:
            s = normalize_pct(s, f"fertility {tier}/{crop} South")
        e = FertEdit(tier, crop, n, s, rule=rule)
        self.fert[(tier, crop)] = e
        self._bump()
        return e

    def drop_fert_if(self, key, expected):
        """Value-equality drop for one (tier, crop) fertility key."""
        if self.fert.get(key) == expected and expected is not None:
            self.drop_fert(key[0], key[1])
            return True
        return False

    def drop_fert(self, tier=None, crop=None):
        if tier is None and crop is None:
            if self.fert:
                self.fert.clear()
                self._bump()
            return
        if (tier, crop) in self.fert:
            del self.fert[(tier, crop)]
            self._bump()

    # -- snapshot / counts ---------------------------------------------------
    def snapshot(self):
        """A frozen copy for a background build: later session edits can
        never leak into a build already in flight."""
        return ChangeSet(
            dials=dict(self.dials),
            rels=dict(self.rels),
            extras=dict(self.extras),
            fert=dict(self.fert),
            version=self.version,
        )

    def counts(self):
        """Raw per-class record counts. Relations count list replacements
        per kind."""
        return {
            "dials": len(self.dials),
            "relations": len(self.rels),
            "extras": len(self.extras),
            "fertility": len(self.fert),
        }
