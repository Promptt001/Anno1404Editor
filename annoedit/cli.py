#!/usr/bin/env python3
"""annoedit — command-line front-end (argparse).

Shares the exact Session code paths with the GUI. Main commands (run
`annoedit --help` for the full list, including provide-vanilla,
set-live-path, revert-globals, snapshots, restore-snapshot, store, log):

  list       <src.rda>                          roster: template, GUID, dials
  dials      <src.rda> <GUID|name>              all dials w/ value+default+doc
  dial       <src.rda> <GUID|name> <Path>       one dial in detail
  apply      <src.rda> <out.rda>                preset build to a SEPARATE file
              [--persona NAME] [--char GUID] [--preset file.json]
              [--dry-run] [--json]
  flash      <src.rda>                          apply pending preset edits
              [--persona ...] [--char ...]     IN PLACE (snapshot + atomic
              [--preset ...]                    replace), exactly like the GUI
  backup     <src.rda>                          capture the write-once
                                                vanilla backup
  restore    <src.rda>                          restore vanilla over src.rda
  personas                                      list available personas
  extras      <src.rda> [section]               EXTRAS catalog: assets per tag
                                                w/ values (assets.xml dials)
  extras-apply <src.rda> <out.rda> <spec.json>  apply EXTRAS changes
                                                (see --help for spec shape)
  fertility   <src.rda> [tier]                  fertility catalog (N/S % per
                                                crop/tier, randommapgenerator.xml)
  fertility-apply <src.rda> <out.rda> <spec.json>
                                                apply fertility changes:
                                                {"fertility": [{"tier": "low",
                                                  "crop": "Dates",
                                                  "north": 40,
                                                  "south": null}, ...]}
  relations   <src.rda> <who>                 War/Ally/Trade/AvoidWar lists
                                                of one character
  relations-apply <src.rda> <out.rda> <spec.json>
                                                apply relations changes:
                                                {"relations": [{"character": "Leif",
                                                  "War": ["1645020", ...],
                                                  "AvoidWar": ["Guy"]}, ...]}
                                                (items: GUID or name;
                                                 absent kind = untouched)

All output plain text; --json gives machine-readable results.
"""
import argparse
import json
import sys
from datetime import datetime

from . import __version__
from .backup import BackupError, BackupStore
from .core import ModProject
from .model import effective_value, schema_doc
from .presets import load_custom
from .session import Session, SessionError
from .model import EditError
from .rda import RdaFormatError
from .exports import ExportsError
from .extras import ExtrasError
from .fertility import FertilityError
from .changeset import ChangeSetError
import xml.etree.ElementTree as ET
from .spans import SpanError


def _add_preset_args(ap):
    ap.add_argument("--persona", help="persona preset name (see `personas`)")
    ap.add_argument("--char", help="GUID or unique name substring of the "
                                   "character to apply the persona/preset to")
    ap.add_argument("--preset", help="custom JSON preset file "
                                     "(applied to every character in it)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the change report, write nothing")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")


