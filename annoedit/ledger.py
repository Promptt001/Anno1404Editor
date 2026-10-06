"""ledger — the write ledger: what THIS tool wrote to a target, as facts.

Without a record of its own writes, a tool cannot tell "a value I wrote
earlier and the user has since cleared" apart from "a value another mod
wrote". The ledger removes that guesswork.

The ledger records, per SAVE TARGET (next to that target's pre-flash
snapshot manifest, under pre-flash/<sha1(target)[:12]>/ledger.json), the
set of keys a successful commit WROTE, with the value written and the
BASE value it replaced. On the next save to that target, every
differing key classifies as a FACT, not a guess:

  * mine, now cleared — the key is in the ledger, the session has NO
    pending edit on it, and the opened archive endorses the recorded
    base (opened value == recorded base): the user cleared the edit,
    so the save REVERTS the key to the recorded base value.
  * mine, but changed — the key is in the ledger and live no longer
    holds what we wrote: someone else touched it after our write. That
    is a REAL conflict the save must surface, never overwrite silently.
  * foreign — the key is not in the ledger: another mod. KEPT by the
    replay (this is what "keep other mods" actually means).

The endorsement test is what separates "cleared edit" from "the write
is the session's working baseline": after an in-place save the session
reloads the written file, so the opened value equals the WRITTEN value,
not the recorded base — no revert is queued and the saved edits persist
across in-place saves. In the save-to-live, clear, save-again sequence the
opened archive still carries the base, so the revert is queued and the
second save restores the exact original value.

Limit: the ledger reverts REPLACE-shaped writes
only. A write that INSERTED a leaf absent from the opened archive
cannot be reverted by writing a value back — the engine has no
delete-leaf operation; those keys are reported as not auto-revertable.
Restoring a snapshot remains the exact undo for those.
"""

import json
import os

from .backup import _sha1_prefix

LEDGER_NAME = "ledger.json"

# Plan section names (annoedit.plan) — the ledger keys kinds by them.
AI_PROFILE = "AI profile"
AI_RELATIONS = "AI relations"
EXTRAS = "EXTRAS"
FERTILITY = "FERTILITY"


def ledger_path(store, target):
    """Path of the per-target ledger file inside the backup store."""
    return os.path.join(store.root, "pre-flash", _sha1_prefix(target),
                        LEDGER_NAME)


def load(store, target):
    """The per-target ledger as {(kind, key-tuple): {base, written}}.

    Returns {} when no ledger exists yet (first save) or the file is
    unreadable/corrupt (best effort: the ledger sharpens drift
    classification but is never a hard dependency).
    """
    p = ledger_path(store, target)
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                kind, rest = k.split(":", 1)
                key = tuple(json.loads(rest))
            except (ValueError, TypeError):
                continue
            if isinstance(v, dict) and "base" in v and "written" in v:
                out[(kind, key)] = {"base": v["base"], "written": v["written"]}
    return out


def _enc_key(kind, key):
    return f"{kind}:{json.dumps(list(key), separators=(',', ':'))}"


def normalize_base(kind, old):
    """A plan row's display 'old' -> the structured base for the ledger.

    Relations rows display ', '-joined GUID lists; fertility rows
    display 'N=x S=y' — the ledger stores them structured so the
    revert queue can consume them directly.
    """
    if kind == AI_RELATIONS:
        if old in (None, "", "(empty)"):
            return []
        return [g.strip() for g in str(old).split(",") if g.strip()]
    if kind == FERTILITY:
        out = {}
        for part in str(old or "").split():
            k, _sep, v = part.partition("=")
            if k == "N" and v != "":
                out["north"] = int(v) if str(v).isdigit() else v
            elif k == "S" and v != "":
                out["south"] = int(v) if str(v).isdigit() else v
        return out
    return old


