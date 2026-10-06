"""plan — the single source of truth for what a build will write.

Vanilla / Hardened / revert-globals queue a value for EVERY key in scope,
marked rule='reset' or 'harden'. Which of those rows are real changes
depends only on the BASE being written (the live file for save-to-live,
the opened archive for in-place saves and exports).

plan(cs, roster, base) -> (rows, totals): every ResolvedChange row is a
change the build WILL make against base; no-op rule rows are dropped
here, once. The review dialog, the pending counts and the build's no-op
drop all derive from plan(), so what the user approves is by
construction what gets written.

plan() only decides keep/drop. The bytes are still emitted by the edit
engine in its fixed order (one batch per profile, insert_after anchors).
"""

from .model import effective_value
from .presets import KEY_DIALS

# Sections of the plan, in review display order.
AI_PROFILE = "AI profile"
AI_RELATIONS = "AI relations"
EXTRAS = "EXTRAS"
FERTILITY = "FERTILITY"


class ResolvedChange:
    """One row of the change plan: what the build will do to BASE.

    kind: AI_PROFILE | AI_RELATIONS | EXTRAS | FERTILITY
    key:  the IDENTITY of the leaf — (guid, path) / (guid, kind) /
          (asset, tag, occ) / (tier, crop), exactly the ChangeSet's own
          key shape, so the build can match plan rows to records
    name: the display character/asset name (roster name or asset id)
    old:  the value in BASE the edit replaces ('(absent)' markers as
          the review shows them) or None when unknown
    new:  the value the build writes
    rule: 'reset' | 'harden' | None (manual/persona — never dropped)
    label: ready display dial label (EXTRAS multi-instance '#N' suffix)
    """

    __slots__ = ("kind", "key", "name", "old", "new", "rule", "label")

    def __init__(self, kind, key, name, old, new, rule=None, label=None):
        self.kind = kind
        self.key = key
        self.name = name
        self.old = old
        self.new = new
        self.rule = rule
        self.label = label

    def row(self):
        """The review-dialog display row {section, character, dial,
        old, new} — the only shape the dialog needs from the plan.
        label (EXTRAS multi-instance tags) carries the ready '#N'
        dial suffix."""
        if self.kind == AI_PROFILE:
            character, dial = self.name, self.key[1]
        elif self.kind == AI_RELATIONS:
            character, dial = self.name, f"Relations/{self.key[1]}"
        elif self.kind == EXTRAS:
            character, dial = self.name, (self.label or self.key[1])
        else:
            character, dial = self.name, self.key[1]
        return {"section": self.kind, "character": character,
                "dial": dial, "old": self.old, "new": self.new}

    def __repr__(self):  # pragma: no cover — debugging aid
        return (f"ResolvedChange({self.kind!r}, {self.key!r}, "
                f"old={self.old!r}, new={self.new!r}, rule={self.rule!r})")


def plan_dial_noop(e, bprof, base, path):
    """True when a rule-marked dial edit is a NO-OP against BASE
    ('reset': base effective == target; 'harden': base at/beyond the
    target in the KEY_DIALS direction, NEVER-EASIER vs the BASE; a
    non-numeric base value keeps the edit — the engine refuses at
    apply time, loudly). rule=None is never a no-op here."""
    if not e.rule or bprof is None:
        return False
    cur, _src = effective_value(bprof.dials, base.defaults, path)
    if e.rule in ("reset", "revert"):
        return cur is not None and str(cur) == str(e.value)
    if e.rule == "harden":
        d = dict(KEY_DIALS).get(path)
        if not d:
            return False
        try:
            c, t = float(cur), float(e.value)
        except (TypeError, ValueError):
            return False
        return (d == "max" and c >= t) or (d == "min" and c <= t)
    return False