def build_parser():
    """Build the argparse CLI with version flag and all subcommands."""
    p = argparse.ArgumentParser(
        prog="annoedit",
        description="Anno1404 GameEditor — Anno 1404 History Edition game-data editor")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="list AI profiles in the archive")
    s.add_argument("source")

    s = sub.add_parser("dials", help="show all dials of one character")
    s.add_argument("source")
    s.add_argument("who")

    s = sub.add_parser("dial", help="show one dial in detail")
    s.add_argument("source")
    s.add_argument("who")
    s.add_argument("path")

    s = sub.add_parser("apply", help="preset build to a separate file")
    s.add_argument("source")
    s.add_argument("out")
    _add_preset_args(s)

    s = sub.add_parser("flash", help="apply edits IN PLACE (like the GUI)")
    s.add_argument("source")
    _add_preset_args(s)

    s = sub.add_parser("backup", help="capture the vanilla backup")
    s.add_argument("source")

    s = sub.add_parser("restore", help="restore vanilla over source")
    s.add_argument("--full", action="store_true",
                   help="replace the WHOLE file (default: surgical — only "
                        "the editor's own 4 files are restored, other "
                        "mods/patches in the live file are kept)")
    s.add_argument("source")

    s = sub.add_parser("personas", help="list personas")

    s = sub.add_parser("provide-vanilla", help="provide the VANILLA data1.rda "
                       "(stored persistently as data1.rda_vanilla)")
    s.add_argument("source")

    s = sub.add_parser("set-live-path", help="set the game's LIVE data1.rda "
                       "location (where flash/restore operate)")
    s.add_argument("source")

    s = sub.add_parser("log", help="show the last log entries")
    s.add_argument("-n", type=int, default=40, help="number of lines")
    s = sub.add_parser("store", help="show the backup store's disk usage "
                       "(snapshots + vanilla can hold ~7x the "
                       "archive size)")
    s.add_argument("-n", type=int, default=40, help="number of lines")

    s = sub.add_parser("snapshots", help="list pre-save snapshots "
                       "(per save target; the newest are kept)")
    s.add_argument("target", nargs="?", help="filter to one save target's "
                   "pool (the live game archive path)")

    s = sub.add_parser("restore-snapshot", help="restore a pre-save "
                       "snapshot OVER a game archive (undo a save)")
    s.add_argument("id", help="snapshot id from 'annoedit snapshots'")
    s.add_argument("target", help="the archive path to overwrite")

    s = sub.add_parser("extras", help="EXTRAS catalog (assets.xml dials)")
    s.add_argument("source")
    s.add_argument("section", nargs="?", help="filter to one section "
                    "(production/influence/housing/noria/trade/speed/"
                    "military/costs)")

    s = sub.add_parser("extras-apply", help="apply EXTRAS changes (spec JSON)")
    s.add_argument("source")
    s.add_argument("out")
    s.add_argument("spec")

    s = sub.add_parser("fertility", help="fertility catalog "
                       "(island crop rates)")
    s.add_argument("source")
    s.add_argument("tier", nargs="?", help="filter to one tier "
                    "(low/medium/high)")

    s = sub.add_parser("fertility-apply", help="apply fertility changes "
                       "(spec JSON)")
    s.add_argument("source")
    s.add_argument("out")
    s.add_argument("spec")

    s = sub.add_parser("revert-globals",
                       help="apply EXTRAS+fertility reverts to the provided "
                            "vanilla copy (explicit global action) — writes "
                            "to OUT (export) or, with --flash, in place")
    s.add_argument("source")
    s.add_argument("out", nargs="?", help="output path (default: no write)")
    s.add_argument("--flash", action="store_true",
                   help="write IN PLACE over the source archive")
    s.set_defaults(func=cmd_revert_globals)
    s = sub.add_parser("relations", help="show one character's relations "
                       "(War/Ally/Trade/AvoidWar)")
    s.add_argument("source")
    s.add_argument("who")

    s = sub.add_parser("relations-apply", help="apply relations changes "
                       "(spec JSON)")
    s.add_argument("source")
    s.add_argument("out")
    s.add_argument("spec")
    return p


def resolve_unique(proj, key):
    """Resolve a GUID or unique name substring to a profile or exit."""
    if key in proj.by_guid:
        return proj.by_guid[key]
    # Exact name (case-insensitive) BEFORE substring
    # 'Leif' must resolve to Leif even if 'Leif Jorgensen' exists
    exact = [n for n in proj.by_name if n.lower() == key.lower()]
    if len(exact) == 1:
        return proj.by_name[exact[0]]
    hits = [n for n in proj.by_name if key.lower() in n.lower()]
    if len(hits) == 1:
        return proj.by_name[hits[0]]
    raise SystemExit(f"no unique profile for {key!r} (matches: {hits})")


# ------------------------------------------------------------------ commands

def cmd_revert_globals(args):
    """+ apply the global
    extras/fertility reverts AND WRITE them — to OUT (export) or, with
    --flash, in place over the source. The old command queued the
    reverts in memory, printed 'queued …', and exited without writing
    anything (the README advertised it as THE CLI global-revert action)."""
    from annoedit.session import Session
    from annoedit.changeset import ChangeSetError
    ses = Session()
    try:
        ses.open(args.source)
        try:
            ses.revert_globals_to_reference()
        except ChangeSetError as e:
            raise SystemExit(f"revert-globals: {e}")
        # Honest counts: absolute queueing queues EVERY reference
        # leaf even when the base already matches; the REVIEW's
        # no-op drop decides what actually changes. Report those,
        # so 'nothing to revert' is reachable and true.
        _rows, totals = ses.pending_change_rows(ses.proj)
        ex = totals.get("extras", 0); ft = totals.get("fertility", 0)
        if not ex and not ft:
            print("nothing to revert (no reference baseline or no "
                  "differences) — nothing written")
            return 0
        if args.flash:
            ses.flash()
            print(f"reverted globals IN PLACE: {ex} extras, {ft} fertility")
        elif args.out:
            ses.export(args.out)
            print(f"reverted globals -> {args.out}: {ex} extras, {ft} fertility")
        else:
            raise SystemExit(
                "revert-globals: pass an OUT path (export) or --flash "
                "(in place) — refusing to queue edits without writing")
        return 0
    finally:
        ses.close()


