#!/usr/bin/env python3
"""ops — pure worker functions for the background (non-Tk) thread.

Every long-running operation the GUI runs in a worker thread (open,
flash, restore, drift check, named export) is split into two phases:

  * a PURE phase, in this module: frozen inputs -> a result object. It
    touches no Session attribute, so the Tk thread may keep editing
    while this runs without any chance of a race.
  * a COMMIT phase, on the Session (install_open / apply_flash_result
    / apply_restore_result), run on the Tk thread ONLY.

What "pure" means here, concretely:
  * No Session attribute is read or written. Inputs are frozen at
    prepare time on the Tk thread: a ChangeSet SNAPSHOT (a copied
    dict), the opened archive's entries dict (never mutated after
    open() — every build seeds from a copy), plain strings and lists.
  * Shared objects passed in (BackupStore / ExportStore / Settings)
    are used for their FILE effects only (locking, snapshotting,
    writing); their in-memory state is thread-safe for that use.
  * The applog is append-only and never raises — safe from any thread.

The synchronous Session.open / flash / restore_vanilla / target_drift /
export_named wrappers run the same pure functions inline on the calling
thread and then the same commit methods: one code path each, so the
build/commit logic is never duplicated.
"""
import hashlib
import os
import tempfile

from .applog import log as _log
from .backup import BackupError, fsync_dir, md5_of
from .core import ARCHIVE_MEMBERS, ASSETS_FILE, FERT_FILE, ModProject
from .model import SCHEMA_FILE, EditError, effective_value
# The surgical-restore set: the 4 EDIT members PLUS the schema
# defaults file (properties.xml). The effective value of every
# omitted dial falls back to a schema default, so a modded
# properties.xml silently changes effective AI behaviour while a
# surgical restore keeps it - 'restored to vanilla' would still
# carry non-vanilla effective behaviour. properties.xml is
# RESTORE-ONLY (never an edit target - the engine reads it).
RESTORE_MEMBERS = tuple(ARCHIVE_MEMBERS) + (SCHEMA_FILE,)
from . import plan as plan_mod
from .rda import read_rda, read_rda_with_md5, write_rda