def plan_dials(cs, roster, base, opened):
    """AI-profile dial rows (drop rule no-ops vs base) + the dropped
    keys, in roster order then path order (the review display order).
    No base (CLI dry-run shape): old comes from the OPENED project and
    no rule row drops (the call site decides the shape)."""
    out, dropped = [], []
    for q in roster:
        bprof = base.by_guid.get(q.guid) if base is not None else None
        oprof = opened.by_guid.get(q.guid) if opened is not None else None
        for path, e in sorted(dict(cs.dial_items(q.guid)).items()):
            if base is not None and plan_dial_noop(e, bprof, base, path):
                dropped.append((q.guid, path))
                continue
            src_prof = bprof if base is not None else oprof
            if src_prof is not None:
                defaults = base.defaults if base is not None \
                    else opened.defaults
                val, _src = effective_value(
                    src_prof.dials, defaults, path)
                old = val if val is not None else "(absent)"
            else:
                old = None
            out.append(ResolvedChange(
                AI_PROFILE, (q.guid, path), q.name, old, e.value, e.rule))
    return out, dropped


def plan_relations(cs, roster, base, opened):
    """AI-relations rows (drop rule no-ops vs base) + dropped keys.
    No base: old comes from the OPENED project's relations."""
    out, dropped = [], []
    for q in roster:
        e_set = {k for (g, k) in cs.rels if g == q.guid}
        if not e_set:
            continue
        bprof = base.by_guid.get(q.guid) if base is not None else None
        if base is not None and bprof is not None:
            cur = base.relations(bprof)
        elif opened is not None:
            oprof = opened.by_guid.get(q.guid)
            cur = opened.relations(oprof) if oprof is not None else {}
        else:
            cur = {}
        for kind in sorted(e_set):
            e = cs.rels[(q.guid, kind)]
            if (base is not None and e.rule and bprof is not None
                    and list(cur.get(kind, ()))
                    == [str(g) for g in e.guids]):
                dropped.append((q.guid, kind))
                continue
            out.append(ResolvedChange(
                AI_RELATIONS, (q.guid, kind), q.name,
                ", ".join(str(g) for g in cur.get(kind, [])) or "(empty)",
                ", ".join(str(g) for g in e.guids) or "(empty)",
                e.rule))
    return out, dropped


def plan_extras(cs, base_catalog, multi_tags=None):
    """EXTRAS rows. base_catalog = base.extras_catalog(); rule='reset'
    rows whose base value already equals the target are dropped.
    multi_tags (optional): {(asset, tag): bool} — when the asset
    carries MULTIPLE instances of the tag (norias, multi-level build
    times) the row's dial label gets the '#N' occurrence suffix
    (review row shape); the key keeps (asset, tag, occ)."""
    out = []
    if cs.extras:
        for (asset, tag, occ), e in sorted(
                cs.extras.items(),
                key=lambda kv: (kv[0][0], kv[0][1],
                                kv[0][2] if kv[0][2] is not None else -1)):
            val = e.value
            old = _catalog_value(base_catalog, asset, tag, occ)
            if (e.rule in ("reset", "revert")
                    and old != "(absent)" and str(old) == str(val)):
                continue
            # A rule row whose base value is '(absent)' is dropped: a
            # reset writes a value back, and there is nothing to write
            # back to when the asset or tag is not in the base at all.
            # Manual insert rows (rule=None) are never dropped.
            if e.rule and old == "(absent)":
                continue
            multi = multi_tags.get((asset, tag)) if multi_tags else None
            if multi is None and base_catalog:
                for section in base_catalog.values():
                    fam = section.get(tag)
                    if fam and len(fam.get(asset) or ()) > 1:
                        multi = True
                        break
            label = (f"{tag} #{occ + 1}" if (multi and occ is not None)
                     else tag)
            out.append(ResolvedChange(
                EXTRAS, (asset, tag, occ), asset, old, val, e.rule,
                label=label))
    return out


def plan_fertility(cs, base_catalog):
    """FERTILITY rows. base_catalog = base.fertility_catalog(); rows
    whose pending side is None-or-equal on BOTH sides are dropped (a
    None side means 'keep that side' — a no-op by definition)."""
    out = []
    if cs.fert:
        by_key = {(r["tier"], r["crop"]): r for r in base_catalog}
        for (tier, crop), e in sorted(cs.fert.items()):
            r = by_key.get((tier, crop), {})
            n, sv = e.north, e.south
            if ((n is None or n == r.get("north"))
                    and (sv is None or sv == r.get("south"))):
                continue
            # A rule row whose pair is missing from the base catalog is
            # dropped: there is nothing to write back to.
            rule = getattr(e, "rule", None)
            if rule and (tier, crop) not in by_key:
                continue
            old = f"N={r.get('north')} S={r.get('south')}"
            new = " ".join([p for p in (f"N={n}" if n is not None else None,
                                       f"S={sv}" if sv is not None
                                       else None) if p])
            out.append(ResolvedChange(
                FERTILITY, (tier, crop), tier, old, new,
                getattr(e, "rule", None)))
    return out