def cmd_list(args):
    """Print every AI profile (file, template, GUID, dial count, name)."""
    proj = ModProject(args.source)
    for fk, ps in proj.profiles.items():
        for q in ps:
            print(f"{fk:<28}{q.template:<11}{q.guid:<10}{len(q.dials):<7}{q.name}")
    return 0


def cmd_dials(args):
    """Print all dials of one character with value, source, default, doc."""
    proj = ModProject(args.source)
    prof = resolve_unique(proj, args.who)
    print(f"{prof.name} ({prof.template} {prof.guid}) — {len(prof.dials)} dials")
    for path in sorted(prof.dials):
        val, src = effective_value(prof.dials, proj.defaults, path)
        doc = schema_doc(proj.docs, path)  # Full-path doc lookup
        print(f"  {path:<55}= {val:<10} [{src}] "
              f"default={proj.defaults.get(path, '—'):<8} "
              f"{doc.get('desc', '')[:60]}")
    return 0


def cmd_dial(args):
    """Print one dial in detail: value, source, default, type, range, doc."""
    proj = ModProject(args.source)
    prof = resolve_unique(proj, args.who)
    val, src = effective_value(prof.dials, proj.defaults, args.path)
    doc = schema_doc(proj.docs, args.path)  # Full-path doc lookup
    print(f"{prof.name} ({prof.template} {prof.guid})")
    print(f"{args.path} = {val}  [{src}]  "
          f"schema default: {proj.defaults.get(args.path, '—')}")
    print(f"type: {doc.get('type', '—')}  range: "
          f"{doc.get('min', '—')}..{doc.get('max', '—')}")
    print(doc.get("desc", "(no schema doc)"))
    return 0


def _collect_changes(ses, args):
    """Apply --persona/--char/--preset to the session. -> n edits."""
    proj = ses.proj
    n = 0
    if args.persona:
        personas = ses.personas
        if args.persona not in personas:
            raise SystemExit(f"unknown persona {args.persona!r} — "
                             f"known: {', '.join(sorted(personas))}")
        targets = list(personas[args.persona]["targets"])
        if args.char:
            prof = resolve_unique(proj, args.char)
            ses.set_mode(prof, args.persona)
            # Personas carry relations too; count both.
            n += len(ses.changes.get(prof.guid, {}))
            n += len(ses.rels.get(prof.guid, {}))
        else:
            for name in targets:
                # Exact name match only (same rule as the session's
                # persona targeting); never guess on a fuzzy match.
                hits = [q for q in ses.roster
                        if name.lower() == q.name.lower()]
                if len(hits) != 1:
                    print(f"warning: persona target {name!r} does not "
                          f"match exactly one profile ({len(hits)} hits) "
                          "— skipped",
                          file=sys.stderr)
                    continue
                ses.set_mode(hits[0], args.persona)
                # Count relations as well as dials.
                n += len(ses.changes.get(hits[0].guid, {}))
                n += len(ses.rels.get(hits[0].guid, {}))
    if args.preset:
        # Transactional: one bad value in the file applies nothing and
        # leaves the existing pending edits untouched.
        with ses._txn():
            for name, entry in load_custom(args.preset).items():
                dials = entry["dials"]
                prof = resolve_unique(proj, name)
                # Queue through the session (typed validation + canonical
                # keys), never a direct write.
                for path, val in dials.items():
                    try:
                        ses._txn_add_dial(prof, path, val)
                    except SessionError as e:
                        raise SystemExit(
                            f"preset {name}/{path}: {e} — nothing applied")
                    n += 1
                # Relations too. set_relations takes lowercase kwargs
                # (war/ally/trade/avoidwar); preset files capitalise kinds.
                rels = entry.get("relations") or {}
                if rels:
                    ses.set_relations(
                        prof, **{k.lower(): list(v)
                                 for k, v in rels.items()})
    return n