def update(store, target, applied_rows, clear=False):
    """Post-commit bookkeeping for one target's ledger.

    applied_rows: [ResolvedChange] the commit actually WROTE (their
    'old' is the base value replaced, 'new' the value written). Rows
    with rule='revert' DROP their key from the ledger (the tool wrote
    a recorded base back — it no longer owns that key). clear=True
    wipes the ledger (a restore returned the target to a state the
    tool's writes no longer describe).

    Best effort, called AFTER the irreversible commit: no failure here
    may ever surface as a save failure over an already-written file.
    Returns the new ledger dict (or None when nothing could be written).
    """
    try:
        led = {} if clear else load(store, target)
        if not clear:
            for r in applied_rows:
                if r.rule == "revert":
                    led.pop((r.kind, tuple(r.key)), None)
                    continue
                led[(r.kind, tuple(r.key))] = {
                    "base": normalize_base(r.kind, r.old),
                    "written": r.new}
        p = ledger_path(store, target)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        payload = {_enc_key(kind, tuple(key)): val
                   for (kind, key), val in led.items()}
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        return led
    except OSError:
        return None


def cleared_keys(led, cs, opened, roster):
    """Ledger keys that are CLEARED edits, endorsed by the opened archive.

    This is the only endorsement classifier: drift classification and
    the session's revert queueing both use it, so they cannot disagree.

    A ledger key is a cleared edit iff the session has NO pending edit
    on it AND the opened archive's value equals the recorded BASE (the
    pre-write value): the user opened the archive the tool wrote to,
    cleared the edit, and the next save reverts the key to the base.
    When the opened value equals the WRITTEN value instead (an in-place
    save reloaded the written file; a re-open of the saved archive), the
    write is the session's working baseline — NOT a cleared edit, no
    revert.

    -> ({(kind, key): rec}, [unrevertable display strings]) where an
    INSERT-shaped write (recorded base '(absent)' / an empty relations
    list) lands in unrevertable — the engine has no delete-leaf
    operation; restore-snapshot stays its exact undo.
    """
    if not led or opened is None:
        return {}, []
    out = {}
    unrevert = []
    names = {q.guid: q.name for q in roster} if roster else {}
    for (kind, key), rec in sorted(led.items(), key=lambda kv: str(kv[0])):
        if kind == AI_PROFILE:
            guid, path = key
            if key in cs.dials:
                continue
            prof = opened.by_guid.get(guid)
            if prof is None:
                continue
            from .model import effective_value
            cur, _src = effective_value(prof.dials, opened.defaults, path)
            cur_disp = str(cur) if cur is not None else "(absent)"
            if cur_disp != str(rec["base"]):
                continue
            if cur_disp == "(absent)":
                unrevert.append(f"{names.get(guid, guid)} / {path}")
            else:
                out[(kind, key)] = rec
        elif kind == AI_RELATIONS:
            guid, relkind = key
            if key in cs.rels:
                continue
            prof = opened.by_guid.get(guid)
            if prof is None:
                continue
            base_list = rec["base"] if isinstance(rec["base"], list) else []
            cur = opened.relations(prof).get(relkind, ())
            if [str(g) for g in cur] != [str(g) for g in base_list]:
                continue
            if not base_list:
                unrevert.append(f"{names.get(guid, guid)} / {relkind}")
            else:
                out[(kind, key)] = rec
        elif kind == EXTRAS:
            if key in cs.extras:
                continue
            asset, tag, occ = key
            vals = None
            for section in opened.extras_catalog().values():
                fam = section.get(tag)
                if fam and fam.get(asset):
                    vals = fam[asset]
                    break
            cur = None
            if vals:
                if occ is None:
                    cur = vals[0]
                elif occ < len(vals):
                    cur = vals[occ]
            cur_disp = str(cur) if cur is not None else "(absent)"
            if cur_disp != str(rec["base"]):
                continue
            if cur_disp == "(absent)":
                unrevert.append(f"{asset} / {tag}")
            else:
                out[(kind, key)] = rec
        elif kind == FERTILITY:
            if key in cs.fert:
                continue
            tier, crop = key
            recb = rec["base"] if isinstance(rec["base"], dict) else None
            if recb is None:
                continue
            row = next((r for r in opened.fertility_catalog()
                        if (r.get("tier"), r.get("crop")) == (tier, crop)),
                       None)
            if row is None:
                continue
            if (str(row.get("north")) != str(recb.get("north"))
                    or str(row.get("south")) != str(recb.get("south"))):
                continue
            out[(kind, key)] = rec
    return out, unrevert