def _catalog_value(catalog, asset, tag, occ):
    """Current value of one extras leaf from a base catalog, with the
    '(absent)' marker for display ('old' = what the edit replaces)."""
    for section in catalog.values():
        fam = section.get(tag)
        if not fam:
            continue
        vals = fam.get(asset)
        if vals is None:
            plain = asset.split(" [", 1)[0]
            hits = [v for k, v in fam.items()
                    if k.split(" [", 1)[0] == plain]
            vals = hits[0] if hits else None
        if vals is None:
            continue
        if occ is None:
            return vals[0] if vals else "(absent)"
        return vals[occ] if occ < len(vals) else "(absent)"
    return "(absent)"


def plan(cs, roster, base, opened=None, base_extras_catalog=None,
         base_fert_catalog=None):
    """THE change plan: everything the build will write against BASE.

    base: the project the save will actually write (the LIVE project
    for save-to-live — from the stashed drift result; the opened
    project for in-place saves and exports).  No-op rule rows
    ('reset'/'harden' whose target the base already carries) are
    dropped HERE, once — the review, the build's no-op drop, and every
    display count derive from this plan, so what the user approves
    is by construction what the build writes.

    No base (CLI dry-run shape): old comes from the OPENED project and
    no rule row drops — the call site decides the shape.

    -> (rows, totals): rows = [ResolvedChange], totals = {dials,
    relations, extras, fertility} real-change counts (relations counts
    GUID items across the kept replacement lists).
    """
    if base_extras_catalog is None:
        base_extras_catalog = (base.extras_catalog() if base is not None
                               else (opened.extras_catalog()
                                     if opened is not None else {}))
    if base_fert_catalog is None:
        base_fert_catalog = (base.fertility_catalog() if base is not None
                             else (opened.fertility_catalog()
                                   if opened is not None else []))
    dials, dropped_dials = plan_dials(cs, roster, base, opened)
    rels, dropped_rels = plan_relations(cs, roster, base, opened)
    extras = plan_extras(cs, base_extras_catalog)
    fert = plan_fertility(cs, base_fert_catalog)
    rows = dials + rels + extras + fert
    dropped = set(dropped_dials) | set(dropped_rels)
    totals = {
        "dials": len(dials),
        "relations": sum(len(cs.rels[k].guids) for k in cs.rels
                         if k not in dropped),
        "extras": len(extras),
        "fertility": len(fert),
    }
    return rows, totals


def plan_hash(rows):
    """Stable hash of a plan (the rows list); part of the consent anchor
    that binds a review to its build. Built from the same fields that make a row a change
    (kind, key, old, new, rule, name); two plans hash equal iff the
    builds would make the same writes."""
    import hashlib
    import json
    canon = json.dumps(
        [[r.kind, _canon(r.key), _canon(r.name), _canon(r.old),
          _canon(r.new), _canon(r.rule), _canon(r.label)] for r in rows],
        sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _canon(x):
    if isinstance(x, tuple):
        return ["t", _canon(list(x))]
    if isinstance(x, list):
        return ["l"] + [_canon(v) for v in x]
    return str(x)


def plan_counts(cs, roster, base, opened=None, base_extras_catalog=None,
                base_fert_catalog=None):
    """Pending counts for display (badges, status lines): the real
    changes the build would make against base, not counting no-op rule
    rows. Without a base, falls back to raw record counts (an upper
    bound; the review shows the exact number)."""
    if base is None:
        return {
            "dials": len(cs.dials),
            "relations": sum(len(e.guids) for e in cs.rels.values()),
            "extras": len(cs.extras),
            "fertility": len(cs.fert),
        }
    rows, totals = plan(cs, roster, base, opened, base_extras_catalog,
                       base_fert_catalog)
    return totals