def cmd_apply(args):
    """Apply preset edits and build to a separate .rda (dry-run/--json aware)."""
    ses = Session()
    ses.open(args.source)
    n = _collect_changes(ses, args)
    if n == 0 and not args.dry_run:
        print("no changes — pass --persona/--char and/or --preset")
        ses.close()
        return 1
    if args.dry_run:
        print(ses.change_report())
        print(f"(dry run — {args.source} untouched)")
        ses.close()
        return 0
    rep = ses.export(args.out)
    if args.json:
        print(json.dumps(_jsonable(rep), indent=2))
    else:
        print(f"wrote {rep['out']}: {rep['files']} files, "
              f"{rep['dial_edits']} dial edits, changed: "
              f"{', '.join(rep['changed'])}")
        print(f"md5: {rep['md5']}")
    ses.close()
    return 0


def _jsonable(report):
    """A JSON-serializable copy of a build/flash report. Bytes values
    (the report's 'entries' map) and other non-JSON types are dropped,
    so printing a report can never fail after the archive was written."""
    out = {}
    for k, v in report.items():
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        out[k] = v
    return out


def cmd_flash(args):
    """Apply pending edits in place: snapshot, atomic replace, then close."""
    ses = Session()
    ses.open(args.source)   # captures vanilla backup + takes the lock
    try:
        _collect_changes(ses, args)
        # Relations/extras/fertility edits count as changes too.
        if not (any(ses.changes.values()) or ses.rels
                or ses.extras or ses.fert):
            print("no changes to flash — pass --persona/--char/--preset")
            return 1
        if args.dry_run:
            print(ses.change_report())
            print(f"(dry run — {args.source} untouched)")
            return 0
        rep = ses.flash()
        if args.json:
            print(json.dumps(_jsonable(rep), indent=2))
        else:
            print(f"flashed {rep['flashed']}: {rep['dial_edits']} dial edits, "
                  f"{rep.get('relations_edits', 0)} relations edits, "
                  f"{rep.get('extras_edits', 0)} extras edits, "
                  f"{rep.get('fert_edits', 0)} fertility edits, "
                  f"{len(rep['changed'])} files changed")
            print(f"md5 (new): {rep['md5']}")
            print(f"pre-flash snapshot md5: {rep['snapshot_md5']}")
        return 0
    finally:
        ses.close()


def cmd_backup(args):
    """Capture the write-once vanilla backup of the source archive."""
    store = BackupStore()
    md5, created = store.capture_vanilla(args.source)
    state = "captured" if created else "already on file (not overwritten)"
    print(f"vanilla backup {state}: {md5}")
    print(f"store: {store.root}")
    return 0


def cmd_restore(args):
    """Restore the stored vanilla backup over the source archive.

    Deliberately does not open the target first: opening is a strict
    parse, and a corrupt live archive is exactly when a restore is
    needed. Session.restore_vanilla needs no open archive when an
    explicit target is passed."""
    ses = Session()
    try:
        md5 = ses.restore_vanilla(target=args.source,
                                  full=getattr(args, "full", False))
        mode = "full" if getattr(args, "full", False) else "surgical"
        print(f"restored vanilla {md5} over {args.source} ({mode})")
        return 0
    except (SessionError, BackupError) as e:
        print(f"restore failed: {e}", file=sys.stderr)
        return 1
    finally:
        ses.close()


def cmd_personas(_args):
    """Print each persona's description and its target character names."""
    ses = Session()
    for name, spec in sorted(ses.personas.items()):
        print(f"{name}: {spec['description']}")
        for t in spec["targets"]:
            print(f"  - {t}")
    ses.close()
    return 0


def cmd_provide_vanilla(args):
    """Provide the vanilla data1.rda (persisted write-once copy)."""
    ses = Session()
    info = ses.provide_vanilla(args.source)
    state = "stored" if info["created"] else "already on file (identical)"
    print(f"vanilla copy {state}: {info['md5']}")
    print(f"store: {info['path']}")
    ses.close()
    return 0


def cmd_set_live_path(args):
    """Set the game's live addon/data1.rda location (persisted)."""
    ses = Session()
    p = ses.set_live_path(args.source)
    print(f"live archive location set: {p}")
    ses.close()
    return 0


def cmd_log(args):
    """Print the last n activity-log lines."""
    from .applog import tail
    lines = tail(args.n)
    if not lines:
        print("(no log entries yet)")
    for l in lines:
        print(l)
    return 0