def _fnum(x):
    """Float(x) or None (the hardened never-easier numeric compare)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class DriftUnavailable(Exception):
    """The drift check could not read/parse the live target (drift
    fails CLOSED). The GUI must show this as 'could not compare', never
    as 'no drift'."""


class SessionError(Exception):
    """Raised when a session operation is attempted in a bad state.
    (Defined here — session.py re-exports it — because the pure workers
    raise the SAME error type as the sync wrappers; callers catch one.)"""


def protected_paths(backup_root, exports_root):
    """The protected-path policy: files the tool must never overwrite,
    derived from the two store roots:
      * anything inside the backup store (pre-flash snapshots, the
        first-open vanilla backup, session.lock);
      * anything inside the exports store (data1.rda_vanilla, named
        exports, their .meta.json sidecars);
      * the vanilla copy's recorded md5 metadata file itself.
    -> a predicate(path) -> bool. Lives here (not on the Session) so the
    pure commit path (commit_archive / restore_build) can refuse a
    protected target without touching Session state."""
    def norm(p):
        return os.path.normcase(os.path.realpath(p))
    broot = norm(backup_root)
    eroot = norm(exports_root)
    def predicate(path):
        p = norm(path)
        if p == broot or p.startswith(broot + os.sep):
            return True
        if p == eroot or p.startswith(eroot + os.sep):
            return True
        return False
    return predicate


def _refuse_protected(store, exports_store, target, what):
    """Raise unless target is safe to overwrite. 'what' names the
    operation for the error message (e.g. 'commit_archive')."""
    is_prot = protected_paths(store.root, exports_store.root)
    if is_prot(target):
        raise SessionError(
            f"refusing to write {target} — it is a protected app file "
            "(the stored vanilla copy, a backup, or the export store); "
            f"the {what} path never writes there")


def _live_path_from_settings():
    """The persisted live addon/data1.rda path from settings (or None).
    Kept a tiny local helper: the CLI export route reads the same setting
    the Session exposes, without constructing a Session."""
    try:
        from .appsettings import Settings
        p = Settings().get("live_path")
        return p if p and os.path.isfile(p) else None
    except Exception:
        return None


def export_guard(store, exports_store, out_path, source_path=None):
    """The export-output policy every CLI apply-family command goes
    through before building:
      * refuse protected paths (the stores)
      * refuse the OPEN source (the CLI 'apply' builds FROM source —
        writing over it is the in-place job of 'flash', which carries
        the snapshot/lock/mode protocol);
      * refuse the configured LIVE path ('use flash' instead).
    -> the guarded absolute path. An existing ordinary file is allowed
    (an overwrite the user asked for) but the caller must then
    route the write through commit_archive (snapshot + md5 guard +
    mode preservation) — see session export/CLI apply."""
    p = os.path.abspath(out_path)
    _refuse_protected(store, exports_store, p, "export")
    if source_path and os.path.normcase(p) == os.path.normcase(
            os.path.abspath(source_path)):
        raise SessionError(
            f"refusing to write {p} — it is the SOURCE archive itself; "
            "use 'annoedit flash' for in-place saves (it snapshots and "
            "locks first)")
    live = _live_path_from_settings()
    if live and os.path.normcase(p) == os.path.normcase(os.path.abspath(live)):
        raise SessionError(
            f"refusing to write {p} — it is the configured live game "
            "archive; use 'annoedit flash' (it snapshots and locks first)")
    return p



# --------------------------------------------------------------- results

class LoadedOpen:
    """load_archive() result — everything install_open() needs to swap
    the session to the newly opened archive (nothing is applied to the
    Session until install_open runs on the Tk thread)."""

    def __init__(self, path, proj, md5, backup_msg, lock,
                 vanilla_baseline, vanilla_stamp, same_path):
        self.path = path
        self.proj = proj
        self.md5 = md5
        self.backup_msg = backup_msg
        self.lock = lock                  # entered flock (None: same-path reload)
        self.vanilla_baseline = vanilla_baseline
        self.vanilla_stamp = vanilla_stamp
        self.same_path = same_path


class FlashResult:
    """flash_build() result — the build report plus the frozen snapshot
    it was built from (the subtractive clear needs it) and, for an
    in-place flash, the freshly re-read project."""

    def __init__(self, report, cs, in_place, new_proj, source_path=None):
        self.report = report
        self.cs = cs                      # the frozen ChangeSet snapshot
        self.in_place = in_place
        self.new_proj = new_proj          # re-read project (in-place only)
        # The archive the session had open when the build was dispatched.
        # The GUI's stale-result guard compares it against the CURRENT
        # source_path in the done callback: if the user opened another
        # archive while the 30-60 s build ran, the commit's in-place
        # proj reload is skipped instead of swapping the session back to
        # the OLD archive (single-flight makes this unreachable in the
        # normal GUI flow; it remains the safety net for any path that
        # bypasses _run_bg).
        self.source_path = source_path


class DriftResult(tuple):
    """Target_drift result. IS the six-field
    drift tuple (n_dials, n_relations, n_extras, n_fert, n_chars,
    foreign) — subclassing tuple keeps every existing unpack/index/
    isinstance/equality call site working — plus up to 5 example drift
    keys PER SURFACE for the drift dialog (the dialog lists
    examples, not just counts)."""

    _EXAMPLES = ("dial_keys", "rel_keys", "extra_keys", "fert_keys")

    def __new__(cls, n_dials, n_relations, n_extras, n_fert, n_chars,
                foreign, dial_keys=(), rel_keys=(), extra_keys=(),
                fert_keys=(), kept_dials=0, kept_relations=0,
                kept_extras=0, kept_fert=0, unmodelled=(),
                live=None, live_md5=None, mine_cleared_dials=0,
                mine_cleared_relations=0, mine_cleared_extras=0,
                mine_cleared_fert=0):
        self = super().__new__(cls, (n_dials, n_relations, n_extras,
                                     n_fert, n_chars, foreign))
        self.mine_cleared_dials = mine_cleared_dials
        self.mine_cleared_relations = mine_cleared_relations
        self.mine_cleared_extras = mine_cleared_extras
        self.mine_cleared_fert = mine_cleared_fert
        self.dial_keys = tuple(dial_keys)
        self.rel_keys = tuple(rel_keys)
        self.extra_keys = tuple(extra_keys)
        self.fert_keys = tuple(fert_keys)
        # The tuple fields count real CONFLICTS: live values the save
        # would overwrite without the user having seen them. The kept_*
        # counts are differences the replay preserves (shown for
        # information). `unmodelled` lists tracked members whose bytes
        # differ in ways no modeled surface (dials/relations/extras/
        # fertility) explains, i.e. another mod editing inside the
        # editor's files; they are kept too, but the user is told.
        self.kept_dials = kept_dials
        self.kept_relations = kept_relations
        self.kept_extras = kept_extras
        self.kept_fert = kept_fert
        self.unmodelled = tuple(unmodelled)
        # The consent anchor for the save: the live project plus the md5
        # of the exact live bytes this drift was computed against. For
        # save-to-live the GUI passes live_md5 as expected_md5, so
        # commit_archive refuses if the live file changed between the
        # review and the save. These are attributes rather than tuple
        # fields so tuple unpacking at call sites stays unchanged.
        # `live` must be a parsed ModProject (or None): the review dialog
        # relies on its by_guid index.
        if live is not None and not isinstance(live, ModProject):
            raise TypeError("DriftResult.live must be a ModProject or None")
        self.live = live
        self.live_md5 = live_md5
        return self

    def __bool__(self):
        # Falsy when there is nothing to report (a plain 6-tuple would
        # always be truthy). An unmodelled warning alone makes it truthy.
        return any(self) or bool(self.unmodelled)

    def __repr__(self):
        return (f"DriftResult(dials={self[0]}, rels={self[1]}, "
                f"extras={self[2]}, fert={self[3]}, "
                f"chars={self[4]}, foreign={self[5]})")


class RestoreResult:
    """restore_build() result — the restored md5 plus, for an in-place
    restore, the freshly re-read project and the frozen ChangeSet
    snapshot the restore started from (apply_restore_result needs it so
    edits queued or changed during the restore stay pending)."""

    def __init__(self, vmd5, in_place, new_proj, cs=None, unmodelled=(),
                 new_md5="", degraded_to_full=None):
        self.vmd5 = vmd5
        self.in_place = in_place
        self.new_proj = new_proj
        self.cs = cs
        # Md5 of the bytes actually written; '' falls
        # back to vmd5 at the apply site (raw-copy restores are equal).
        self.new_md5 = new_md5
        # Tracked members in the target that differed from vanilla in
        # ways no modeled surface explains (another mod editing inside the
        # editor's files). They are restored anyway, but reported.
        self.unmodelled = tuple(unmodelled)
        # A surgical restore that fell back to FULL
        # because the live file could not be read back — the restore
        # happened, but untracked members (other mods) may be gone.
        self.degraded_to_full = degraded_to_full


# drift helpers

def _extras_conflicts(opened_proj, live_proj, cs, led=None):
    """assets.xml EXTRAS: ledger-driven classification of every live
    difference the session has no pending edit on, plus the 3-way
    replay conflicts for keys it does.

    A pending edit is a real conflict iff the live value at that
    occurrence differs from both the pending value and the opened value
    (the replay would overwrite a live value the user never saw). A
    pending edit whose value already sits in live is a no-op.

    Ledger classification for a differing leaf with NO pending edit:
      * in the ledger, live == written, opened == recorded base ->
        MINE, NOW CLEARED: the save reverts it (informational);
      * in the ledger otherwise -> MINE, BUT CHANGED (a real conflict:
        someone else touched it after our write);
      * not in the ledger -> FOREIGN, kept by the replay.
    -> (n_conflict, [up to 5 example keys], n_mine_cleared, n_kept).
    """
    base_cat = opened_proj.extras_catalog()
    live_cat = live_proj.extras_catalog()
    led = led or {}
    n = 0
    keys = []
    cleared = 0
    kept = 0
    for section in set(base_cat) | set(live_cat):
        bsec = base_cat.get(section, {})
        lsec = live_cat.get(section, {})
        for tag in set(bsec) | set(lsec):
            bvals = bsec.get(tag, {})
            lvals = lsec.get(tag, {})
            for asset in set(bvals) | set(lvals):
                bv = bvals.get(asset)
                lv = lvals.get(asset)
                if bv == lv:
                    continue          # no difference there at all
                pending_hit = False
                for key, e in cs.extras.items():
                    if key[0] != asset or key[1] != tag:
                        continue
                    # The comparison is PER OCCURRENCE, at the same
                    # granularity as the key: a pending edit to occ #0
                    # only conflicts when the live value AT THAT
                    # OCCURRENCE differs (and live differs from opened
                    # there). A live change at occ #1 alone is NOT a
                    # conflict for an occ-#0 edit — the whole-list
                    # compare counted it as one and spuriously BLOCKED
                    # the save.
                    occ = e.occ if e.occ is not None else 0
                    live_val = lv[occ] if (lv and occ < len(lv)) else None
                    base_val = bv[occ] if (bv and occ < len(bv)) else None
                    if str(base_val) == str(live_val):
                        continue   # this occurrence matches — not our fight
                    pending_hit = True
                    if str(live_val) != str(e.value):
                        # A pending REVERT of the tool's own earlier
                        # write is not a conflict (the ledger proves
                        # live == what WE wrote; the review showed the
                        # revert row).
                        rec_r = led.get(("EXTRAS", key))
                        if (getattr(e, "rule", None) == "revert"
                                and rec_r is not None
                                and str(live_val) == str(rec_r["written"])
                                and str(e.value) == str(rec_r["base"])):
                            cleared += 1
                            break
                        n += 1        # the replay overwrites live here
                        if len(keys) < 5:
                            keys.append(f"{asset} / {tag}")
                    # else: live == pending — a no-op for the replay.
                    break
                if pending_hit:
                    continue
                # No pending decision on (asset, tag): the LEDGER
                # decides between mine-cleared / mine-changed / foreign.
                for occ in range(max(len(bv or ()), len(lv or ()))):
                    b_v = bv[occ] if (bv and occ < len(bv)) else None
                    l_v = lv[occ] if (lv and occ < len(lv)) else None
                    if str(b_v) == str(l_v):
                        continue
                    rec = led.get(("EXTRAS", (asset, tag, occ)))
                    if rec is None:
                        kept += 1       # foreign -> kept by the replay
                        continue
                    if (str(l_v) == str(rec["written"])
                            and str(b_v) == str(rec["base"])):
                        cleared += 1    # mine, now cleared -> reverted
                    else:
                        n += 1          # mine, but changed -> conflict
                        if len(keys) < 5:
                            keys.append(f"{asset} / {tag}")
    return n, keys, cleared, kept


def _extras_diffs(opened_proj, live_proj):
    """The KEPT side — leaves where OPENED != LIVE with no
    pending edit (the replay seeds from live, so these survive)."""
    base_cat = opened_proj.extras_catalog()
    live_cat = live_proj.extras_catalog()
    n = 0
    for section in set(base_cat) | set(live_cat):
        bsec = base_cat.get(section, {})
        lsec = live_cat.get(section, {})
        for tag in set(bsec) | set(lsec):
            bvals = bsec.get(tag, {})
            lvals = lsec.get(tag, {})
            for asset in set(bvals) | set(lvals):
                if bvals.get(asset) != lvals.get(asset):
                    n += 1
    return n, []


def _fert_conflicts(opened_proj, live_proj, cs, led=None):
    """Fertility — LEDGER-DRIVEN, per side, same shape as
    _extras_conflicts. -> (n_conflict, [up to 5 keys], n_mine_cleared,
    n_kept)."""
    base_rows = {(r["tier"], r["crop"]): (r["north"], r["south"])
                 for r in opened_proj.fertility_catalog()}
    live_rows = {(r["tier"], r["crop"]): (r["north"], r["south"])
                 for r in live_proj.fertility_catalog()}
    led = led or {}
    n = 0
    keys = []
    cleared = 0
    kept = 0
    for key in set(base_rows) | set(live_rows):
        if base_rows.get(key) == live_rows.get(key):
            continue          # no difference at all
        e = cs.fert.get(key)
        ln, ls = live_rows.get(key) or (None, None)
        bn, bs = base_rows.get(key) or (None, None)
        if e is not None:
            # PER SIDE, at the key's own granularity: a side is only
            # 'our fight' when the OPENED side differs from the live
            # side (a value the user has NOT seen change). A pending
            # North edit is not a conflict when only live SOUTH differs
            # (a whole-pair compare counted it as one and spuriously
            # BLOCKED the save); nor when live NORTH still holds the
            # opened value (the normal replay). A side whose live value
            # equals the pending value is a no-op for the replay.
            n_conf = False
            if e.north is not None and str(bn) != str(ln):
                if str(e.north) != str(ln):
                    n_conf = True   # the replay overwrites an unseen value
            if e.south is not None and str(bs) != str(ls):
                if str(e.south) != str(ls):
                    n_conf = True
            if n_conf:
                # A pending REVERT of the tool's own earlier write is
                # not a conflict (the ledger proves live == what WE
                # wrote; the review showed the revert row).
                rec_r = led.get(("FERTILITY", key))
                if (getattr(e, "rule", None) == "revert"
                        and rec_r is not None
                        and isinstance(rec_r["written"], dict)
                        and isinstance(rec_r["base"], dict)):
                    w_ok = True
                    b_ok = True
                    for side, b_v, l_v in (("north", bn, ln),
                                           ("south", bs, ls)):
                        if str(b_v) != str(l_v):
                            pend_v = getattr(e, side)
                            if str(l_v) != str(rec_r["written"].get(side)) \
                                    or str(pend_v) != \
                                    str(rec_r["base"].get(side)):
                                w_ok = False
                    if w_ok and b_ok:
                        cleared += 1
                        continue
                n += 1
                if len(keys) < 5:
                    keys.append(f"{key[0]} / {key[1]}")
            continue
        # No pending edit on the pair: the LEDGER decides per side.
        rec = led.get(("FERTILITY", key))
        for side, b_v, l_v in (("north", bn, ln), ("south", bs, ls)):
            if str(b_v) == str(l_v):
                continue
            if rec is None:
                kept += 1           # foreign -> kept by the replay
                continue
            recb = rec["base"] if isinstance(rec["base"], dict) else {}
            if (isinstance(rec["written"], dict)
                    and str(l_v) == str(rec["written"].get(side))
                    and str(b_v) == str(recb.get(side))):
                cleared += 1        # mine, now cleared -> reverted
            else:
                n += 1              # mine, but changed -> conflict
                if len(keys) < 5:
                    keys.append(f"{key[0]} / {key[1]}")
    return n, keys, cleared, kept


def _fert_diffs(opened_proj, live_proj):
    """The KEPT side — (tier, crop) entries where
    OPENED != LIVE with no pending edit (kept by the replay)."""
    base_rows = {(r["tier"], r["crop"]): (r["north"], r["south"])
                 for r in opened_proj.fertility_catalog()}
    live_rows = {(r["tier"], r["crop"]): (r["north"], r["south"])
                 for r in live_proj.fertility_catalog()}
    n = 0
    for key in set(base_rows) | set(live_rows):
        if base_rows.get(key) != live_rows.get(key):
            n += 1
    return n, []


# ------------------------------------------------------------ open

def load_vanilla_baseline(exports_store, cached_baseline, cached_stamp):
    """Load the stored vanilla copy as the reference baseline (pure).

    -> (baseline ModProject or None, stamp). Best effort: any failure
    (no stored copy, unreadable) -> (None, None); the caller falls back
    to plain pending-clearing for 'vanilla' mode. The cache short-cut
    keeps re-opens instant while the stored file is unchanged."""
    try:
        p = exports_store.vanilla_path
        if not (exports_store.has_vanilla_copy() and os.path.isfile(p)):
            return None, None
        st = os.stat(p)
        stamp = (st.st_size, st.st_mtime_ns)
        if cached_baseline is not None and cached_stamp == stamp:
            return cached_baseline, cached_stamp
        return ModProject(p), stamp
    except Exception as e:   # logged, so a '—' in the GUI's Vanilla
        # column always has a recorded reason
        _log("vanilla_baseline_failed", error=repr(e))
        return None, None


def _sweep_stale_temps(rda_path, extra_dirs=()):
    """Remove crash-orphaned temp files next to the archive (and any
    extra directories, e.g. the live game directory). Call ONLY while
    the caller HOLDS the store session lock: every writer path takes
    that lock, so any matching temp is stale by construction.
    Patterns match what the writers create (.annoedit-*.tmp,
    .annoedit-*.verifytmp, .ce_pack_*.tmp) plus names used by earlier
    releases (.flashbuild-*.rda, <name>.verifytmp, .flashbuild-*.tmp).
    Best-effort: any failure is ignored.
    Returns the list of removed basenames."""
    import glob
    dirs = [os.path.dirname(rda_path) or "."]
    dirs += [os.path.dirname(d) or "." for d in extra_dirs if d]
    seen = set()
    cands = []
    for d in dirs:
        if d in seen:
            continue
        seen.add(d)
        try:
            cands += (glob.glob(os.path.join(d, ".annoedit-*.tmp"))
                      + glob.glob(os.path.join(d, ".annoedit-*.verifytmp"))
                      + glob.glob(os.path.join(d, ".ce_pack_*.tmp"))
                      + glob.glob(os.path.join(d, ".flashbuild-*.rda"))
                      + glob.glob(os.path.join(d, ".flashbuild-*.tmp"))
                      + glob.glob(os.path.join(d, os.path.basename(rda_path)
                                               + ".verifytmp")))
        except OSError:
            continue
    removed = []
    for pth in cands:
        try:
            os.unlink(pth)
            removed.append(os.path.basename(pth))
        except OSError:
            continue
    return removed


def load_archive(rda_path, store, exports_store, settings, same_path,
                 cached_baseline=None, cached_stamp=None):
    """The pure phase of Session.open(): parse, md5, capture the
    first-open snapshot, take the store flock (a NEW archive only),
    parse the vanilla baseline, persist 'last_opened'.

    Frozen inputs: rda_path (str), the stores, settings. The cached
    baseline/stamp come from the session's cache (prepare time). May
    raise SessionError/BackupError; on any failure the caller's
    Session is untouched.
    -> LoadedOpen (install via Session.install_open, Tk thread only).
    """
    rda_path = os.path.abspath(rda_path)
    if not os.path.isfile(rda_path):
        raise SessionError(f"no such archive: {rda_path}")
    # Parse and hash from one read (read_rda_with_md5), strictly: any
    # archive opened here may later be written back in place, and a
    # lenient open that skipped a corrupt block would produce a save
    # missing those members (which a round-trip check against the
    # already-damaged entries could not notice).
    entries, new_md5 = read_rda_with_md5(rda_path, strict=True)
    new_proj = ModProject(rda_path, entries=entries)
    if same_path:
        # A reload of the same path keeps the existing lock and takes no
        # backup; install_open resets the pending state.
        baseline, stamp = load_vanilla_baseline(
            exports_store, cached_baseline, cached_stamp)
        return LoadedOpen(rda_path, new_proj, new_md5,
                          "reloaded (pending edits dropped)", None,
                          baseline, stamp, True)
    # take the flock BEFORE anything else; on BackupError the caller's
    # session keeps its own lock (another instance holds the store)
    new_lock = store.session_lock()
    try:
        new_lock.__enter__()
    except BackupError:
        raise
    # Sweep stale temp files a crash may have left (they can be hundreds
    # of MB). Only while holding the store lock, so another instance's
    # in-flight temps are never touched. The live game directory is
    # swept too, since save-to-live temps land there.
    _sweep_stale_temps(rda_path, extra_dirs=(_live_path_from_settings(),))
    backup = "no vanilla backup"
    try:
        try:
            bmd5, created = store.capture_vanilla(rda_path)
            backup = (f"first-open snapshot "
                      f"{'captured' if created else 'already on file'} "
                      f"(unverified, {bmd5[:12]}…) — 'Restore Vanilla' "
                      f"prefers your provided vanilla copy")
        except BackupError as e:              # non-fatal: warn, keep working
            backup = f"WARNING: first-open snapshot failed: {e}"
        # the persistent vanilla copy is provided EXPLICITLY only
        # (provide_vanilla) — never captured implicitly on open
        if exports_store.has_vanilla_copy():
            backup += "; vanilla copy on file as data1.rda_vanilla"
        try:
            settings.set("last_opened", rda_path)
        except Exception:   # settings must never block opening
            pass
        baseline, stamp = load_vanilla_baseline(
            exports_store, cached_baseline, cached_stamp)
        return LoadedOpen(rda_path, new_proj, new_md5, backup, new_lock,
                          baseline, stamp, False)
    except BaseException:
        # anything failing between lock-take and return must not leak
        # the new lock — release it; the caller's session stays intact
        try:
            new_lock.__exit__(None, None, None)
        except Exception:
            pass
        raise


# ------------------------------------------------------------ drift

def _b_derived_anchor(text, pb, path):
    """The insert_after anchor implied by B's own sibling order: the tag
    of the leaf's immediately preceding element sibling in B's asset
    text. None when the leaf is the first child or anything cannot be
    located; the caller then replays an un-anchored insert."""
    from .model import _locate_values
    from .spans import child as _child, index as _index
    try:
        span = _locate_values(text, pb)
        if span is None:
            return None
        vtext = text[span[0]:span[1]]
        root = _index(vtext)
        vs = _child(root, "Values")
        if len(vs) != 1:
            return None
        cur = vs[0]
        for tag in path.split("/")[:-1]:
            kids = _child(cur, tag)
            if len(kids) != 1:
                return None
            cur = kids[0]
        kids = _child(cur, path.split("/")[-1])
        if len(kids) != 1:
            return None
        prev = None
        for c in cur.children:
            if c is kids[0]:
                break
            prev = c
        return prev.tag if prev is not None else None
    except Exception:
        return None


def _modeled_member_diff(proj_a, proj_b, member):
    """Residual compare: is the byte difference of `member` between
    proj_a and proj_b fully explained by the editor's modeled surfaces
    (dials, relations, extras, fertility)?
    -> bool: True = an unmodelled residual remains (another mod edited
    one of the 4 tracked members outside the modeled surfaces).

    Method: take member A's text, replay onto it every modeled
    difference from A to B (same engines, same keys, same batch shapes),
    then byte-compare with B's text:
      * equal  -> explained (-> False);
      * differ -> residual = unmodelled (-> True).
    A replay step that raises (a key the engine cannot express, a
    leaf present in A but absent in B — the engine has no delete op,
    an occurrence-count change) also reports unmodelled: the engine
    cannot reproduce it. If the leaf-insertion layout differs between
    A and B, the residual compare reports unmodelled: better to report
    than to miss it."""
    from .core import PROFILE_FILES, ASSETS_FILE, FERT_FILE
    rel_to_fk = {rel: fk for fk, rel in PROFILE_FILES.items()}
    fk = rel_to_fk.get(member)
    scratch = None
    try:
        if fk is not None:
            # a profile present in one, gone in the other: structural,
            # the dial engine cannot replay it
            ga = {p.guid for p in proj_a.profiles.get(fk, ())}
            gb = {p.guid for p in proj_b.profiles.get(fk, ())}
            if ga != gb:
                return True
            scratch = ModProject.from_entries(dict(proj_a.entries),
                                             proj_a.source_rda)
            for pa in proj_a.profiles.get(fk, ()):
                pb = proj_b.by_guid[pa.guid]
                changes = {}
                for path, vb in pb.dials.items():
                    va = pa.dials.get(path)
                    if str(va) != str(vb):
                        if va is None:
                            # An A->B insert: anchor it on B's own
                            # sibling order so a mid-list insert in B
                            # replays byte-exactly (an un-anchored
                            # first-child insert would differ and be
                            # misreported as unmodelled).
                            ia = _b_derived_anchor(
                                proj_b.filetexts[pb.filekey], pb, path)
                            changes[path] = (str(vb), ia)
                        else:
                            changes[path] = str(vb)
                for path in pa.dials:
                    if path not in pb.dials:
                        # a leaf A carries that B lacks: no delete op
                        return True
                if changes:
                    scratch.set_dials(scratch.by_guid[pa.guid], changes)
                ra = proj_a.relations(pa)
                rb = proj_b.relations(pb)
                kw = {}
                for kind in ("War", "Ally", "Trade", "AvoidWar"):
                    la = [str(g) for g in ra.get(kind, ())]
                    lb = [str(g) for g in rb.get(kind, ())]
                    if la != lb:
                        kw[kind.lower()] = lb
                if kw:
                    scratch.set_relations(scratch.by_guid[pa.guid], **kw)
        elif member == ASSETS_FILE:
            ca = proj_a.extras_catalog()
            cb = proj_b.extras_catalog()
            if ca != cb:
                scratch = ModProject.from_entries(dict(proj_a.entries),
                                                 proj_a.source_rda)
                for section, tags in cb.items():
                    for tag, assets in tags.items():
                        a_map = ca.get(section, {}).get(tag, {})
                        for asset, vals in assets.items():
                            av = a_map.get(asset)
                            if av == vals:
                                continue
                            if av is None:
                                # A single-occurrence tag B added that A
                                # lacks can be replayed through the insert
                                # path (allow-listed shapes only; anything
                                # else raises and reports unmodelled).
                                # Multi-occurrence inserts cannot be
                                # replayed (occurrences are positional).
                                if len(vals) == 1:
                                    scratch.set_extra(asset, tag,
                                                      str(vals[0]), None)
                                    continue
                                return True
                            if len(vals) != len(av):
                                # Occurrence count changed: positional
                                # occurrences cannot be replayed.
                                return True
                            for i, v in enumerate(vals):
                                if str(av[i]) != str(v):
                                    scratch.set_extra(asset, tag, str(v), i)
                for section, tags in ca.items():
                    for tag, assets in tags.items():
                        b_map = cb.get(section, {}).get(tag, {})
                        for asset in assets:
                            if asset not in b_map:
                                # A carries the tag, B lacks it: no delete
                                return True
        elif member == FERT_FILE:
            ra = {(r["tier"], r["crop"]): r
                  for r in proj_a.fertility_catalog()}
            rb = {(r["tier"], r["crop"]): r
                  for r in proj_b.fertility_catalog()}
            if set(ra) != set(rb):
                return True
            if ra != rb:
                scratch = ModProject.from_entries(dict(proj_a.entries),
                                                 proj_a.source_rda)
                for key, rwb in rb.items():
                    rwa = ra[key]
                    if (rwa["north"] != rwb["north"]
                            or rwa["south"] != rwb["south"]):
                        scratch.set_fertility(key[0], key[1],
                                               north=rwb["north"],
                                               south=rwb["south"])
        else:
            return False
    except Exception:
        # a replay step raised — the engine cannot reproduce this diff
        return True
    if scratch is None:
        # no modeled diff at all: the byte difference IS the residual
        return proj_a.entries[member][0] != proj_b.entries[member][0]
    # Compare the replayed working text with B's member bytes (entries are
    # only rebuilt at build(), so they would still hold the unreplayed
    # text).
    if fk is not None:
        replay = scratch.filetexts[fk].encode("utf-8")
    elif member == ASSETS_FILE:
        replay = scratch.assets_text.encode("latin-1")
    else:
        replay = scratch.fert_text.encode("latin-1")
    return replay != proj_b.entries[member][0]


def drift_check(proj, roster, cs, target, source_path, store=None):
    """The pure phase of Session.target_drift().

    Frozen inputs: the OPENED project (a reference — never mutated after
    open), a frozen roster LIST, a ChangeSet SNAPSHOT, the resolved
    target path. -> DriftResult (a 6-field tuple subclass: n_dials,
    n_relations, n_extras, n_fert, n_chars, foreign) with up to 5
    example keys per surface. Raises DriftUnavailable when the live
    target cannot be read/parsed (fails closed)."""
    if proj is None:
        return None
    target = os.path.abspath(target or "")
    if not target or not os.path.isfile(target):
        return None
    if os.path.normcase(target) == os.path.normcase(source_path):
        return None          # in-place flash: baseline == target
    try:
        # Parse + hash from ONE read — the md5 of the
        # exact blob the drift verdict was computed against (the save's
        # expected_md5, see DriftResult.live_md5).
        live_entries, live_md5 = read_rda_with_md5(target, strict=True)
    except Exception as e:
        raise DriftUnavailable(f"could not compare: {e}")
    # Foreign entries — untracked members that differ between the
    # opened baseline and the live target (another mod, a game patch).
    foreign = sum(
        1 for k in live_entries
        if k not in ARCHIVE_MEMBERS
        and live_entries[k][0] != proj.entries.get(k, (b"",))[0])
    # Cheap byte-gate first — only parse the live archive when a
    # tracked member actually differs from the opened baseline
    diff_files = [f for f in ARCHIVE_MEMBERS
                  if live_entries.get(f) != proj.entries.get(f)]
    if not diff_files:
        if foreign:
            return DriftResult(0, 0, 0, 0, 0, foreign, (), (), (), (),
                               live_md5=live_md5)
        # No differences: still return a (falsy) result carrying live and
        # live_md5, the consent anchor the save needs in this common case.
        # live must be a full ModProject (the review uses its by_guid).
        try:
            live_proj = ModProject(target, entries=live_entries)
        except Exception as e:
            raise DriftUnavailable(f"could not compare: {e}")
        return DriftResult(0, 0, 0, 0, 0, 0, (), (), (), (),
                          live=live_proj, live_md5=live_md5)
    try:
        live = ModProject(target, entries=live_entries)
    except Exception as e:
        raise DriftUnavailable(f"could not compare: {e}")
    # Per-key set logic on canonical maps: O (opened archive), L (live
    # target) and P (pending edits). The save REPLAYS pending edits onto
    # the live members, so for every key where O != L:
    #   * pending and L != P -> CONFLICT: the save would overwrite a live
    #     value the user never saw (counted, examples listed, the GUI
    #     asks before saving);
    #   * pending and L == P -> no-op for this save (not counted);
    #   * not pending        -> classified via the write ledger below.
    # Separately, a tracked member whose bytes differ in ways no modeled
    # surface explains is UNMODELLED (another mod inside the editor's
    # files): kept by the replay, but reported.
    n_dial = n_rel = n_extra = n_fert = 0
    k_dial = k_rel = k_extra = k_fert = 0
    m_dial = m_rel = m_extra = m_fert = 0
    chars = set()
    dial_keys = []
    rel_keys = []
    extra_keys = []
    fert_keys = []
    # The write ledger classifies live differences that have NO pending
    # edit (see annoedit/ledger.py):
    #   * mine, now cleared — ledger key, live == written, opened == the
    #     recorded base: the save reverts it (shown as a revert row;
    #     informational, counted in m_*).
    #   * mine, but changed — ledger key, live != written: someone else
    #     changed it after our write. A real conflict.
    #   * foreign           — not in the ledger: kept by the replay
    #     (counted in k_*).
    from . import ledger as ledger_mod
    led = ledger_mod.load(store, target) if store is not None else {}
    for q in roster:
        live_q = live.by_guid.get(q.guid)
        pend_dial = cs.dial_map(q.guid)
        pend_rel = cs.rel_map(q.guid)
        O = q.dials                       # opened baseline
        L = live_q.dials if live_q is not None else {}
        for k in set(O) | set(L):
            if O.get(k) != L.get(k):
                if k in pend_dial:
                    if str(pend_dial[k]) != str(L.get(k)):
                        # A pending revert of the tool's own earlier
                        # write is not a conflict: the ledger shows live
                        # still holds what we wrote. (dial_map returns
                        # values only; the rule comes from cs.dials.)
                        rec = led.get(("AI profile", (q.guid, k)))
                        pend_rec = cs.dials.get((q.guid, k))
                        if (rec is not None
                                and getattr(pend_rec, "rule", None)
                                == "revert"
                                and str(L.get(k)) == str(rec["written"])
                                and str(pend_dial[k])
                                == str(rec["base"])):
                            m_dial += 1
                            continue
                        # TRUE CONFLICT: the pending edit would OVERWRITE a
                        # live value the user never saw (live != pending).
                        n_dial += 1
                        chars.add(q.name)
                        if len(dial_keys) < 5:
                            dial_keys.append(f"{q.name}: {k}")
                    # else: live == pending, a no-op for the replay.
                    continue
                rec = led.get(("AI profile", (q.guid, k)))
                if rec is not None:
                    if str(L.get(k)) == str(rec["written"]):
                        oprof = proj.by_guid.get(q.guid)
                        cur, _src = effective_value(
                            oprof.dials if oprof is not None else {},
                            proj.defaults, k) if oprof is not None \
                            else (None, None)
                        o_disp = str(cur) if cur is not None else "(absent)"
                        if o_disp == str(rec["base"]):
                            m_dial += 1   # mine, now cleared -> reverted
                            continue
                    n_dial += 1           # mine, but changed -> conflict
                    chars.add(q.name)
                    if len(dial_keys) < 5:
                        dial_keys.append(f"{q.name}: {k} (changed after "
                                         "an earlier save)")
                    continue
                k_dial += 1               # foreign -> kept by the replay
        try:
            # The relations reader raises on a broken/ambiguous
            # structure, so drift fails closed instead of treating the
            # character as having empty lists.
            base_rels = proj.relations(q)
            live_rels = (live.relations(live_q)
                         if live_q is not None else {})
        except EditError as e:
            raise DriftUnavailable(
                f"relations unreadable for {q.name} ({q.guid}): {e}")
        for kind in set(base_rels) | set(live_rels):
            if list(base_rels.get(kind, ())) != list(live_rels.get(kind, ())):
                if kind in pend_rel:
                    if list(pend_rel[kind]) != list(live_rels.get(kind, ())):
                        n_rel += 1       # true conflict
                        chars.add(q.name)
                        if len(rel_keys) < 5:
                            rel_keys.append(f"{q.name}: {kind}")
                    continue
                rec = led.get(("AI relations", (q.guid, kind)))
                if rec is not None:
                    w_list = rec["written"] if isinstance(
                        rec["written"], list) else None
                    b_list = rec["base"] if isinstance(
                        rec["base"], list) else None
                    l_now = [str(g) for g in live_rels.get(kind, ())]
                    b_now = [str(g) for g in base_rels.get(kind, ())]
                    if (w_list is not None and b_list is not None
                            and l_now == [str(g) for g in w_list]
                            and b_now == [str(g) for g in b_list]):
                        m_rel += 1       # mine, now cleared -> reverted
                        continue
                    n_rel += 1           # mine, but changed -> conflict
                    chars.add(q.name)
                    if len(rel_keys) < 5:
                        rel_keys.append(f"{q.name}: {kind}")
                    continue
                k_rel += 1               # foreign -> kept
    if ASSETS_FILE in diff_files:
        n_extra, extra_keys, m_extra, k_extra = _extras_conflicts(
            proj, live, cs, led)
    if FERT_FILE in diff_files:
        n_fert, fert_keys, m_fert, k_fert = _fert_conflicts(
            proj, live, cs, led)
    # True = an unmodelled residual remains after replaying every
    # modeled A->B difference onto A (see _modeled_member_diff).
    try:
        unmodelled = tuple(
            m for m in diff_files
            if _modeled_member_diff(proj, live, m))
    except EditError as e:
        raise DriftUnavailable(f"could not compare: {e}")
    # Kept-only differences are not drift: the replay seeds from live
    # and they survive. Always return a DriftResult so live/live_md5
    # (the consent anchor and review base) are available; a result with
    # nothing to report is falsy, so `if drift:` call sites work.
    if not n_dial and not n_rel and not n_extra and not n_fert \
            and not foreign and not unmodelled:
        return DriftResult(0, 0, 0, 0, len(chars),
                           foreign, dial_keys, rel_keys, extra_keys, fert_keys,
                           kept_dials=k_dial, kept_relations=k_rel,
                           kept_extras=k_extra, kept_fert=k_fert,
                           unmodelled=unmodelled, live=live, live_md5=live_md5,
                           mine_cleared_dials=m_dial,
                           mine_cleared_relations=m_rel,
                           mine_cleared_extras=m_extra,
                           mine_cleared_fert=m_fert)
    return DriftResult(n_dial, n_rel, n_extra, n_fert, len(chars),
                       foreign, dial_keys, rel_keys, extra_keys, fert_keys,
                       kept_dials=k_dial, kept_relations=k_rel,
                       kept_extras=k_extra, kept_fert=k_fert,
                       unmodelled=unmodelled, live=live, live_md5=live_md5,
                       mine_cleared_dials=m_dial,
                       mine_cleared_relations=m_rel,
                       mine_cleared_extras=m_extra,
                       mine_cleared_fert=m_fert)


# ------------------------------------------------------------ build

def build_from_snapshot(base_entries, source_path, cs, out_path,
                        roster=None, expected_plan=None):
    """Apply a SNAPSHOT of the pending changes to a fresh project and
    build+verify it. Working on a frozen copy means later session edits
    can never leak into a build in flight. Seeded from in-memory
    entries, never re-read from disk.

    Byte contract (pinned by the golden-bytes and persona tests): dial
    edits are applied as ONE batch per profile in cs.dial_guids()
    insertion order; relations sorted by (guid, kind); extras sorted by
    (asset, tag, occ); fertility sorted by (tier, crop). Do not sort
    dials and do not apply them one at a time."""
    p = ModProject.from_entries(base_entries, source_path)
    n = 0
    # No-op drop: which rule-marked rows ('reset' from Vanilla /
    # revert-globals, 'harden' from Hardened) are skipped is decided by
    # the change plan (annoedit.plan), the same plan the review showed.
    # It is computed against this project's pristine texts (before any
    # edit below), exactly as Session.change_plan computed the approved
    # hash: same base, same catalogs, same old values.
    if roster is not None:
        _drows, _dtot = plan_mod.plan(
            cs, roster, p, opened=None,
            base_extras_catalog=(p.extras_catalog() if cs.extras else None),
            base_fert_catalog=(p.fertility_catalog() if cs.fert else None))
        if expected_plan is not None and \
                plan_mod.plan_hash(_drows) != expected_plan:
            raise SessionError(
                "the change plan changed since the review (the base "
                "archive changed) — reopen the review and re-approve; "
                "refusing to write a plan the user never saw")
    else:
        _drows = None
    # The plan is the build contract for extras and fertility too: only
    # records whose plan row survived are applied (rule rows that are
    # no-ops, or whose asset/pair is absent from the base, are skipped).
    # Manual rows (rule=None) are never dropped.
    kept_extra_keys = None
    kept_fert_keys = None
    if _drows is not None:
        kept_extra_keys = {r.key for r in _drows if r.kind == plan_mod.EXTRAS}
        kept_fert_keys = {r.key for r in _drows
                          if r.kind == plan_mod.FERTILITY}
    for guid in cs.dial_guids():
        prof = p.by_guid.get(guid)
        if prof is None:
            raise SessionError(f"profile {guid} not in archive — reopen?")
        changes = {}
        for path, e in cs.dial_items(guid):
            # rule-marked no-ops drop per the ONE plan (rule=None
            # manual/persona edits are never dropped — byte pins).
            drop = False
            if e.rule:
                drop = plan_mod.plan_dial_noop(
                    e, p.by_guid.get(guid), p, path)
            if not drop:
                changes[path] = ((e.value, e.insert_after)
                                 if e.insert_after else e.value)
        if not changes:
            continue
        p.set_dials(prof, changes)
        n += len(changes)
    nr = 0
    for (guid, kind), e in sorted(cs.rels.items()):
        prof = p.by_guid.get(guid)
        if prof is None:
            raise SessionError(f"profile {guid} not in archive — reopen?")
        # A rule-marked relations no-op vs the BASE is
        # DROPPED (an empty reference list on a base that LACKS the block
        # would INSERT an empty <War> block — not byte-neutral; a
        # same-list replacement would rewrite a foreign-shaped block for
        # nothing). rule=None (manual/persona) rows are never dropped.
        if e.rule:
            bprof = p.by_guid.get(guid)
            if bprof is not None:
                base_list = [str(g) for g in
                             p.relations(bprof).get(kind, ())]
                if base_list == [str(g) for g in e.guids]:
                    continue
        p.set_relations(prof, **{kind.lower(): list(e.guids)})
        nr += len(e.guids)   # GUID items (kinds stay out of dials)
    nx = 0
    # Replay guard: before applying a pending extras edit to the base
    # (opened archive for in-place saves, live members for save-to-live),
    # verify the leaf still holds what it held at queue time: same
    # occurrence count, same old value. If another mod added a level
    # (e.g. NoriaEndRadius 8/10 -> 6/8/10), occurrence #2 would now be a
    # different leaf, so the save refuses and names the conflict.
    #
    # All guard checks read from one parse of the pristine base text and
    # the edits are applied in one batch (set_extras). revert-globals can
    # queue 1000+ edits, so per-edit re-parsing of the ~9 MB file is not
    # an option. Batch and per-edit application are byte-identical on
    # disjoint leaves (pinned by the equivalence tests).
    if cs.extras:
        from .extras import (find_asset, occurrences, parse_assets,
                              asset_text, set_extras)
        assets = parse_assets(p.assets_text)
        cur_cache = {}
        for (asset, tag, occ), e in sorted(
                cs.extras.items(),
                key=lambda kv: (kv[0][0], kv[0][1],
                                kv[0][2] if kv[0][2] is not None else -1)):
            if e.expected_old is not None or e.occ_count is not None:
                if (asset, tag) not in cur_cache:
                    try:
                        a = find_asset(assets, asset)
                        cur_cache[(asset, tag)] = [
                            m.group(1) for m in
                            occurrences(asset_text(p.assets_text, a), tag)]
                    except Exception as exc:
                        raise SessionError(
                            f"extras replay guard: {asset}/{tag} could "
                            f"not be located in the build base ({exc})")
                cur = cur_cache[(asset, tag)]
                if (e.occ_count is not None
                        and len(cur) != e.occ_count):
                    raise SessionError(
                        f"extras replay conflict: {asset}/{tag} carries "
                        f"{len(cur)} occurrence(s) in the target but your "
                        f"edit was made against {e.occ_count} — another mod "
                        "changed the levels; reopen the archive and re-apply "
                        "your edit; refusing to guess")
                if (e.occ is not None and e.expected_old is not None
                        and (occ >= len(cur)
                             or str(cur[occ]) != str(e.expected_old))):
                    live_v = cur[occ] if occ < len(cur) else "(absent)"
                    raise SessionError(
                        f"extras replay conflict: {asset}/{tag} "
                        f"occurrence #{occ + 1} holds {live_v!r} in the "
                        f"target but your edit replaced "
                        f"{e.expected_old!r} — open the LIVE file "
                        "and re-apply your edit there; refusing to "
                        "overwrite")
        batch = [{"asset": asset, "tag": tag, "value": e.value,
                  "occ": occ}
                 for (asset, tag, occ), e in sorted(
                     cs.extras.items(),
                     key=lambda kv: (kv[0][0], kv[0][1],
                                     kv[0][2] if kv[0][2] is not None
                                     else -1))
                 if kept_extra_keys is None
                 or (asset, tag, occ) in kept_extra_keys]
        p.assets_text, _results = set_extras(p.assets_text, batch)
        p._extras_cat = None
        p.extras_changes.extend(
            {"asset": ed["asset"], "tag": ed["tag"],
             "occ": ed["occ"], "old": r, "new": str(ed["value"])}
            for ed, r in zip(batch, _results))
        nx = len(batch)
    nf = 0
    for (tier, crop), e in sorted(cs.fert.items()):
        if kept_fert_keys is not None and (tier, crop) not in kept_fert_keys:
            continue
        p.set_fertility(tier, crop, e.north, e.south)
        nf += 1
    report = p.build(out_path)
    # The applied PLAN rows ride in the report: the commit's post-
    # bookkeeping (the write ledger) records exactly what THIS build
    # wrote, with the base values it replaced — the same rows the
    # review displayed and the plan-hash approved.
    if _drows is not None:
        report["plan_rows"] = _drows
    report["dial_edits"] = n
    report["relations_edits"] = nr
    report["extras_edits"] = nx
    report["fert_edits"] = nf
    return report


# ------------------------------------------------------------ commit

def commit_archive(store, target, build_tmp, expected_md5=None,
                   skip_md5s=(), exports_store=None,
                   snapshot_reason="pre-flash"):
    """The only route that may replace a game file.

    A protected target (anything in the stores) is refused up front.

    Commit protocol: the one irreversible step, os.replace, comes LAST
    among the steps that can fail:
      1. read the old target bytes (for the snapshot), if present;
      2. build+verify into tmp (already done by the caller);
      3. snapshot the old bytes BEFORE the replace (skipped when its
         md5 is already preserved in the store);
      4. os.replace(tmp, target), with the Windows "file is locked,
         close the game (and Steam)" message;
      5. post-commit bookkeeping wrapped in try/except: nothing after
         the replace may raise.
    -> report dict with snapshot_written / snapshot_md5 set.
    """
    if exports_store is not None:
        _refuse_protected(store, exports_store, target, "commit_archive")
    snap = bytearray()
    snap_md5 = ""
    if os.path.isfile(target):
        with open(target, "rb") as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                snap.extend(b)
        snap_md5 = hashlib.md5(snap).hexdigest()
    # Refuse when the target changed on disk since it was opened or
    # reviewed (expected_md5). The session lock only excludes other
    # annoedit instances, not a mod manager or Steam "verify files".
    if expected_md5 and snap_md5 and snap_md5 != expected_md5:
        raise SessionError(
            f"{target} changed on disk since it was opened "
            f"(now {snap_md5[:12]}…, opened {expected_md5[:12]}…) — "
            "reopen the archive, or save as export instead; "
            "refusing to overwrite")
    # The snapshot happens BEFORE the replace. If it fails, abort with
    # the target untouched: replacing without having preserved the old
    # bytes would be irreversible data loss.
    snap_written = False
    if snap:
        # skip_md5s adds caller-known md5s (e.g. the stored vanilla
        # copy's recorded md5). 'written' reports whether a snapshot was
        # actually stored.
        _, snap_written = store.snapshot_pre_flash_bytes(
            bytes(snap), snap_md5,
            skip_md5s=(store.snapshot_skip_md5s(snap_md5)
                       | set(skip_md5s)),
            target=target, reason=snapshot_reason)
    try:
        os.chmod(build_tmp, os.stat(target).st_mode & 0o7777)
    except OSError:
        pass
    try:
        os.replace(build_tmp, target)
    except PermissionError:
        try:
            os.unlink(build_tmp)
        except OSError:
            pass
        raise BackupError(
            f"cannot replace {target}: the file is locked — close "
            "the game (and Steam) first and try again") from None
    fsync_dir(target)
    # Return the md5 of the exact bytes now on disk. The caller stores it
    # as source_md5, so it must describe the file itself (a repacked
    # restore is not byte-identical to the vanilla source).
    h = hashlib.md5()
    with open(target, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    new_md5 = h.hexdigest()
    return {"snapshot_written": snap_written,
            "snapshot_md5": snap_md5,
            "new_md5": new_md5}


def rebase_build(entries, target):
    """The build base for save-to-live: the LIVE target's members
    (tracked and untracked). The pending ChangeSet is replayed onto the
    target's own members by
    build_from_snapshot, because every edit locates its target by
    identity (GUID+path / asset+tag+occ / tier+crop), not by byte
    offset. Everything in live the editor does not overwrite survives
    by construction:
      * untracked members (other mods' files, game patches) — copied;
      * earlier edits inside the 4 tracked members at keys the user is
        not editing: the replay seeds from the live member text, so
        they survive.
    opened entries remain the base when the target is missing or
    unreadable (live_ok=False, reported).
    -> (base_entries, live_ok, live_md5)."""
    if target and os.path.isfile(target):
        # An existing but unreadable target raises: silently falling
        # back to the opened entries would overwrite the live members.
        live_entries, live_md5 = read_rda_with_md5(target, strict=True)
        # The exact md5 of the parsed live blob — the
        # caller passes it as expected_md5 so commit_archive refuses
        # when the file changes between the rebase and the commit.
        return dict(live_entries), True, live_md5
    return dict(entries), False, None


# ------------------------------------------------------------ flash

def flash_build(lock_ctx, store, entries, source_path, build_fn, cs,
                target, in_place, expected_md5=None, exports_store=None,
                roster=None, expected_plan=None):
    """The pure phase of Session.flash(): build from the FROZEN snapshot
    and commit to the target, all under the session write lock.

    build_fn(tmp, cs, base_entries) -> report: the injected build step
    (the sync path passes Session._build, which tests can patch; the
    GUI passes a closure over ops.build_from_snapshot with frozen
    entries, so the worker never touches the Session).
    exports_store: the export store for the protected-target refusal
    in commit_archive (the GUI path passes the session's store).
    -> FlashResult; apply via Session.apply_flash_result (Tk thread).
    """
    with lock_ctx():
        # rebase: untracked members from the TARGET, tracked from
        # opened+edits. In-place flash: target == opened, identical.
        if in_place:
            base, live_ok, live_md5 = dict(entries), True, None
        else:
            base, live_ok, live_md5 = rebase_build(entries, target)
        # Unique temp name, so instances never collide.
        _fd, tmp = tempfile.mkstemp(
            prefix=".annoedit-", suffix=".tmp",
            dir=os.path.dirname(os.path.abspath(target)) or ".")
        os.close(_fd)
        os.unlink(tmp)
        # Optional kwargs are passed only when set: some build_fn
        # implementations take just (tmp, cs, base).
        extra = {}
        if roster is not None:
            extra["roster"] = roster
        if expected_plan is not None:
            extra["expected_plan"] = expected_plan
        try:
            report = build_fn(tmp, cs, base, **extra)
            commit = commit_archive(
                store, target, tmp, exports_store=exports_store,
                # The live blob's md5 from the rebase
                # read — the TOCTOU guard for NOT-in-place saves too.
                expected_md5=expected_md5 or live_md5,
                snapshot_reason="flash")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        report.update(commit)
        # +the GUI/CLI must see live_ok=False and
        # refuse; commit carries new_md5 for the in-place source_md5.
        report["live_ok"] = live_ok
        report["flashed"] = target
        report["in_place"] = in_place
        # THE WRITE LEDGER (post-commit bookkeeping, best-effort —
        # nothing after the irreversible replace may ever surface as
        # a failure over a written file): record what THIS commit wrote
        # per target, with the base values replaced. Revert rows drop
        # their keys (the tool wrote a recorded base back — it no
        # longer owns that key). The ledger is what makes 'save ->
        # clear -> save' exact and lets drift tell the tool's own
        # writes from another mod's.
        from . import ledger as ledger_mod
        report["ledger"] = ledger_mod.update(
            store, target, report.get("plan_rows") or [])
        # Build new_proj from the exact entries the build wrote (from its
        # report), never from a disk re-read: a transient read error
        # after the irreversible replace must not turn a successful save
        # into a reported failure. (`base` is the PRE-edit entry map and
        # must not be used here.)
        new_proj = ModProject(source_path,
                              entries=report.get("entries")) \
            if in_place else None
        _log("flash", path=target, md5=report["md5"][:12],
             dial_edits=report.get("dial_edits", 0),
             relations_edits=report.get("relations_edits", 0),
             extras_edits=report.get("extras_edits", 0),
             fert_edits=report.get("fert_edits", 0),
             snapshot=report.get("snapshot_md5", "")[:12])
        return FlashResult(report, cs, in_place, new_proj,
                          source_path=source_path)


# ------------------------------------------------------------ restore

def restore_source(store, exports_store):
    """(path, md5, label) of the best vanilla source (pure).

    The player-provided data1.rda_vanilla wins: it was supplied
    explicitly as pristine. The auto-backup taken on first open is the
    fallback (it captures whatever was opened first, modded or not)."""
    if exports_store.has_vanilla_copy():
        p = exports_store.vanilla_path
        return p, md5_of(p), "data1.rda_vanilla (your provided copy)"
    if store.has_vanilla:
        m = store._read_manifest()
        return (store.vanilla_path(m["vanilla_md5"]), m["vanilla_md5"],
                "first-open snapshot (unverified — captured on first "
                "open; use 'Provide vanilla…' for a verified copy)")
    raise SessionError("no vanilla copy stored — use 'Provide vanilla…' "
                       "first")


def restore_build(lock_ctx, store, exports_store, target, full,
                  source_path, cs=None):
    """The pure phase of Session.restore_vanilla.

    Surgical by default: only RESTORE_MEMBERS (the 4 edit members plus
    the schema-defaults properties.xml) are restored and untracked live
    content is kept. The stored copy is verified against its recorded
    md5, and a pre-restore snapshot is taken before the replace via
    commit_archive. A protected target is refused up front.
    -> RestoreResult; apply via Session.apply_restore_result."""
    with lock_ctx():
        _refuse_protected(store, exports_store, target, "restore_build")
        src_path, vmd5, _label = restore_source(store, exports_store)
        # Verify the stored copy against its RECORDED md5 before
        # anything touches the game file. When the source is the
        # PROVIDED copy, a missing record is itself an integrity
        # failure (the record is committed before the copy lands),
        # so restore refuses instead of silently skipping the check.
        # The first-open snapshot fallback carries no record by
        # design (labelled unverified) and stays usable.
        provided = src_path == exports_store.vanilla_path
        rec = exports_store.vanilla_copy_md5()
        if provided and rec is None:
            raise SessionError(
                "the stored vanilla copy has no recorded md5 "
                f"({src_path}) — its integrity cannot be verified; "
                "delete and re-provide it via 'Provide vanilla…'")
        if rec is not None and md5_of(src_path) != rec:
            raise SessionError(
                "the stored vanilla copy fails its md5 check "
                f"({src_path}) — it may be corrupt; re-provide it "
                "via 'Provide vanilla…'")
        if os.path.isfile(target) and md5_of(target) == vmd5:
            raise SessionError("archive already IS the stored vanilla "
                               f"({vmd5[:12]}…)")
        van_entries = read_rda(src_path, strict=True)
        unmodelled = []
        degraded_to_full = None
        if full:
            base = dict(van_entries)
        else:
            # Surgical restore: a tracked member is taken from the stored
            # vanilla only when it differs from vanilla; every other
            # member stays exactly as it is in the target. A tracked
            # member that differs in ways no modeled surface explains
            # (another mod editing inside the editor's files) is still
            # restored, since that is what restore means, but reported.
            base = dict(van_entries)
            # An unreadable live target degrades the surgical restore to
            # a FULL one (restoring over a corrupt file is the right call),
            # and that is reported (degraded_to_full + reason) and logged.
            # Read failures and analysis failures are logged separately.
            degraded_to_full = None
            if os.path.isfile(target):
                try:
                    live_entries = read_rda(target, strict=True)
                except Exception as exc:
                    degraded_to_full = (
                        f"the live file could not be read back "
                        f"({exc!r}) — untracked members (other mods) "
                        f"could not be kept")
                else:
                    try:
                        for k in live_entries:
                            if k not in RESTORE_MEMBERS:
                                base[k] = live_entries[k]
                        # Detect unmodelled edits inside the tracked
                        # members of the target.
                        try:
                            live_proj = ModProject(target, entries=live_entries)
                            van_proj = ModProject(src_path, entries=van_entries)
                            # SCHEMA_FILE is restored but never edited,
                            # so a plain byte compare is enough. It is
                            # checked so that a mod changing AI schema
                            # defaults is reported, not silently reverted.
                            if (live_entries.get(SCHEMA_FILE)
                                    != van_entries.get(SCHEMA_FILE)):
                                unmodelled.append(SCHEMA_FILE)
                            for m in ARCHIVE_MEMBERS:
                                if live_entries.get(m) == van_entries.get(m):
                                    continue
                                # True = unmodelled
                                # residual after replaying the modeled
                                # live->vanilla diffs
                                if _modeled_member_diff(live_proj, van_proj, m):
                                    unmodelled.append(m)
                        except Exception as exc:
                            _log("restore_unmodelled_analysis_failed",
                                 target=target, error=repr(exc))
                    except Exception as exc:
                        degraded_to_full = (
                            f"the live file's members could not be "
                            f"carried over ({exc!r}) — untracked members "
                            f"(other mods) could not be kept")
        _fd, tmp = tempfile.mkstemp(
            prefix=".annoedit-", suffix=".tmp",
            dir=os.path.dirname(target) or ".")
        os.close(_fd)
        os.unlink(tmp)
        try:
            # The exports-store vanilla copy's recorded md5 rides in
            # the skip set (snapshot of the vanilla itself adds nothing)
            _vm = (exports_store.vanilla_copy_md5()
                   if exports_store.has_vanilla_copy() else None)
            # A write_rda repack is never byte-identical to the original
            # container. So when the surgical result is data-equivalent to
            # the stored vanilla, copy the pristine vanilla bytes instead
            # of repacking: the restored file is then byte-identical.
            if {k: v[0] for k, v in base.items()} == \
                    {k: v[0] for k, v in van_entries.items()}:
                with open(src_path, "rb") as fin, \
                        open(tmp, "wb") as fout:
                    while True:
                        b = fin.read(1024 * 1024)
                        if not b:
                            break
                        fout.write(b)
                    fout.flush()
                    os.fsync(fout.fileno())
            else:
                write_rda(base, tmp)
            # The in-place restore must assign
            # source_md5 from the md5 of the bytes actually WRITTEN —
            # a repacked surgical restore (untracked members differ)
            # never equals the vanilla source md5.
            commit = commit_archive(store, target, tmp,
                                    exports_store=exports_store,
                                    skip_md5s=(_vm,) if _vm else (),
                                    snapshot_reason="restore")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        in_place = (source_path is not None and
                    os.path.normcase(target) == os.path.normcase(source_path))
        # Same rule as flash — build from the in-memory base, never
        # a post-commit re-read.
        new_proj = ModProject(source_path, entries=dict(base)) \
            if in_place else None
        # The tool's recorded writes no longer describe the restored
        # target, so clear its ledger (best-effort; a failure here never
        # surfaces over a restored file).
        from . import ledger as _ledger_mod
        _ledger_mod.update(store, target, [], clear=True)
        _log("restore_vanilla", path=target, md5=vmd5[:12],
             source=src_path, full=bool(full),
             unmodelled=len(unmodelled),
             degraded_to_full=bool(degraded_to_full))
        # The md5 of the bytes actually written
        # (new_md5), carried separately from vmd5 (the vanilla source
        # md5); apply_restore_result assigns it to source_md5.
        return RestoreResult(vmd5, in_place, new_proj, cs, unmodelled,
                             new_md5=commit.get("new_md5", ""),
                             degraded_to_full=degraded_to_full)


# ------------------------------------------------------------ exports

def export_named_build(lock_ctx, exports_store, entries, source_path,
                       cs, name, note="", roster=None, expected_plan=None):
    """The pure phase of Session.export_named: build the frozen
    pending changes into the exports store as data1.rda_<name>.
    expected_plan: the plan hash the review approved; the build refuses
    when the recomputed plan diverges (the base changed).
    -> report (export_name/export_stored_path set)."""
    with lock_ctx():
        extra = {}
        if roster is not None:
            extra["roster"] = roster
        if expected_plan is not None:
            extra["expected_plan"] = expected_plan
        return exports_store.save_named_build(
            name,
            lambda tmp: build_from_snapshot(
                entries, source_path, cs, tmp, **extra),
            note=note)