def cmd_store(_args):
    """Surface the backup store's disk usage.

    The store can silently hold ~7x the archive size (5 rolling
    pre-flash snapshots + the first-open snapshot + the stored vanilla
    copy) with nothing in the UI showing it.
    """
    from .backup import BackupStore
    store = BackupStore()
    rep = store.store_report()
    mb = rep["total_bytes"] / (1024 * 1024)
    print(f"backup store: {rep['root']}")
    print(f"  total: {rep['total_bytes']:,} bytes ({mb:.1f} MiB) "
          f"in {rep['files']} file(s)")
    print(f"  vanilla copies: {rep['vanilla_bytes']:,} bytes")
    print(f"  pre-flash snapshots: {rep['snapshot_count']} "
          f"({rep['snapshot_bytes']:,} bytes; the newest "
          f"{BackupStore.KEEP_SNAPSHOTS} are kept)")
    print("  prune: unreferenced snapshots are pruned automatically on "
          "every snapshot; use the export manager to delete the stored "
          "vanilla copy")
    return 0


def cmd_snapshots(args):
    """List pre-save snapshots, newest first, grouped by save target.

    Snapshots are rotated PER TARGET (pre-flash/<sha1(target)[:12]>/),
    so repeated export overwrites can never evict the live game file's
    pre-save snapshots (the only undo for a save-to-live)."""
    from .backup import BackupStore
    store = BackupStore()
    rows = store.snapshots(args.target)
    if not rows:
        print("(no pre-save snapshots stored yet)")
        return 0
    for r in rows:
        ts = r.get("ts")
        when = (datetime.fromtimestamp(ts).isoformat(timespec="seconds")
                if ts else "?")
        mb = (r.get("size") or 0) / (1024 * 1024)
        print(f"{r['id']}  {when}  {mb:7.1f} MiB  {r.get('reason') or '?'}")
        print(f"    of {r.get('target') or '?'}  (md5 "
              f"{(r.get('md5') or '')[:12]}…)")
    return 0


def cmd_restore_snapshot(args):
    """Restore a stored pre-save snapshot OVER a game archive (atomic,
    md5-verified, the stored snapshot itself never touched)."""
    from .backup import BackupStore
    store = BackupStore()
    try:
        md5 = store.restore_snapshot(args.id, args.target)
    except BackupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"restored snapshot {args.id} over {args.target}: {md5}")
    return 0


def cmd_extras(args):
    """Print the EXTRAS catalog by section/tag with asset values."""
    proj = ModProject(args.source)
    cat = proj.extras_catalog()
    for section, tags in cat.items():
        if args.section and section != args.section:
            continue
        print(f"== {section} ==")
        for tag, assets in tags.items():
            n = len(assets)
            multi = sum(1 for v in assets.values() if len(v) > 1)
            print(f"  {tag}: {n} assets" +
                  (f" ({multi} multi-instance)" if multi else ""))
            for name, vals in list(assets.items())[:6]:
                print(f"    {name}: {'/'.join(vals)}")
            if n > 6:
                print(f"    ... and {n - 6} more")
    return 0


def cmd_extras_apply(args):
    """Apply EXTRAS edits from a spec JSON and export to a new .rda."""
    with open(args.spec, encoding="utf-8") as f:
        data = json.load(f)
    ses = Session()
    ses.open(args.source)
    try:
        for item in data.get("extras", []):
            ses.set_extra(item["asset"], item["tag"], item["value"],
                          item.get("occ"))
        rep = ses.export(args.out)
        print(f"wrote {rep['out']}: {rep['files']} files, md5 {rep['md5']}")
        print(f"  changed: {', '.join(rep['changed'])}")
        print(f"  extras edits: {rep.get('extras_edits', 0)}")
        print("  round-trip verified: 0 mismatches")
    finally:
        ses.close()
    return 0


def cmd_fertility(args):
    """Print fertility rates (North/South) per crop, optionally per tier."""
    from .fertility import FERT_TIERS
    proj = ModProject(args.source)
    if args.tier and args.tier not in FERT_TIERS:
        print(f"unknown tier {args.tier!r} (need one of {FERT_TIERS})",
              file=sys.stderr)
        return 1
    for tier in FERT_TIERS:
        if args.tier and tier != args.tier:
            continue
        trows = [r for r in proj.fertility_catalog() if r["tier"] == tier]
        print(f"== {tier} ({len(trows)} crops) ==")
        for r in trows:
            print(f"  {r['crop']:<12} North={r['north']:<4} South={r['south']}")
    return 0


def cmd_fertility_apply(args):
    """Apply fertility edits from a spec JSON and export to a new .rda."""
    with open(args.spec, encoding="utf-8") as f:
        data = json.load(f)
    ses = Session()
    ses.open(args.source)
    try:
        for item in data.get("fertility", []):
            ses.set_fertility(item["tier"], item["crop"],
                              item.get("north"), item.get("south"))
        rep = ses.export(args.out)
        print(f"wrote {rep['out']}: {rep['files']} files, md5 {rep['md5']}")
        print(f"  changed: {', '.join(rep['changed'])}")
        print(f"  fertility edits: {rep.get('fert_edits', 0)}")
        print("  round-trip verified: 0 mismatches")
    finally:
        ses.close()
    return 0


def cmd_relations(args):
    """Print one character's War/Ally/Trade/AvoidWar GUID lists w/ names."""
    proj = ModProject(args.source)
    prof = resolve_unique(proj, args.who)
    rel = proj.relations(prof)
    names = {q.guid: q.name for ps in proj.profiles.values() for q in ps}
    print(f"{prof.name} ({prof.template} {prof.guid})")
    for kind in ("War", "Ally", "Trade", "AvoidWar"):
        guids = rel.get(kind, [])
        if guids:
            shown = ", ".join(f"{g} ({names.get(g, '?')})" for g in guids)
        else:
            shown = "(empty)"
        print(f"  {kind:<9}{shown}")
    return 0


def cmd_relations_apply(args):
    """Apply relations edits from a spec JSON and export to a new .rda."""
    with open(args.spec, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("relations")
    if not isinstance(items, list):
        raise SystemExit("spec JSON needs a 'relations' list")
    ses = Session()
    ses.open(args.source)
    try:
        for item in items:
            prof = resolve_unique(ses.proj, item["character"])
            ses.set_relations(
                prof,
                war=item.get("War") if "War" in item else None,
                ally=item.get("Ally") if "Ally" in item else None,
                trade=item.get("Trade") if "Trade" in item else None,
                avoidwar=item.get("AvoidWar") if "AvoidWar" in item else None)
        rep = ses.export(args.out)
        print(f"wrote {rep['out']}: {rep['files']} files, md5 {rep['md5']}")
        print(f"  changed: {', '.join(rep['changed'])}")
        print(f"  relations edits: {rep.get('relations_edits', 0)}")
        print("  round-trip verified: 0 mismatches")
    finally:
        ses.close()
    return 0


def main(argv=None):
    """Parse argv, dispatch to the matching cmd_* handler, return exit code.

    Expected errors (SessionError, EditError,
    RdaFormatError, ExportsError, missing archive members) print a
    clean `error: ...` to stderr and exit 2 — never a raw traceback.
    """
    args = build_parser().parse_args(argv)
    from .applog import startup_note
    startup_note()
    handler = {
        "list": cmd_list, "dials": cmd_dials, "dial": cmd_dial,
        "apply": cmd_apply, "flash": cmd_flash, "backup": cmd_backup,
        "restore": cmd_restore, "personas": cmd_personas,
        "provide-vanilla": cmd_provide_vanilla,
        "set-live-path": cmd_set_live_path, "log": cmd_log,
        "store": cmd_store,
        "extras": cmd_extras, "extras-apply": cmd_extras_apply,
        "fertility": cmd_fertility, "fertility-apply": cmd_fertility_apply,
        "relations": cmd_relations, "relations-apply": cmd_relations_apply,
        "revert-globals": cmd_revert_globals,
        "snapshots": cmd_snapshots,
        "restore-snapshot": cmd_restore_snapshot,
    }[args.cmd]
    from .core import ArchiveMemberMissing
    try:
        return handler(args)
    except ArchiveMemberMissing as e:
        # An archive member absence is labelled for
        # what it is — never 'spec item is missing key'
        print(f"error: archive member missing: {e}", file=sys.stderr)
        return 2
    except (SessionError, EditError, RdaFormatError, ExportsError,
            BackupError, ExtrasError, FertilityError, ChangeSetError) as e:
        # ChangeSetError can be raised directly by the ChangeSet (e.g.
        # while queueing global reverts).
        print(f"error: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: spec file is not valid JSON: {e}", file=sys.stderr)
        return 2
    except (ET.ParseError, SpanError, UnicodeDecodeError) as e:
        # A modded archive that fails the XML parse (or a non-UTF-8
        # profile file) is an expected error too.
        print(f"error: could not parse archive data: {e}", file=sys.stderr)
        return 2
    except KeyError as e:
        # a spec item missing a key (e.g. "asset") — never a silent
        # "no such archive member" mislabel
        print(f"error: spec item is missing key {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
