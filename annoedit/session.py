#!/usr/bin/env python3
"""session — the display-free controller between the GUI and the core.

Every button in the GUI maps 1:1 onto a Session method, so the entire
user workflow (open -> auto-backup -> persona/dial edits -> flash ->
restore) is exercisable headless in tests (see tests/test_session.py).

Safety rules are enforced here, not in the GUI:
  * opening an archive captures a write-once vanilla backup first;
  * a session lock is held from open() to close() — a second tool
    instance (or a second session) cannot interleave restore/flash;
  * commit protocol: the game file changes in exactly ONE os.replace,
    and only after a verified build and a stored snapshot.
    ops.commit_archive is the only route: read old target -> build+verify
    tmp -> snapshot the old bytes (if not already preserved) -> single
    replace -> post-commit steps that may never raise. For save-to-live
    the pending edits are replayed onto the live target's own members.
  * restore copies FROM the stored vanilla backup, never onto it.
"""
import contextlib
import json
import os
import string
import tempfile
import threading

from .applog import log as _log
from .appsettings import Settings
from .backup import BackupStore
from .changeset import ChangeSet, ChangeSetError
from .core import ModProject
from . import ledger as ledger_mod
from . import ops
from .ops import SessionError as SessionError  # noqa: compat import site
from .exports import ExportsError, ExportStore
from .extras import ExtrasError
from .extras import set_extra as set_extra_edit
from .fertility import FertilityError
from .fertility import set_fertility as set_fertility_edit
from . import plan as plan_mod
from .model import EditError, effective_value
from .changeset import _READ_ONLY_TYPES as _RO_TYPES
from .presets import HARD_GUIDS, KEY_DIALS, hardened_target

# compat re-export: DriftUnavailable moved to annoedit.ops
# session.DriftUnavailable keeps working (tests import it from here).
DriftUnavailable = ops.DriftUnavailable

# Personas ship inside the package (annoedit/presets/) so a pip install
# carries them. A repo-root presets/ dir is still honoured as a
# development fallback.
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(_PACKAGE_DIR)
REPO_PRESETS = (os.path.join(_PACKAGE_DIR, "presets")
                if os.path.isdir(os.path.join(_PACKAGE_DIR, "presets"))
                else os.path.join(PACKAGE_ROOT, "presets"))


class _NestedLocks:
    """Stack two context managers (RLock + on-disk flock) as one
    re-entrant gate around every session write. __enter__ acquires BOTH
    (the flock may raise BackupError — another tool instance — which
    propagates with the RLock released and no state touched)."""

    def __init__(self, rlock, flock):
        self._rlock = rlock
        self._flock = flock

    def __enter__(self):
        self._rlock.__enter__()
        try:
            self._flock.__enter__()
        except BaseException:
            self._rlock.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        try:
            return self._flock.__exit__(*exc)
        finally:
            self._rlock.__exit__(None, None, None)


def _user_presets_dir():
    """User preset dir, resolved at call time (env-aware).

    ANN0140_PRESETS_DIR > ANN0140_HOME/presets > ~/.anno1404gameeditor/presets.
    Resolving at call time means an ANN0140_HOME set after import still
    redirects every store.
    """
    from .homevar import user_presets_dir
    return user_presets_dir()


def _user_personas_dir():
    """Call-time user personas dir (ANN0140_PERSONAS_DIR > ANN0140_HOME/personas)."""
    from .homevar import user_personas_dir
    return user_personas_dir()


# Import-time snapshot kept for compatibility; code should call
# _user_presets_dir() to get the current value.
USER_PRESETS = _user_presets_dir()


def _persona_dirs():
    """Default persona search dirs.

    The shipped personas plus the user's own personas/ dir. Not
    presets/: that dir holds saved named presets, which must never be
    able to shadow a shipped persona.
    """
    return (REPO_PRESETS, _user_personas_dir())


REL_KINDS = ("War", "Ally", "Trade", "AvoidWar")


def _norm_rels(rels):
    """Normalize a preset 'relations' map -> {kind: [guid str]} or raise.

    Accepts kinds case-insensitively ('war' -> 'War'); only the four
    Relations kinds are legal. Values must be a list of profile GUIDs
    (names are resolved later against the open archive).
    """
    if rels in (None, {}):
        return {}
    if not isinstance(rels, dict):
        raise SessionError("'relations' must be an object keyed by "
                           "War/Ally/Trade/AvoidWar")
    out = {}
    lowered = {k.lower(): k for k in REL_KINDS}
    for kind, guids in rels.items():
        k = lowered.get(str(kind).lower())
        if k is None:
            raise SessionError(f"unknown relations kind {kind!r} "
                               f"(need one of {REL_KINDS})")
        if guids is None:
            continue
        if isinstance(guids, (str, bytes)) or not hasattr(guids, "__iter__"):
            raise SessionError(f"relations {k}: need a list of GUIDs")
        out[k] = [str(g).strip() for g in guids if str(g).strip()]
    return out


def load_personas(dirs=None, errors=None):
    """Persona JSON files -> {label: {'description': str,
    'targets': {char_name: {dial: value}}}}.

    A persona file has top-level 'name' + 'description' and a
    'characters' {name: {'dials': {...}}} map (see presets/*.json).

    Each file is loaded in its own try/except, so one malformed file
    never stops the app; failures are collected in `errors` (a list,
    when passed) for the GUI status bar.
    """
    if dirs is None:
        dirs = _persona_dirs()
    if errors is None:
        errors = []
    out = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(d, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise SessionError("top level is not a JSON object")
                name = data.get("name") or fn[:-5]
                targets = {}
                for cname, spec in (data.get("characters") or {}).items():
                    if not isinstance(spec, dict):
                        continue
                    dials = spec.get("dials")
                    if not isinstance(dials, dict):
                        raise SessionError(
                            f"character {cname!r}: 'dials' must be an object")
                    rels = _norm_rels(spec.get("relations"))
                    if dials or rels:
                        t = {
                            "dials": {k: str(v) for k, v in dials.items()},
                            "relations": rels,
                        }
                        # Optional per-dial 'insert_after' anchor map:
                        # reproduces the verified build's insert positions
                        # (first child is the default).
                        ia = spec.get("insert_after")
                        if isinstance(ia, dict):
                            t["insert_after"] = {k: str(v) for k, v in ia.items()}
                        # Optional per-target 'guid' key: exact targeting
                        # by GUID even if a character name differs.
                        if spec.get("guid"):
                            t["guid"] = str(spec["guid"])
                        targets[cname] = t
                if targets:
                    # A user file whose name collides with a shipped
                    # persona never replaces it (first dir wins, and the
                    # shipped dir comes first in _persona_dirs).
                    if name in out:
                        errors.append(
                            f"{path}: persona {name!r} already defined "
                            "by an earlier dir — skipped")
                        continue
                    out[name] = {"description": data.get("description", ""),
                                 "targets": targets}
            except Exception as e:
                errors.append(f"{path}: {e}")
                continue
    return out


class Session:
    """One open archive + its pending edits + its safety state."""

    def __init__(self, backup_root=None, persona_dirs=None, exports_root=None,
                 settings=None):
        self.store = BackupStore(backup_root)
        self.exports_store = ExportStore(exports_root)
        # Settings (live archive path etc.) are
        # persistent between launches; tests pass a temp-root Settings so
        # the real home dir is never touched.
        self.settings = settings or Settings()
        # Per-file guarded load: a malformed file is reported in
        # preset_load_errors (GUI status bar) instead of stopping startup.
        self.preset_load_errors = []
        # Choice/Flags enumerations from the opened
        # archive's config/game/datasets.xml, lazily parsed, cached per
        # session, RESET on open/close (another archive may differ)
        self._datasets_map = None
        self.personas = load_personas(persona_dirs or _persona_dirs(),
                                       errors=self.preset_load_errors)
        for err in self.preset_load_errors:
            _log("preset-error", detail=err)
        self.proj = None
        self.source_path = None
        self.source_md5 = None
        # ONE canonical validated pending model.
        # changes/rels/extras/fert below are READ-ONLY compat views (
        # no caller writes the dicts directly anymore).
        self.cs = ChangeSet()
        self.modes = {}         # guid -> 'vanilla'|'hardened'|'custom'|persona
        self.vanilla_baseline = None   # ModProject over the stored vanilla copy
        # Dial paths the last set_mode(vanilla) could
        # NOT revert (added by the opened modded archive, absent from
        # vanilla, no schema default) — surfaced by the GUI.
        self._last_unrevertable = []
        # EXTRAS leaves a global revert cannot remove (the tool's
        # own allow-listed INSERTS; no delete op exists)
        self._last_unrevertable_extras = []
        # 'verified' | 'modded' | 'partial' | None (not yet provided)
        # - the known-vanilla registry verdict on the stored copy
        self._vanilla_class = None
        self._lock = None
        # In-process serialization on top of the
        # on-disk flock. The _Flock re-entrancy is per-object and NOT
        # thread-aware — the Tk thread and a _run_bg worker thread share
        # depth, so a worker flash could interleave with a Tk-thread
        # write. A threading.RLock serialises writers within the process
        # while staying re-entrant for nested calls on one thread.
        self._write_mutex = threading.RLock()
        # The threading rule — Session
        # state is mutated ONLY on the UI (Tk) thread. Workers run
        # the PURE annoedit.ops functions on frozen inputs; commits
        # (install_open / apply_flash_result / apply_restore_result)
        # run here. Assertion enabled by ANN0140_STRICT_THREADS=1
        # (the test fixture sets it; read per-instance so a fixture
        # that sets the env after import still counts).
        self.strict_threads = \
            os.environ.get("ANN0140_STRICT_THREADS") == "1"

    # single write gate
    def _write_lock(self):
        """Context manager guarding every session-state or file WRITE.

        Two layers:
        * the in-process threading.RLock (workers vs the Tk thread);
        * the on-disk BackupStore flock, always taken for a write even
          when this session never called open(), so a second, unopened
          Session cannot restore while another instance holds the lock.

        The flock is re-entrant per BackupStore instance, so taking it
        inside an already-open session is harmless. Two Session objects
        over one store root keep separate file handles and still block
        each other, by design.
        """
        rlock = self._write_mutex
        flock = self.store.session_lock()
        return _NestedLocks(rlock, flock)

    def _assert_ui_thread(self):
        """Session mutators run on the
        UI (Tk) thread only — in a real GUI that IS the main thread
        (Tk mainloop); workers must call the pure ops.* functions
        and commit via install_open / apply_*_result."""
        if self.strict_threads and \
                threading.current_thread() is not threading.main_thread():
            raise RuntimeError(
                "Session state mutated off the UI thread — workers run "
                "the pure annoedit.ops functions and commit on the Tk "
                "thread (install_open/apply_*_result)")

    # transactional edits
    @contextlib.contextmanager
    def _txn(self):
        """Transaction around ANY multi-step edit of the pending state.

        SWAP-BASED: self.cs is swapped to a fresh CANDIDATE (a snapshot
        copy) for the duration of the with-block, so every setter that
        edits the pending state (dials, relations, extras, fertility —
        including callers we do not control) automatically lands on the
        candidate. At commit the candidate IS the new self.cs; on ANY
        exception the ORIGINAL ChangeSet is restored untouched — no
        half-applied persona, no lost user edits.

        Nested transactions collapse into the outermost stage.
        self.modes rides along (copied; restored on rollback).
        """
        if getattr(self, "_txn_cs", None) is not None:
            yield                    # nested: edit the OUTER stage directly
            return
        orig_cs, orig_modes = self.cs, self.modes
        stage = orig_cs.snapshot()
        self.cs = stage
        self.modes = dict(orig_modes)
        self._txn_cs = stage
        try:
            yield
            # One bulk dry-run at commit time: the staged dials go through
            # the real engine on the in-memory text before the candidate
            # may become self.cs. A bad path/value fails here, inside the
            # transaction, so the user's existing pending edits survive.
            # Only guids whose dial map changed in this transaction are
            # dry-run, so an extras/relations-only edit stays cheap.
            changed = [g for g in stage.dial_guids()
                       if stage.dial_map(g, anchors=True)
                       != orig_cs.dial_map(g, anchors=True)]
            self._dry_run_dials(changed)
        except BaseException:
            self.cs = orig_cs
            self.modes = orig_modes
            self._txn_cs = None
            raise
        self._txn_cs = None           # commit: stage stays as self.cs

    def _txn_add_dial(self, profile, path, value, insert_after=None,
                      rule=None, from_reference=False):
        """Queue one dial edit (txn-aware). Inside a transaction this
        lands on the candidate stage; outside it edits the live set —
        single edits stay atomic without a transaction .
        rule: None | 'reset' | 'harden' — see DialEdit."""
        return self._queue_dial(profile, path, value, insert_after,
                                rule=rule, from_reference=from_reference)

    def _dry_run_dials(self, guids=None):
        """Dry-run pending dial edits through the real span engine on a
        scratch copy of the in-memory project text (never a disk
        re-read). Catches at queue time, instead of build time: container
        paths ("Military" is a container), list-structure paths
        (Relations/Profiles/Item; use set_relations), ambiguous blocks
        and wrong-depth paths.
        `guids` limits the dry-run to the affected profiles; None = all.
        """
        if not self.proj or not self.cs.dials:
            return
        targets = self.cs.dial_guids() if guids is None else list(guids)
        # pure-function dry-run on the IN-MEMORY file text (apply_changes
        # never mutates the project; a scratch ModProject would re-seed the
        # whole archive per single dial edit — perf class)
        from .model import apply_changes
        for guid in targets:
            prof = self.proj.by_guid.get(guid)
            if prof is None:
                raise SessionError(f"profile {guid} not in archive — reopen?")
            changes = self.cs.dial_map(guid, anchors=True)
            _t, _applied, errors = apply_changes(
                self.proj.filetexts[prof.filekey], prof, changes)
            if errors:
                path, why = errors[0]
                raise SessionError(
                    f"dial {path!r} (profile {guid}) fails the edit engine: "
                    f"{why} — nothing applied")

    def _txn_add_rel(self, profile, kind, guids, rule=None):
        """Queue one relations kind edit (txn-aware, ).
        ChangeSet-level relations validation (dedupe/self-war/cross-kind
        conflict) is translated to SessionError so CLI/GUI handlers and
        the txn rollback treat it like every other refused edit.
        rule: 'reset' for set_mode(vanilla) reverts
        see RelEdit (the build/review drop the no-op vs the base)."""
        try:
            return self.cs.add_rel(profile.guid, kind, guids, rule=rule)
        except ChangeSetError as e:
            raise SessionError(str(e))

    def _txn_drop_profile(self, guid):
        """Drop a profile's pending edits (txn-aware, )."""
        self.cs.drop_profile(guid)

    # compat views (READ-ONLY; write via set_* methods)
    def _view(self, name, builder):
        """Cached dict view, keyed by (identity, version) of the live
        ChangeSet, so it is rebuilt only when an edit actually landed
        (the GUI tables read these once per row). Returned dicts are
        read-only by contract: the Session is the only writer, and a test
        enforces that app code never writes them directly."""
        cs = self.cs
        key = (id(cs), cs.version)
        cache = getattr(self, "_view_cache", None)
        if cache is None or cache[0] != key:
            cache = self._view_cache = (key, {})
        box = cache[1]
        if name not in box:
            box[name] = builder()
        return box[name]

    @property
    def changes(self):
        """{guid: {path: value}} pending dial edits (cached view)."""
        return self._view("changes", self._build_changes_view)

    def _build_changes_view(self):
        out = {}
        for (guid, path), e in self.cs.dials.items():
            out.setdefault(guid, {})[path] = e.value
        return out

    @property
    def rels(self):
        """{guid: {kind: [guid]}} pending relations edits (cached view)."""
        return self._view("rels", self._build_rels_view)

    def _build_rels_view(self):
        out = {}
        for (guid, kind), e in self.cs.rels.items():
            out.setdefault(guid, {})[kind] = list(e.guids)
        return out

    @property
    def extras(self):
        """{(asset, tag, occ): value} pending extras edits (cached view)."""
        return self._view("extras",
                          lambda: {k: e.value for k, e in self.cs.extras.items()})

    @property
    def fert(self):
        """{(tier, crop): (north, south)} pending fertility edits (view)."""
        return self._view("fert", lambda: {k: (e.north, e.south)
                                           for k, e in self.cs.fert.items()})

    def _load_vanilla_baseline(self):
        """Load the stored vanilla copy as the 'back to vanilla'
        baseline (pure ops.load_vanilla_baseline; best effort —
        any failure leaves None and the GUI falls back to plain
        pending-clearing for 'vanilla' mode)."""
        self.vanilla_baseline, self._vanilla_stamp = \
            ops.load_vanilla_baseline(
                self.exports_store, self.vanilla_baseline,
                getattr(self, "_vanilla_stamp", None))

    # ------------------------------------------------------------ open/close

    def open(self, rda_path):
        """Load the archive, capture the vanilla backup, take the lock.

        The heavy lifting (parse, md5, backup capture, flock,
        vanilla-baseline parse) is the pure ops.load_archive, safe on a
        worker thread; the state swap is install_open (Tk thread only).
        On any failure the session stays exactly as it was. A reload of
        the same path installs a fresh state with an empty ChangeSet and
        keeps the existing lock. -> info dict.
        """
        self._assert_ui_thread()
        rda_path = os.path.abspath(rda_path)
        same = (self.proj is not None and self.source_path and
                os.path.normcase(self.source_path)
                == os.path.normcase(rda_path))
        loaded = ops.load_archive(
            rda_path, self.store, self.exports_store, self.settings, same,
            cached_baseline=self.vanilla_baseline,
            cached_stamp=getattr(self, "_vanilla_stamp", None))
        return self.install_open(loaded)

    def install_open(self, loaded):
        """Tk-thread commit of ops.load_archive: swap the
        whole session to the newly opened archive. A failed load never
        reaches here (the worker raised and the session is untouched),
        so the swap is unconditional. -> info dict for the UI."""
        self._assert_ui_thread()
        if loaded.lock is not None:
            # A new archive: release the old session's lock and install
            # the new one (same-path reloads keep the existing lock).
            if self._lock is not None:
                try:
                    self._lock.__exit__(None, None, None)
                except Exception:
                    pass
            self._lock = loaded.lock
        if self.proj is not None:
            _log("close", path=self.source_path)
        self.proj = loaded.proj
        self.source_path = loaded.path
        self.source_md5 = loaded.md5
        self.cs = ChangeSet()
        self.modes = {}
        self._datasets_map = None
        self.vanilla_baseline = loaded.vanilla_baseline
        self._vanilla_stamp = loaded.vanilla_stamp
        _log("open", path=loaded.path, md5=loaded.md5[:12],
             files=len(loaded.proj.entries), reload=loaded.same_path)
        return {"path": loaded.path,
                "files": len(loaded.proj.entries),
                "profiles": len(loaded.proj.by_guid),
                "source_md5": loaded.md5,
                "backup": loaded.backup_msg,
                "personas": len(self.personas)}

    def close(self):
        """Clear all session state and release the lock; idempotent."""
        self._assert_ui_thread()
        if self.proj is not None:
            _log("close", path=self.source_path)
        self.proj = self.source_path = self.source_md5 = None
        self.cs = ChangeSet()
        self.modes = {}
        self._datasets_map = None
        if self._lock is not None:
            try:
                self._lock.__exit__(None, None, None)
            finally:
                self._lock = None


    def provide_vanilla(self, rda_path):
        """Explicitly provide the game's VANILLA data1.rda for storage.

        The user picks the pristine vanilla file (the game's original
        addon/data1.rda — e.g. verified by Steam). The file is copied
        write-once into the app's own structure as data1.rda_vanilla and
        persists between launches. NOT necessarily the same path the
        live game archive lives at (set via set_live_path).
        """
        rda_path = os.path.abspath(rda_path)
        with self._write_lock():
            # Verify the trust anchor before storing it: a strict RDA
            # parse plus a full ModProject parse. An md5 alone would only
            # prove the file is unchanged since capture, not that it is a
            # usable archive.
            try:
                from .rda import read_rda
                from .core import ModProject
                ventries = read_rda(rda_path, strict=True)
                ModProject(rda_path, entries=ventries)
            except Exception as e:
                raise SessionError(
                    f"the provided file is not a readable Anno 1404 "
                    f"data1.rda archive ({e}) — refusing to store it as "
                    "the vanilla copy")
            try:
                vmd5, vcreated = self.exports_store.capture_vanilla_copy(rda_path)
            except ExportsError as e:
                raise SessionError(str(e))
            # KNOWN-VANILLA verification: the per-member SHA-256
            # registry (a hash is not game data) says whether the
            # provided copy is a VERIFIED vanilla build or an
            # UNKNOWN one (possibly modded). Surface it - the
            # restore/reference trust claims depend on it.
            from . import vanilla_registry as _vr
            self._vanilla_class = _vr.member_class(ventries)
            _log("provide_vanilla", path=rda_path, md5=vmd5[:12],
                 created=vcreated)
            self._load_vanilla_baseline()
            return {"md5": vmd5, "created": vcreated,
                    "path": self.exports_store.vanilla_path}

    def set_live_path(self, path):
        """Set the game's LIVE addon/data1.rda location (persisted).

        The live archive is what Flash overwrites and Restore-vanilla
        restores — NOT necessarily where the vanilla copy was provided
        from. Also updates the BackupStore capture on next open of that
        path. Returns the normalized absolute path.
        """
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise SessionError(f"no such archive: {path}")
        # The live location must NEVER be a protected
        # app file (the stored vanilla copy, a backup, the export store) —
        # the GUI save path then 'saved to live' straight over the trust
        # anchor with no check anywhere on the pure commit path.
        if self._is_protected(path):
            raise SessionError(
                f"refusing to set the live location to {path} — it is a "
                "protected app file (the stored vanilla copy, a backup, "
                "or the export store); the live location is the game's "
                "addon/data1.rda")
        self.settings.set("live_path", path)
        _log("set_live_path", path=path)
        return path

    def live_path(self):
        """The persisted live addon/data1.rda path (or None)."""
        p = self.settings.get("live_path")
        return p if p and os.path.isfile(p) else None

    # ------------------------------------------------------------ roster

    @property
    def roster(self):
        """Flatten all profiles of the open archive (empty when closed)."""
        return [q for ps in (self.proj.profiles.values() if self.proj else [])
                for q in ps]

    def personas_for(self, profile):
        """Persona labels whose target list includes this character."""
        out = []
        for label, spec in self.personas.items():
            if self._persona_target(profile, spec):
                out.append(label)
        return out

    @staticmethod
    def _persona_target(profile, spec):
        # EXACT name match first, then the optional 'guid'
        # key — never a fuzzy substring match (a short name matched
        # broadly and could attach a persona to the wrong profile).
        for cname, tspec in spec["targets"].items():
            if cname == profile.name:
                return cname
            if isinstance(tspec, dict) and tspec.get("guid") \
                    and str(tspec["guid"]) == profile.guid:
                return cname
        return None

    def persona_dials(self, profile, label):
        """Return the persona's dial map for this profile or raise."""
        return dict(self._persona_spec(profile, label)["dials"])

    def persona_relations(self, profile, label):
        """Return the persona's {kind: [guids]} map for this profile or raise."""
        return dict(self._persona_spec(profile, label)["relations"])

    def _persona_anchor(self, profile, label, path):
        """The persona's insert_after anchor for one dial
        path (None when the persona carries no anchor for it)."""
        try:
            ia = self._persona_spec(profile, label).get("insert_after") or {}
            return ia.get(path)
        except SessionError:
            return None

    def _persona_spec(self, profile, label):
        spec = self.personas.get(label)
        if not spec:
            raise SessionError(f"unknown persona: {label}")
        cname = self._persona_target(profile, spec)
        if not cname:
            raise SessionError(f"persona {label!r} has no entry for {profile.name}")
        return spec["targets"][cname]

    # ------------------------------------------------------------ edits

    def set_mode(self, profile, mode):
        """'vanilla' resets the profile to the reference; 'hardened'
        queues the hardened targets; a persona label applies that
        persona; 'custom' keeps as-is.

        ABSOLUTE QUEUEING: 'vanilla'
        queues the reference value for EVERY key in scope (dials AND all
        four relations kinds), 'hardened' queues the target for every
        KEY_DIAL the archive knows — not only where the OPENED archive
        differs. On save-to-live the replay lands on the LIVE members,
        so a live-only mod the opened archive lacks is reset too; no-op
        rows drop at review/build time against the base actually
        written (rule='reset'/'harden' — see DialEdit).
        """
        self._assert_ui_thread()
        # The whole mode dispatch runs on a candidate ChangeSet: any
        # validation failure part-way through leaves the user's pending
        # edits and the mode label untouched.
        with self._txn():
            # Per-call reset — the un-revertable list
            # describes the LAST set_mode(vanilla) only
            self._last_unrevertable = []
            if mode == "vanilla":
                self._txn_drop_profile(profile.guid)
                # An honest mode label: without a vanilla reference
                # (no baseline, or the character absent from it) a
                # Vanilla click only DROPS pending edits - it reverts
                # nothing. The label must not claim 'vanilla'.
                had_reference = False
                if self.vanilla_baseline is not None:
                    vprof = self.vanilla_baseline.by_guid.get(profile.guid)
                    if vprof is not None:
                        had_reference = True
                        un_revertable = []
                        # SORTED — a bare set
                        # makes the missing-leaf INSERT order depend on
                        # PYTHONHASHSEED (built bytes non-deterministic).
                        # ABSOLUTE
                        # QUEUEING — queue the reference value for EVERY
                        # key in scope, not only where the OPENED archive
                        # differs. The old delta-queueing made a Vanilla
                        # click silently INEFFECTIVE on save-to-live
                        # whenever live differed from opened (opened ==
                        # vanilla -> nothing queued -> the replay kept
                        # every live mod). No-op rows drop at review/build
                        # time against the BASE actually written
                        # (rule='reset').
                        for path in sorted(set(profile.dials)
                                           | set(vprof.dials)):
                            vval, _vsrc = effective_value(
                                vprof.dials, self.vanilla_baseline.defaults,
                                path)
                            if vval is None:
                                # A leaf the OPENED
                                # (modded) archive ADDED that vanilla lacks
                                # AND that has no schema default cannot be
                                # reverted by a VALUE edit — the engine has
                                # no delete-leaf operation. Recorded and
                                # surfaced (never silently ignored).
                                if (path in profile.dials
                                        and path not in self.proj.defaults):
                                    un_revertable.append(path)
                                continue
                            # read-only leaves (Quest/Text/Color/
                            # FileName/... — 120 in real profiles, e.g.
                            # ShipFight/ShipDropPool): the validator
                            # refuses them and the engine never edits
                            # them; queueing one aborted the whole
                            # vanilla click on real data. Skip silently —
                            # the reset of a value-identical leaf is a
                            # no-op anyway (opened == vanilla there in
                            # the un-modded case; a foreign MOD of such a
                            # leaf is unmodelled and reported by the
                            # drift/unmodelled machinery, not reverted).
                            schema = self._schema_entry(profile, path)
                            if ((schema.get(path) or {}).get("type", "")
                                    .strip().lower() in _RO_TYPES):
                                continue
                            self._txn_add_dial(profile, path, str(vval),
                                               rule="reset",
                                               from_reference=True)
                        self._last_unrevertable = un_revertable
                        # Vanilla mode resets relations too: all four
                        # kinds are queued as full-list replacements, not
                        # only where the opened archive differs, so a
                        # live-only list is also reset by the replay. A
                        # kind whose base list already equals the
                        # reference is dropped as a no-op at review/build
                        # time.
                        try:
                            # The relations reader RAISES on a
                            # broken/ambiguous structure — a broken
                            # vanilla copy must abort the mode change
                            # cleanly (rolled back), never copy a
                            # silent {} into the pending state.
                            vrel = self.vanilla_baseline.relations(vprof)
                        except EditError as e:
                            raise SessionError(
                                f"vanilla reference relations unreadable "
                                f"for {profile.name}: {e}")
                        for kind in REL_KINDS:
                            self._txn_add_rel(
                                profile, kind,
                                [str(g) for g in vrel.get(kind, ())],
                                rule="reset")
                        # Global EXTRAS/fertility are not touched by a
                        # per-character Vanilla click; reverting them is
                        # the explicit revert_globals_to_reference()
                        # action.
            elif mode == "hardened":
                self._txn_drop_profile(profile.guid)
                # Derive 'hardest vanilla
                # values' from the VANILLA BASELINE (the provided/stored
                # vanilla copy) when available — the opened archive may
                # itself be modded (our own personas), which would make
                # 'hardened' build on modded extremes. Without a vanilla
                # baseline, keep the opened archive (labelled relative).
                roster = self.vanilla_baseline_roster()
                defaults = (self.vanilla_baseline.defaults
                            if self.vanilla_baseline is not None
                            else self.proj.defaults)
                # ABSOLUTE queueing over
                # KEY_DIALS — the hardened target is queued for EVERY key
                # dial the archive knows; NEVER-EASIER is evaluated at
                # review/build time against the BASE being written (the
                # old hardened_changes skip was evaluated against the
                # OPENED profile, so a live value LOWER than the opened
                # one stayed lower after save-to-live).
                hard_dials = [q.dials for q in roster
                              if q.guid in HARD_GUIDS]
                for k, direction in KEY_DIALS:
                    v = hardened_target(k, direction, hard_dials, defaults)
                    if v is None:
                        continue   # dial unknown to this archive — skip
                    self._txn_add_dial(profile, k, str(v), rule="harden")
                # Without a vanilla baseline the derivation is
                # RELATIVE to the (possibly modded) opened archive — the
                # GUI label says so (helper handles it)
                if self.vanilla_baseline is None:
                    self.modes[profile.guid] = "hardened_rel"
                    return self.changes.get(profile.guid, {})
            elif mode in self.personas:
                self._txn_drop_profile(profile.guid)
                tspec = self._persona_spec(profile, mode)
                ia = tspec.get("insert_after") or {}
                for k, v in self.persona_dials(profile, mode).items():
                    self._txn_add_dial(profile, k, str(v), ia.get(k))
                rels = self._resolved_rel_dict(
                    profile, self.persona_relations(profile, mode))
                self._dry_run_relations(profile, rels)
                for kind, guids in rels.items():
                    self._txn_add_rel(profile, kind, guids)
            elif mode == "custom":
                pass        # keep whatever is pending
            else:
                raise SessionError(f"unknown mode: {mode}")
            if mode == "vanilla" and not had_reference:
                # dropped pending only - the label says so (the GUI
                # maps it to 'Cleared (no vanilla reference)')
                self.modes[profile.guid] = "vanilla_no_ref"
            else:
                self.modes[profile.guid] = mode
        return self.changes.get(profile.guid, {})

    def set_dial(self, profile, path, value):
        """Set/clear one pending dial edit. value None/'' = clear pending.

        Clearing on a persona-mode profile restores the PERSONA's value for
        that dial (a manual override is dropped, not the whole persona edit).
        """
        self._assert_ui_thread()
        guid = profile.guid
        # A single manual edit is a transaction too: stage -> validate
        # (engine dry-run of the changed guid only) -> swap. A refused edit
        # never stays queued, and a previously valid pending value for the
        # same key survives the refusal untouched.
        with self._txn():
            if value is None or str(value).strip() == "":
                mode = self.modes.get(guid)
                persona_val = None
                if mode in self.personas:
                    try:
                        persona_val = self.persona_dials(
                            profile, mode).get(path)
                    except SessionError:
                        persona_val = None
                if persona_val is not None:
                    # Restore the persona value together with its
                    # insert_after anchor, so persona -> tweak -> reset
                    # yields the exact persona bytes again.
                    ia = self._persona_anchor(profile, mode, path)
                    self._queue_dial(profile, path, persona_val, ia)
                else:
                    self.cs.drop_dial(guid, path)
            else:
                self._queue_dial(profile, path, value)
            # NOTE: manual dial edits do NOT clobber an existing mode
            # label — a persona stays 'that persona + tweaks', so
            # clearing a manual override can still restore the persona's
            # own value (see above). An unset profile becomes 'custom'
            # on the first manual edit.
            if self.changes.get(guid) and guid not in self.modes:
                self.modes[guid] = "custom"
        return self.changes.get(guid, {})

    def _queue_dial(self, profile, path, value, insert_after=None,
                    rule=None, from_reference=False):
        """Queue one dial edit, validated against the schema at queue time
        (Integer/Time/RealInt/AIProfile/Asset -> int, Boolean ->
        0/1|true/false with the file's spelling, Choice -> datasets.xml
        item, Flags -> ';'-subset, Text/Vector/Array/... -> refused) plus a
        dry-run of the edit through the real engine, so it fails right
        here rather than at save time.
        insert_after: sibling anchor for a missing-leaf insert.
        rule: 'reset' | 'harden' — how a no-op against the written base
        is treated at review/build time (see DialEdit)."""
        # List structure is NEVER a dial path (verified on vanilla
        # zero legit dial paths carry Relations/Profiles/Item segments)
        segs = path.split("/")
        if any(s in ("Relations", "Profiles", "Item") for s in segs):
            raise SessionError(
                f"dial {path!r} is list structure (Relations/Profiles/Item) "
                "— use set_relations for relation lists")
        schema = self._schema_entry(profile, path)
        try:
            e = self.cs.add_dial(profile.guid, path, value, schema,
                                  insert_after, rule=rule,
                                  from_reference=from_reference)
        except ChangeSetError as exc:
            raise SessionError(str(exc))
        # (the trailing standalone dry-run is gone: set_dial wraps every
        # manual edit in _txn — the commit dry-run covers the changed guid;
        # inside a transaction the bulk dry-run at commit covers it)
        return e

    def _schema_entry(self, profile, path):
        """{path: doc-entry} for typed validation — exact sub-path, the
        unique-leaf alias, plus additions: 'choices' (the datasets.xml
        enumeration for Choice/Flags) and 'cur_value' (the dial's current
        value in the OPENED archive — Boolean spelling preservation)."""
        schema = {}
        if not self.proj:
            return schema
        d = self.proj.docs.get(path.split("/")[0]) or {}
        rest = "/".join(path.split("/")[1:])
        entry = d.get(rest) or d.get(path.rsplit("/", 1)[-1])
        if not entry:
            return schema
        entry = dict(entry)
        ds = entry.get("dataset")
        if ds:
            choices = self.datasets_choices(ds)
            if choices:
                entry["choices"] = choices
            elif choices is None:
                # The enumeration could not be loaded
                # (datasets.xml unreadable) — mark the entry so the
                # Choice/Flags validator FAILS CLOSED (refuses) instead
                # of silently accepting anything.
                entry["choices_unavailable"] = True
        # Pass the current value so Booleans keep the file's spelling
        # ('1' stays '1', 'true' stays 'true').
        if (entry.get("type") or "").strip().lower() in ("boolean", "bool"):
            try:
                cur, _src = effective_value(profile.dials, self.proj.defaults,
                                            path)
            except Exception:
                cur = None
            if cur is not None:
                entry["cur_value"] = str(cur)
        schema[path] = entry
        return schema

    def datasets_choices(self, ds_name):
        """The allowed values for a DataSet name, from
        config/game/datasets.xml in the OPENED archive (lazily parsed,
        cached per session; () when absent).

        datasets.xml is decoded as latin-1 like its sibling files, so a
        stray cp1252 byte from another mod cannot break parsing. A parse
        failure is logged and marks validation unavailable
        (enum_validation_available); the Choice/Flags validator then
        refuses values rather than accepting anything (fail closed)."""
        if not self.proj:
            return ()
        if self._datasets_map is None:
            m = {}
            try:
                import xml.etree.ElementTree as ET
                key = "addondata/config/game/datasets.xml"
                raw = self.proj.entries.get(key, (b"",))[0]
                if raw:
                    root = ET.fromstring(raw.decode("latin-1"))
                    for ds in root.iter("DataSet"):
                        nm = (ds.findtext("Name") or "").strip()
                        if nm:
                            m[nm] = frozenset(
                                (i.findtext("Name") or "").strip()
                                for i in ds.iter("Item"))
            except Exception as e:
                # Never silently off — log + mark unavailable; the
                # Choice/Flags validation then FAILS CLOSED (a value is
                # refused when its enumeration can't be checked).
                from .applog import log
                log("datasets_xml_unavailable", error=str(e)[:120])
                m = {"__unavailable__": True}
            self._datasets_map = m
        if self._datasets_map.get("__unavailable__"):
            return None
        return self._datasets_map.get(ds_name) or ()

    @property
    def enum_validation_available(self):
        """False when datasets.xml could not be
        parsed (the UI shows why Choice/Flags validation is off)."""
        if not self.proj or self._datasets_map is None:
            self.datasets_choices("")
        return not (self._datasets_map or {}).get("__unavailable__")

    def effective(self, profile, path):
        """Compute a dial's effective value and source (edit vs default)."""
        return effective_value(profile.dials, self.proj.defaults, path)

    # ------------------------------------------------------------ named presets

    @staticmethod
    def _slug(name):
        keep = "-_.() " + string.ascii_letters + string.digits
        s = "".join(c for c in name if c in keep).strip().replace(" ", "_")
        return s or "preset"

    def named_preset_path(self, name):
        """Ensure the user presets dir exists; return the preset JSON path."""
        d = _user_presets_dir()
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, self._slug(name) + ".json")

    def save_named_preset(self, profile, name, note=""):
        """Save THIS character's pending edits as a named JSON preset.

        Relations ride along in the same shape persona files
        use ({'dials': {...}, 'relations': {kind: [guid]}}).
        """
        self._assert_ui_thread()
        pend = self.cs.dial_map(profile.guid)
        rels = self.cs.rel_map(profile.guid)
        if not pend and not rels:
            raise SessionError(f"{profile.name}: no pending edits to save")
        spec = {"dials": dict(pend)}
        # Persist insert_after anchors with named presets so a saved and
        # reloaded preset produces the same bytes.
        ia = self.cs.dial_map(profile.guid, anchors=True)
        anchors = {}
        for path, val in pend.items():
            if isinstance(ia.get(path), tuple):
                anchors[path] = ia[path][1]
        if anchors:
            spec["insert_after"] = anchors
        if rels:
            spec["relations"] = rels
        data = {
            "name": name,
            "description": note or f"named preset for {profile.name} "
                                    f"({profile.template} {profile.guid}), "
                                    f"{len(pend)} dials"
                                    + (f", {len(rels)} relations" if rels else ""),
            "characters": {profile.name: spec},
        }
        with open(self.named_preset_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return self.named_preset_path(name)

    def named_presets(self):
        """{name: path} of the user's saved presets."""
        out = {}
        d = _user_presets_dir()
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fn),
                              encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    continue
                # A preset JSON whose top level is a
                # LIST would AttributeError below — guard on dict.
                if isinstance(data, dict) and data.get("characters"):
                    out[data.get("name") or fn[:-5]] = os.path.join(d, fn)
        return out

    def load_named_preset(self, profile, name):
        """Apply a named preset to THIS profile. -> changes dict."""
        self._assert_ui_thread()
        path = self.named_presets().get(name)
        if not path:
            raise SessionError(f"no named preset {name!r}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        targets = data.get("characters") or {}
        cname = self._persona_target(profile, {"targets": targets})
        if not cname:
            raise SessionError(f"preset {name!r} targets {list(targets)}, "
                               f"not {profile.name}")
        spec = targets[cname]
        dials = {k: str(v) for k, v in (spec.get("dials") or {}).items()}
        rels = {k: list(v) for k, v in (spec.get("relations") or {}).items()}
        if not dials and not rels:
            raise SessionError(f"preset {name!r} has no dials or relations")
        ia = spec.get("insert_after") or {}
        with self._txn():
            self._txn_drop_profile(profile.guid)
            for k, v in dials.items():
                self._txn_add_dial(profile, k, v, ia.get(k))
            if rels:
                resolved = self._resolved_rel_dict(profile, rels,
                                                    self.proj.relations(profile))
                self._dry_run_relations(profile, resolved)
                for kind, guids in resolved.items():
                    self._txn_add_rel(profile, kind, guids)
            self.modes[profile.guid] = "custom"
        return {k: e.value for k, e in
                ((p, self.cs.dials.get((profile.guid, p))) for p in dials)
                if e}

    # ------------------------------------------------------------ relations

    def _resolve_guids(self, profile, names):
        """Resolve a list of names/GUIDs (or None items) to GUID strings.

        Each item may be a GUID ('1645020'), a character name
        ('Baronessa Constanza Zanchi'), or None (= keep the current
        entry). Unresolvable items raise with the full candidate list.
        """
        if not self.proj:
            raise SessionError("no archive open")
        out = []
        for item in names:
            if item is None:
                out.append(None)
                continue
            key = str(item).strip()
            if key in self.proj.by_guid:
                out.append(key)
                continue
            prof = self.proj.by_name.get(key)
            if prof is not None:
                out.append(prof.guid)
                continue
            # Exact (case-insensitive) name
            # match BEFORE substring matching — a name that is a prefix
            # of another name must resolve to itself, never to the
            # longer one
            exact = [n for n in self.proj.by_name
                     if n.lower() == key.lower()]
            if len(exact) == 1:
                out.append(self.proj.by_name[exact[0]].guid)
                continue
            hits = [n for n in self.proj.by_name if key.lower() in n.lower()]
            if len(hits) == 1:
                out.append(self.proj.by_name[hits[0]].guid)
                continue
            if hits:
                raise SessionError(f"{key!r} is ambiguous — matches "
                                   f"{hits}")
            raise SessionError(f"{key!r} is not a known character GUID or name "
                               "in this archive")
        return out

    def _resolved_rel_dict(self, profile, rels, current=None):
        """{kind: [guid]} with names resolved and Nones dropped.

        A GUID already present in the CURRENT list passes
        through UNVALIDATED (a PlayerProfile GUID inside vanilla data must
        not block editing that list); only NEW additions resolve strictly.
        """
        current = current or {}
        resolved = {}
        for kind, names in rels.items():
            known = {str(g) for g in current.get(kind, ())}
            guids = []
            for item in names:
                s = str(item).strip() if item is not None else None
                if s is not None and s in known:
                    guids.append(s)          # already in the list: pass through
                else:
                    guids.extend([g for g in self._resolve_guids(profile, [item])
                                  if g is not None])
            resolved[kind] = guids
        return resolved

    def set_relations(self, profile, war=None, ally=None, trade=None, avoidwar=None):
        """Queue pending Relations edits (validated NOW, applied at build).

        Same semantics as the engine: each kind is a FULL-LIST replacement;
        a kind not passed (None) = leave that list exactly as-is.
        List items may be GUIDs or character names (or None = keep current).
        """
        self._assert_ui_thread()
        if not self.proj:
            raise SessionError("no archive open")
        # Stage -> validate -> swap. The
        # resolution + engine dry-run + ChangeSet-level relations rules
        # (dedupe/self-war/cross-kind conflict) all run on the CANDIDATE
        # inside the transaction; on ANY refusal the user's pending
        # edits survive untouched and nothing half-applied stays.
        with self._txn():
            kwargs = {"War": war, "Ally": ally, "Trade": trade,
                      "AvoidWar": avoidwar}
            pending = dict(self.cs.rel_map(profile.guid))
            for kind, names in kwargs.items():
                if names is None:
                    continue
                if isinstance(names, (str, bytes)) \
                        or not hasattr(names, "__iter__"):
                    raise SessionError(
                        f"relations {kind}: need a list of names/GUIDs")
                pending[kind] = list(names)
            # The current lists are the pass-through baseline: GUIDs
            # already in a list resolve as themselves; only new additions
            # are resolved strictly.
            cur = self.proj.relations(profile)
            resolved = self._resolved_rel_dict(profile, pending, cur)
            # dry-run through the REAL engine on a scratch project before
            # accepting any of it into the pending state
            self._dry_run_relations(profile, resolved)
            for kind, guids in resolved.items():
                self._txn_add_rel(profile, kind, guids)
            return resolved

    def _dry_run_relations(self, profile, resolved):
        """Exercise the engine's set_relations on an IN-MEMORY copy.

        The old scratch ModProject(self.source_path)
        re-read and re-decrypted the whole archive from disk for every
        relations click / persona pick (~4.4 s on real data, on the Tk
        thread) and validated against the DISK file, which may have been
        replaced since open (violation). Now seeded from the opened
        IN-MEMORY entries (from_entries, ~0.1 s) and carrying the profile's
        pending dials so dial/relations insert interactions are exercised
        (the real build applies dials before relations).
        """
        if not self.proj:
            raise SessionError("no archive open")
        scratch = ModProject.from_entries(self.proj.entries, self.source_path)
        prof = scratch.by_guid.get(profile.guid)
        if prof is None:
            raise SessionError(f"profile {profile.guid} not in archive — reopen?")
        pend = self.cs.dial_map(profile.guid, anchors=True)
        if pend:
            scratch.set_dials(prof, pend)   # pending dials included
        kwargs = {k.lower(): v for k, v in resolved.items()}
        scratch.set_relations(prof, **kwargs)   # may raise EditError
        # Exclusivity is checked against the effective post-build state
        # (file lists overlaid with pending), not only among pending edits:
        # a target in the file's AvoidWar list that a War edit would also
        # put in War is an incoherent result. War/Ally vs AvoidWar must be
        # disjoint (as in vanilla). War vs Ally overlap is allowed: the
        # in-game-verified Spider persona has 1645006 in both.
        eff = scratch.relations(prof)
        avoid = set(eff.get("AvoidWar", ()))
        war_clash = set(eff.get("War", ())) & avoid
        ally_clash = set(eff.get("Ally", ())) & avoid
        if war_clash or ally_clash:
            g = sorted(war_clash or ally_clash)[0]
            kind = "War" if war_clash else "Ally"
            raise SessionError(
                f"relations for {profile.name}: {g} would be in both "
                f"{kind} and AvoidWar in the RESULTING profile (it is in "
                "the file's current lists) — remove it from one side first")

    def clear_relations(self, profile, kind=None):
        """Drop pending relations edits for one profile (or one kind)."""
        self._assert_ui_thread()
        if kind is None:
            self.cs.drop_rel(profile.guid)
        else:
            lowered = {k.lower(): k for k in REL_KINDS}
            self.cs.drop_rel(profile.guid,
                             lowered.get(str(kind).lower(), str(kind)))

    def relations_row(self, profile, kind):
        """[guid str] of one kind: pending edit if queued, else current."""
        pend = self.rels.get(profile.guid, {}).get(kind)
        if pend is not None:
            return list(pend)
        return list(self.proj.relations(profile).get(kind, ()))

    def relations_of(self, profile):
        """The profile's full current relations map (no pending applied)."""
        if not self.proj:
            raise SessionError("no archive open")
        return self.proj.relations(profile)

    def dial_row(self, profile, path):
        """Build one dial's row dict: value, source, default, pending."""
        val, src = self.effective(profile, path)
        return {"value": val, "source": src,
                "default": self.proj.defaults.get(path),
                "vanilla": self.vanilla_dial_row(profile, path).get("value"),
                "pending": self.changes.get(profile.guid, {}).get(path)}

    def vanilla_dial_row(self, profile, path):
        """One dial's VANILLA value from the stored data1.rda_vanilla.

        Returns {"value": None} when no vanilla copy is stored (the GUI
        falls back to '—' and reset-to-vanilla drops pending edits).
        """
        if self.vanilla_baseline is None:
            return {"value": None}
        vprof = self.vanilla_baseline.by_guid.get(profile.guid)
        if vprof is None:
            return {"value": None}
        val, _src = effective_value(vprof.dials,
                                    self.vanilla_baseline.defaults, path)
        return {"value": val}

    # ------------------------------------------------------------ extras/fertility

    def extras_catalog(self):
        """-> {section: {tag: {asset display name: [values, file order]}}},
        the REFERENCE values for the GUI 'vanilla' column.

        The reference is the provided vanilla copy when one is stored;
        the opened archive is the fallback. For the values actually in
        the opened archive use extras_current().
        """
        base = self.vanilla_baseline if self.vanilla_baseline else self.proj
        return base.extras_catalog()

    def extras_current(self):
        """-> {section: {tag: {asset display name: [values, file order]}}}
        over the OPENED archive's assets.xml (the current-value
        column — what the file you are editing actually contains; edits
        replace THESE values). None when no archive is open."""
        if not self.proj:
            return None
        return self.proj.extras_catalog()

    def clear_extras(self):
        """Drop every queued EXTRAS edit ('Reset all extras' — the
        GUI may never assign to the read-only .extras view)."""
        self._assert_ui_thread()
        self.cs.drop_all_extras()

    def vanilla_baseline_roster(self):
        """The roster 'Hardened' derives its
        hardest values from — the VANILLA baseline's roster when one is
        available, else the opened archive's (labelled 'relative to the
        opened archive' in the GUI)."""
        if self.vanilla_baseline is not None:
            return [q for ps in self.vanilla_baseline.profiles.values()
                    for q in ps]
        return list(self.roster)

    def revert_globals_to_reference(self):
        """The explicit "revert all EXTRAS + fertility to the vanilla
        reference" action. Stage -> validate -> swap via _txn. Without a
        vanilla reference it refuses (nothing to revert to). It must run
        outside any set_mode transaction so it can raise SessionError.

        EXTRAS leaves the OPENED archive carries but the REFERENCE
        lacks (a tag this tool itself INSERTED — the only legal
        inserts are allow-listed ProductionTime adds) are NOT
        revertable this way (no reference value exists to reset to;
        no delete op exists). They are recorded in
        self._last_unrevertable_extras and surfaced by the GUI as a
        warning — never silently kept."""
        self._assert_ui_thread()
        if not self.proj:
            raise SessionError("no archive open")
        with self._txn():
            self._queue_global_revert_to_reference()
            # opened — reference leaves: the tool's own INSERTS
            # are un-revertable (no reference value; no delete op);
            # record them for the GUI warning
            self._last_unrevertable_extras = self._unrevertable_extras()

    def _unrevertable_extras(self):
        """EXTRAS leaves carried by the OPENED archive but absent
        from the vanilla REFERENCE: the tool's own allow-listed
        INSERTS (ProductionTime on the four donor buildings). No
        delete op exists, so a global revert cannot remove them
        — they are reported instead of silently kept."""
        ref = self.vanilla_baseline
        if ref is None:
            return []
        base_cat = self.proj.extras_catalog()
        ref_cat = ref.extras_catalog()
        out = []
        for section in ref_cat:
            for tag in ref_cat[section]:
                ref_assets = ref_cat[section][tag]
                base_assets = base_cat.get(section, {}).get(tag, {})
                for asset in base_assets:
                    if asset not in ref_assets:
                        out.append(f"{asset} / {tag}")
        return out

    def _queue_global_revert_to_reference(self):
        """Queue global edits (EXTRAS + fertility) that take the opened
        archive's values back to the reference (vanilla) values. Dials and
        relations are per-character (set_mode queues them); these surfaces
        are global and are only reverted via the explicit
        revert_globals_to_reference() action. A reference
        baseline is required — without one (no provided vanilla copy),
        globals are left alone (nothing to revert TO); the occurrence-
        mismatch case raises SessionError (guarded, never IndexError)."""
        ref = self.vanilla_baseline
        if ref is None:
            return
        # Every reference leaf is queued, not only where the opened archive
        # differs: on save-to-live the replay lands on the live members,
        # which may differ from the opened archive. No-op rows are dropped
        # against the base at review time (rule='reset'; the replay guard
        # expects no particular old value for these).
        base = self.proj.extras_catalog()
        refc = ref.extras_catalog()
        for section in refc:
            for tag in refc[section]:
                for asset in refc[section][tag]:
                    bv = base.get(section, {}).get(tag, {}).get(asset)
                    rv = refc[section][tag][asset]
                    if bv is not None and len(bv) != len(rv):
                        # Occurrence-count mismatch between the opened
                        # archive and the reference — guard the IndexError
                        # and report instead of crashing
                        raise SessionError(
                            f"global revert: {asset} / {tag} has "
                            f"{len(bv)} occurrence(s) in the opened "
                            f"archive but {len(rv)} in the vanilla "
                            f"reference — cannot queue a safe revert")
                    # Record the REFERENCE occurrence
                    # count on every revert edit — occ_count=None disabled
                    # the replay guard, so a live file that gained a level
                    # (NoriaEndRadius 8/10 -> 6/8/10) was silently corrupted
                    # to [8,10,10] instead of refused. expected_old stays
                    # None (a reset replaces whatever is there); the count
                    # check alone catches the retarget class.
                    for occ, v in enumerate(rv):
                        self.cs.add_extra(asset, tag, str(v), occ,
                                          expected_old=None,
                                          occ_count=len(rv), rule="reset")
        # fertility: EVERY reference (tier, crop) rides along as a FULL
        # (N, S) pair (FertEdit carries no rule marker — all fert reverts
        # are resets; no-op rows drop at review/build time vs the base)
        rrows = {(r["tier"], r["crop"]): (r["north"], r["south"])
                 for r in ref.fertility_catalog()}
        for key in rrows:
            self.cs.add_fert(key[0], key[1], rrows[key][0], rrows[key][1])
        return True

    def extra_asset_names(self):
        """-> set of valid asset identifiers (plain + 'Name [GUID]' forms)."""
        from .extras import display_names, parse_assets
        parsed = parse_assets(self.proj.assets_text)
        return {a["name"] for a in parsed} | set(display_names(parsed).values())

    def set_extra(self, asset, tag, value, occ=None):
        """Queue one EXTRAS edit (validated NOW: integer + engine dry-run).
        occ=None = single-instance rule; INSERT when the asset lacks the tag."""
        self._assert_ui_thread()
        if not self.proj:
            raise SessionError("no archive open")
        # Stage -> validate -> swap (engine dry-run +
        # ChangeSet-level occ/int validation on the candidate)
        with self._txn():
            if value is None or str(value).strip() == "":
                # Clear EXACTLY this occurrence
                # the CANONICAL asset key and the caller's occ (None =
                # single-instance rule / the un-indexed pending). The old
                # drop_extra(asset, tag) used the NON-canonical asset AND
                # cleared EVERY occurrence of the tag on that asset.
                canon = self._canon_extra_asset(asset)
                # occ=None must also match a pending insert (stored with
                # occ=None).
                for k in [k for k in self.cs.extras
                          if k[0] == canon and k[1] == tag
                          # occ=None also matches a pending insert
                          and k[2] in ((0, None) if occ is None
                                       else (occ,))] :
                    self.cs.drop_extra_exact(*k)
                return True
            # canonical asset key: 'Name [GUID]' when ambiguous
            # else the plain name — one leaf, one edit
            canon = self._canon_extra_asset(asset)
            try:
                _nt, old = set_extra_edit(self.proj.assets_text, canon, tag,
                                          str(value).strip(), occ)
            except ExtrasError as e:
                raise SessionError(str(e))
            # Canonical occ — None means 'single-instance rule'
            # when the tag EXISTS in the asset that is occurrence #0 (None
            # stays reserved for INSERT-only): occ=None and occ=0 are ONE edit
            occ = 0 if (occ is None and old is not None) else occ
            # Record the queue-time leaf state (the opened archive's value
            # at this occurrence and the occurrence count) for the replay
            # guard, which refuses if live differs (another mod changed the
            # leaf or added a level).
            try:
                _full = self._extra_occ_values(canon, tag)
            except Exception:
                _full = None
            # An absent tag gives _full == [], which is a real count of 0
            # (so an insert is guarded against live gaining the tag).
            try:
                self.cs.add_extra(canon, tag, value, occ,
                                  expected_old=(str(old) if old is not None
                                                else None),
                                  occ_count=(len(_full)
                                             if _full is not None
                                             else None))
            except ChangeSetError as e:
                raise SessionError(str(e))
            return True

    def _extra_occ_values(self, canon, tag):
        """The OPENED archive's value list for one
        (canonical asset, tag) — for the queue-time occ_count record."""
        from .extras import find_asset, occurrences, parse_assets, asset_text
        assets = parse_assets(self.proj.assets_text)
        a = find_asset(assets, canon)
        ms = occurrences(asset_text(self.proj.assets_text, a), tag)
        return [m.group(1) for m in ms]

    def _canon_extra_asset(self, asset):
        """Canonical display spelling of an extras asset name
        resolve the name through the engine's find_asset — any resolvable
        spelling (plain name, 'Name [GUID]') maps onto the ONE canonical
        display name, so the same leaf can never be queued twice under
        different spellings. Unresolvable names are returned unchanged
        (the engine dry-run refuses them)."""
        from .extras import ExtrasError, display_names, find_asset, parse_assets
        parsed = parse_assets(self.proj.assets_text)
        try:
            a = find_asset(parsed, asset)
        except ExtrasError:
            return asset
        return display_names(parsed)[id(a)]

    def clear_extra(self, asset, tag):
        """Drop ALL queued EXTRAS edits for one asset/tag pair (the
        explicit 'reset all occurrences' action — per-occurrence
        clears go through set_extra with an empty value)."""
        self._assert_ui_thread()
        self.cs.drop_extra(self._canon_extra_asset(asset), tag)

    def fertility_catalog(self):
        """-> [{crop,tier,north,south}] rows, the REFERENCE (vanilla) rates.

        From the provided vanilla copy when stored; the opened archive is
        the fallback. For the rates actually in the opened archive use
        fertility_current().
        """
        base = self.vanilla_baseline if self.vanilla_baseline else self.proj
        return base.fertility_catalog()

    def fertility_current(self):
        """-> [{crop,tier,north,south}] rows over the OPENED archive's
        randommapgenerator.xml (current-value column). None when no
        archive is open."""
        if not self.proj:
            return None
        return self.proj.fertility_catalog()

    def set_fertility(self, tier, crop, north=None, south=None):
        """Queue one fertility edit (validated NOW via engine dry-run)."""
        self._assert_ui_thread()
        if not self.proj:
            raise SessionError("no archive open")
        # Stage -> validate -> swap (engine dry-run + the
        # ChangeSet-boundary normalization to int 0-100 on the candidate)
        with self._txn():
            cur = self.cs.fert.get((tier, crop))
            n = north if north is not None else (cur.north if cur else None)
            s = south if south is not None else (cur.south if cur else None)
            try:
                set_fertility_edit(self.proj.fert_text, tier, crop, n, s)
            except FertilityError as e:
                raise SessionError(str(e))
            try:
                self.cs.add_fert(tier, crop, n, s)
            except ChangeSetError as e:
                raise SessionError(str(e))
            return True

    def clear_fertility(self, tier=None, crop=None):
        """Clear fertility edits: all, or one (tier, crop) pair."""
        self._assert_ui_thread()
        self.cs.drop_fert(tier, crop)

    # ------------------------------------------------------------ reports

    def change_plan(self, base=None):
        """THE change plan (one source of truth): everything the build
        will write against BASE, as [ResolvedChange] + honest totals.

        base = the project the SAVE will actually write (the LIVE
        project for save-to-live — from the stashed drift result;
        fallback/None: the opened project, the CLI dry-run shape).
        No-op rule rows ('reset'/'harden' whose target the base already
        carries) are DROPPED HERE — the review rows, the build's no-op
        drop, and every display count derive from this one plan, so what
        the user approves is by construction what the build writes.
        The review dialog's rows and the plan the build verifies its
        expected_plan hash against are the SAME plan.
        -> (rows, totals dict)."""
        # Catalogs come from the base when one is given (the build replays
        # onto the base's members, so old values and no-op decisions must
        # match it), else from the opened archive (CLI dry-run).
        return plan_mod.plan(
            self.cs, self.roster, base, opened=self.proj,
            base_extras_catalog=(base.extras_catalog()
                                 if base is not None
                                 else (self.extras_current()
                                       if self.proj else None)),
            base_fert_catalog=(base.fertility_catalog()
                               if base is not None
                               else (self.fertility_current()
                                     if self.proj else None)))

    def pending_change_rows(self, base=None):
        """Structured pending changes for review: one row per change.

        Each row = {section, character, dial, old, new} where 'old' is the
        value that will be REPLACED and 'new' the pending edit. Order: AI
        dials, AI relations, extras, fertility. -> (rows, totals dict).

        DELEGATES to the ONE change plan (see change_plan) — the same
        plan the build's plan-hash guard and the honest pending counts
        use; no separate row logic can drift from the build again.
        """
        prows, totals = self.change_plan(base)
        return [r.row() for r in prows], totals

    def pending_counts(self, base=None):
        """Pending counts for display (badges, status lines, "discard
        edits?" prompts): the real changes the build would write against
        base. Rule rows that are no-ops against base are not counted, so
        clicking Vanilla on an unchanged character shows 0, not ~980.

        Default base = the OPENED project (what an in-place save / export
        writes). Cached per ChangeSet version — cheap on hot GUI paths.
        No open archive: raw record counts (an upper bound).
        -> {dials, relations, extras, fertility, _by_guid} where
        _by_guid = {guid: {dials, rels}} per-character counts for the
        roster badges."""
        if base is not None:
            return plan_mod.plan_counts(
                self.cs, self.roster, base, opened=self.proj,
                base_extras_catalog=(self.extras_current()
                                     if self.proj else None),
                base_fert_catalog=(self.fertility_current()
                                   if self.proj else None))
        return self._view("counts", self._build_counts_view)

    def _build_counts_view(self):
        if self.proj is None:
            return {"dials": len(self.cs.dials),
                    "relations": sum(len(e.guids)
                                      for e in self.cs.rels.values()),
                    "extras": len(self.cs.extras),
                    "fertility": len(self.cs.fert),
                    "_by_guid": {}}
        prows, totals = plan_mod.plan(
            self.cs, self.roster, self.proj, opened=self.proj,
            base_extras_catalog=self.extras_current(),
            base_fert_catalog=self.fertility_current())
        # Totals and _by_guid come from the same plan() call against the
        # same base the build writes, so badges always agree with the
        # review.
        counts = totals
        by_guid = {}
        for r in prows:
            g = by_guid.setdefault(r.key[0], {"dials": 0, "rels": 0})
            if r.kind == plan_mod.AI_PROFILE:
                g["dials"] += 1
            elif r.kind == plan_mod.AI_RELATIONS:
                g["rels"] += len(self.cs.rels[r.key].guids) \
                    if r.key in self.cs.rels else 1
        counts["_by_guid"] = by_guid
        return counts

    def change_report(self):
        """Per-character pending edits (old -> new) as text. No build."""
        lines = []
        total = 0
        for q in self.roster:
            pend = self.changes.get(q.guid) or {}
            rels = self.rels.get(q.guid)
            if not pend and not rels:
                continue
            lines.append(f"{q.name} ({q.template} {q.guid}):")
            for path in sorted(pend):
                val, _ = self.effective(q, path)
                lines.append(f"    {path}: {val} -> {pend[path]}")
                total += 1
            if rels:
                cur = self.proj.relations(q)
                for kind in REL_KINDS:
                    if kind not in rels:
                        continue
                    lines.append(f"    Relations/{kind}: "
                                 f"{cur.get(kind, [])} -> {rels[kind]}")
                # Relation GUID items are NOT dial edits
                # each kind edit is ONE list replacement, counted below
        if total == 0 and not self.rels and not self.extras and not self.fert:
            lines.append("(no pending changes)")
        lines.append(f"total dial edits: {total}")
        if self.rels:
            # Relation GUIDs are NOT dial edits — counted here only
            nrel = sum(len(e.guids) for e in self.cs.rels.values())
            lines.append(f"total relations edits: {nrel}")
        if self.extras:
            lines.append("EXTRAS (assets.xml — global, symmetric):")
            for (asset, tag, occ), val in sorted(
                    self.extras.items(),
                    key=lambda kv: (kv[0][0], kv[0][1],
                                    kv[0][2] if kv[0][2] is not None else -1)):
                occ_s = f"#{occ + 1}" if occ is not None else ""
                lines.append(f"    {asset}/{tag}{occ_s}: -> {val}")
            lines.append(f"total extras edits: {len(self.extras)}")
        if self.fert:
            lines.append("FERTILITY (randommapgenerator.xml — new islands):")
            for (tier, crop), (n, s) in sorted(self.fert.items()):
                parts = []
                if n is not None:
                    parts.append(f"N={n}")
                if s is not None:
                    parts.append(f"S={s}")
                lines.append(f"    {tier}/{crop}: {' '.join(parts)}")
            lines.append(f"total fertility edits: {len(self.fert)}")
        return "\n".join(lines)

    def freeze_drift_inputs(self, target=None):
        """Gather the FROZEN inputs for the
        drift check on the calling (UI) thread: the opened project (a
        reference — ModProject is never mutated in place after open),
        a roster LIST copy, a ChangeSet SNAPSHOT, the resolved target.
        The pure worker is ops.drift_check; nothing it reads can be
        swapped under it by a UI-thread edit."""
        if not self.proj:
            return None
        target = os.path.abspath(target or self.default_target() or "")
        return (self.proj, list(self.roster), self.cs.snapshot(),
                target, self.source_path)

    def target_drift(self, target=None):
        """How the LIVE target differs from the opened baseline, beyond
        the pending ChangeSet: a DriftResult (n_dials, n_relations,
        n_extras, n_fert, n_chars, foreign; falsy when there is nothing
        to report), or None when there is no target to compare.

        All four surfaces are compared (dials, relations, extras,
        fertility). The pure phase is ops.drift_check on frozen inputs
        (see freeze_drift_inputs); the GUI runs it on a worker thread,
        this sync wrapper is the CLI/tests path.
        """
        frozen = self.freeze_drift_inputs(target)
        if frozen is None:
            return None
        return ops.drift_check(*frozen, store=self.store)


    # ------------------------------------------------------------ build/flash

    def _build(self, out_path, snapshot=None, base_entries=None,
                roster=None, expected_plan=None):
        """Apply a SNAPSHOT of the pending changes to a fresh project and
        build+verify it. A thin wrapper over ops.build_from_snapshot
        (which the GUI worker calls directly); tests can patch it.

        Builds work on a frozen copy, so later session edits can never
        leak into a build in flight. Seeded from the in-memory opened
        entries, never re-read from disk. See ops.build_from_snapshot for
        the byte contract."""
        cs = snapshot if snapshot is not None else self.cs.snapshot()
        return ops.build_from_snapshot(
            base_entries if base_entries is not None else self.proj.entries,
            self.source_path, cs, out_path, roster=roster,
            expected_plan=expected_plan)

    def export(self, out_path, export_name=None, note=""):
        """Build to a separate file. Source untouched. -> report.

        The output policy is ops.export_guard: protected paths, the open
        source and the configured live path ("use flash") are refused. An
        existing ordinary out_path is allowed (an overwrite the user asked
        for) and goes through commit_archive (pre-replace snapshot, md5
        guard, mode preservation).

        With export_name the built file is ALSO saved into the export
        store as data1.rda_<exportname> (out_path keeps the exact name
        the user chose; the store copy is the managed one).
        """
        if not self.proj:
            raise SessionError("no archive open")
        self._assert_ui_thread()
        out_path = ops.export_guard(
            self.store, self.exports_store, out_path,
            source_path=self.source_path)
        with self._write_lock():
            if os.path.isfile(out_path):
                # An existing out goes through the commit protocol, which
                # snapshots the old bytes before the replace. Unique temp
                # name so instances never collide.
                _fd, tmp = tempfile.mkstemp(
                    prefix=".annoedit-", suffix=".tmp",
                    dir=os.path.dirname(out_path) or ".")
                os.close(_fd)
                os.unlink(tmp)
                try:
                    report = self._build(tmp, self.cs.snapshot())
                    commit = ops.commit_archive(
                        self.store, out_path, tmp,
                        exports_store=self.exports_store,
                        snapshot_reason="export")
                    report.update(commit)
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
            else:
                report = self._build(out_path, self.cs.snapshot())
            if export_name:
                stored = self.exports_store.save_named_export(
                    out_path, export_name, note=note,
                             source_md5=report.get("md5"))
                report["export_name"] = export_name
                report["export_stored_path"] = stored
            _log("export", path=out_path, name=export_name or "",
                 md5=report["md5"][:12])
            return report

    def export_named(self, name, note=""):
        """Build the pending changes into the exports store as
        data1.rda_<name>. -> report (export_name/export_stored_path set).

        The pure phase is ops.export_named_build on frozen inputs
        (entries reference + ChangeSet snapshot); the GUI runs it on a
        worker thread, this sync wrapper is the CLI/tests path."""
        if not self.proj:
            raise SessionError("no archive open")
        self._assert_ui_thread()
        with self._write_lock():
            return ops.export_named_build(
                self._write_lock, self.exports_store,
                self.proj.entries, self.source_path,
                self.cs.snapshot(), name, note=note,
                roster=list(self.roster))

    # ------------------------------------------------------------ exports mgmt

    def list_saved_exports(self):
        """-> [{name, path, md5, size, saved_at, note}] (vanilla copy first)."""
        return self.exports_store.list_exports()

    def load_saved_export_path(self, name):
        """-> store path of one saved export (or the vanilla copy)."""
        return self.exports_store.load_export_path(name)

    def delete_saved_export(self, name):
        """Delete one saved export (vanilla copy refused)."""
        return self.exports_store.delete_export(name)

    def rename_saved_export(self, old, new):
        """Rename one saved export. -> new name."""
        return self.exports_store.rename_export(old, new)

    # ------------------------------------------------------------ targets

    def _is_protected(self, path):
        """True for files the tool must NEVER overwrite: anything inside the
        app's own backup store, plus the stored vanilla copy.

        Without this guard, opening 'vanilla' from the export manager and
        pressing 'Save to live' (with no live location set) flashed the
        edits straight over data1.rda_vanilla — silently destroying the
        persistent vanilla backup.

        The POLICY lives in ops.protected_paths (pure
        store-roots-only — the same predicate commit_archive and
        restore_build use); this is the Session seam over it.
        """
        return ops.protected_paths(self.store.root,
                                   self.exports_store.root)(path)

    def _guard_write(self, path, allow_same=False):
        """Refuse dangerous build targets.

        Every write path (flash, export, restore_vanilla, the CLI
        apply family) calls this BEFORE building: no protected path,
        and (unless allow_same, for in-place flash/restore) no
        target == the open archive. -> normalized absolute path.
        """
        p = os.path.abspath(path)
        if self._is_protected(p):
            raise SessionError(
                f"refusing to write {p} — it is a protected app file "
                "(the stored vanilla copy, a backup, or the export store)")
        if not allow_same and self.source_path and \
                os.path.normcase(p) == os.path.normcase(self.source_path):
            raise SessionError(
                f"refusing to write {p} — it is the OPEN archive itself "
                "(use 'Save to live'/flash for in-place saves)")
        return p

    def default_target(self):
        """Where 'Save to live' / 'Restore vanilla' write by default.

        The persisted live location when set, else the opened archive —
        unless that is one of the app's own protected files (then None:
        the user must set the live location first).
        """
        live = self.live_path()
        if live:
            return live
        if self.source_path and not self._is_protected(self.source_path) \
                and not self._in_exports_store(self.source_path):
            return self.source_path
        return None

    def _in_exports_store(self, path):
        p = os.path.normcase(os.path.realpath(path))
        root = os.path.normcase(os.path.realpath(self.exports_store.root))
        return p.startswith(root + os.sep)

    def has_restore_source(self):
        """True if Restore-vanilla has something to restore from."""
        return self.exports_store.has_vanilla_copy() or self.store.has_vanilla

    def _restore_source(self):
        """(path, md5, label) of the best vanilla source (pure
        ops.restore_source)."""
        return ops.restore_source(self.store, self.exports_store)

    def restore_source_label(self):
        """Human label of what Restore-vanilla would copy from (or None)."""
        try:
            return self._restore_source()[2]
        except SessionError:
            return None

    def baselines(self):
        """The THREE baseline sources, named.

        -> {"opened": the archive the session has open (the build
            baseline — every edit applies on top of THIS),
            "reference_vanilla": the PROVIDED data1.rda_vanilla copy
            (the reference column source), or None,
            "restore_source": (path, label) of what Restore-vanilla
            would copy from — the provided copy when stored, else the
            first-open snapshot (labelled unverified), or None.

        The three are NOT interchangeable: 'restore_source' may be an
        unverified first-open snapshot, 'reference_vanilla' is None
        until the user provides a copy, and 'opened' may be a
        modded file. UI code should read THIS instead of ad-hoc
        mixing the three."""
        out = {"opened": self.source_path if self.proj else None,
               "reference_vanilla": None,
               "restore_source": None}
        if self.exports_store.has_vanilla_copy():
            out["reference_vanilla"] = self.exports_store.vanilla_path
        try:
            p, _md5, label = self._restore_source()
            out["restore_source"] = (p, label)
        except SessionError:
            pass
        return out

    # ------------------------------------------------------------ flash/restore

    def _commit_archive(self, target, build_tmp):
        """THE ONLY route that may replace a game file .
        Pure ops.commit_archive — kept as the Session seam; the pure
        workers (ops.flash_build / ops.restore_build) call
        ops.commit_archive directly."""
        return ops.commit_archive(self.store, target, build_tmp)

    def _rebase_build(self, target):
        """The build base for 'save to live' (pure ops.rebase_build
        over the opened entries)."""
        return ops.rebase_build(self.proj.entries, target)

    def apply_ledger_reverts(self, target):
        """Queue REVERT records for CLEARED edits from the per-target
        write ledger.

        The write ledger records, per save target, the keys a
        successful commit WROTE with the value written and the base
        value it replaced. A ledger key the session NO LONGER has
        pending, whose recorded base the OPENED archive endorses
        (opened value == recorded base), is a CLEARED edit: the user
        saved a value, then removed it from pending. The next save
        reverts the key to the recorded base, so clearing an edit after
        saving it is an exact operation.

        The endorsement classifier is ledger.cleared_keys, shared with
        drift classification. Insert-shaped writes (a leaf absent from the
        opened archive) cannot be reverted by writing a value back —
        the engine has no delete-leaf operation; they are returned as
        unrevertable (restore-snapshot stays their exact undo).
        Idempotent: a re-run finds the same keys already queued.
        -> (n_queued, [unrevertable 'name / key' strings]).
        """
        if not self.proj:
            return 0, []
        self._assert_ui_thread()
        led = ledger_mod.load(self.store, target)
        if not led:
            return 0, []
        cleared, unrevert = ledger_mod.cleared_keys(
            led, self.cs, self.proj, list(self.roster))
        queued = 0
        with self._write_lock():
            for (kind, key), rec in sorted(cleared.items(),
                                           key=lambda kv: str(kv[0])):
                try:
                    if kind == "AI profile":
                        guid, path = key
                        # from_reference=True: the recorded base comes from
                        # the tool's own ledger (a verified prior write),
                        # so dataset re-validation is skipped — a broken
                        # datasets.xml must not abort the revert.
                        self.cs.add_dial(guid, path, str(rec["base"]),
                                         rule="revert", from_reference=True)
                    elif kind == "AI relations":
                        guid, relkind = key
                        self.cs.add_rel(guid, relkind,
                                        tuple(str(g) for g in rec["base"]),
                                        rule="revert")
                    elif kind == "EXTRAS":
                        asset, tag, occ = key
                        self.cs.add_extra(asset, tag, str(rec["base"]),
                                          occ=occ, rule="revert")
                    elif kind == "FERTILITY":
                        tier, crop = key
                        self.cs.add_fert(tier, crop,
                                         north=rec["base"].get("north"),
                                         south=rec["base"].get("south"),
                                         rule="revert")
                    else:
                        continue
                    queued += 1
                except ChangeSetError:
                    # A revert that cannot be queued cleanly (e.g. a
                    # vanished asset) is skipped, never a save-refusing
                    # exception: the pending edits still save; the
                    # ledger key stays for the next pass.
                    unrevert = unrevert + [f"{key[0]} / {key[-1]}"]
        return queued, unrevert

    def prepare_flash(self, target=None, snapshot=None):
        """Freeze EVERYTHING a flash needs, on
        the calling (UI) thread. -> (cs, target, in_place); raises before
        anything is built (no pending changes, a protected target). The
        GUI passes the returned cs + frozen inputs to ops.flash_build on
        a worker thread and the FlashResult to apply_flash_result on the
        Tk thread."""
        if not self.proj:
            raise SessionError("no archive open")
        self._assert_ui_thread()
        target = os.path.abspath(target or self.source_path)
        if self._is_protected(target):
            raise SessionError(
                f"refusing to overwrite {target} — it is the app's stored "
                "vanilla copy / backup. Set the game's live location and "
                "save there instead.")
        # The write ledger's CLEARED keys are queued as revert records
        # BEFORE the snapshot: both save paths (sync CLI + GUI worker)
        # consume the same snapshot, and the review/plan hash the GUI
        # freezes next already include them. The ledger only ever
        # endorses keys whose recorded base the OPENED archive carries —
        # a re-edit of a saved key stays the user's own pending row.
        n_rev, _unrev = self.apply_ledger_reverts(target)
        if snapshot is None:
            if not any(self.changes.values()) and not self.extras \
                    and not self.fert and not self.rels:
                raise SessionError("no pending changes — nothing to flash")
            snapshot = self.cs.snapshot()
        in_place = (os.path.normcase(target)
                    == os.path.normcase(self.source_path))
        return snapshot, target, in_place

    def flash(self, target=None, snapshot=None):
        """Build the pending changes and write them OVER target (atomic).

        Goes through ops.commit_archive (snapshot before the replace,
        Windows file-lock message). The pure phase is ops.flash_build on
        frozen inputs; the commit is apply_flash_result. This sync
        wrapper is the CLI/tests path (Session._build is passed as
        build_fn, so tests can patch it).

        snapshot: an ALREADY-FROZEN ChangeSet snapshot taken
        on the CALLER's thread. -> report dict.
        """
        cs, target, in_place = self.prepare_flash(target, snapshot)
        # An IN-PLACE save refuses when the file
        # changed on disk since open (another tool wrote it between
        # our open and this save) — expected_md5 is checked inside
        # commit_archive BEFORE anything is replaced.
        res = ops.flash_build(
            self._write_lock, self.store, self.proj.entries,
            self.source_path, self._build, cs, target, in_place,
            expected_md5=self.source_md5 if in_place else None,
            roster=list(self.roster))
        return self.apply_flash_result(res)

    def apply_flash_result(self, res):
        """Tk-thread commit of ops.flash_build: subtractive
        clear of the flashed edits (edits queued while the build ran stay
        pending) and in-place reload of the project. -> report dict."""
        self._assert_ui_thread()
        if res.in_place:
            # Source_md5 describes the file on disk.
            # report["md5"] is md5_of(target) computed inside commit_archive
            # from the exact replaced bytes; commit["new_md5"] is the same
            # value — prefer it when present (identical by construction).
            self.source_md5 = res.report.get("new_md5") or res.report["md5"]
            # refined by refined by
            # VALUE-EQUALITY subtractive clear — a key is dropped
            # only when the CURRENT pending record still EQUALS the
            # frozen one the build consumed. The old key-based clear
            # silently dropped a same-key RE-EDIT made during the
            # 30-60 s build (user typed 50, then 77 -> the 77 was
            # lost, the file carried 50, nothing was pending, ).
            for (guid, path), e in list(res.cs.dials.items()):
                self.cs.drop_dial_if(guid, path, e)
            for (guid, kind), e in list(res.cs.rels.items()):
                self.cs.drop_rel_if(guid, kind, e)
            for key, e in list(res.cs.extras.items()):
                self.cs.drop_extra_if(key, e)
            for key, e in list(res.cs.fert.items()):
                self.cs.drop_fert_if(key, e)
            if not self.cs:
                self.modes = {}
            self.proj = res.new_proj
        return res.report

    def restore_vanilla(self, target=None, full=False):
        """Restore the stored vanilla over target (default: the live
        location, else the open archive). -> the restored md5.

        Surgical by default (only ops.RESTORE_MEMBERS are restored;
        untracked live content is kept), the stored copy is verified
        against its recorded md5, and a pre-restore snapshot is taken
        before the replace. The pure phase is ops.restore_build; the
        commit is apply_restore_result. This sync wrapper is the
        CLI/tests path."""
        if target is None:
            if not self.proj:
                raise SessionError(
                    "no archive open — pass a target or set the live location")
            target = self.source_path
        target = os.path.abspath(target)
        if self._is_protected(target):
            raise SessionError(f"refusing to overwrite {target} — it is the "
                               "stored vanilla copy itself")
        self._assert_ui_thread()
        # Freeze the pending state now: an in-place restore clears only
        # what was pending at this point, so edits made during the
        # restore are kept.
        cs_snap = self.cs.snapshot()
        res = ops.restore_build(
            self._write_lock, self.store, self.exports_store, target,
            full, self.source_path, cs=cs_snap)
        return self.apply_restore_result(res)

    def apply_restore_result(self, res):
        """Tk-thread commit of ops.restore_build: when the open archive
        was the target, reload it and clear the edits that were pending
        when the restore started (edits queued during a background
        restore are kept). -> the restored md5."""
        self._assert_ui_thread()
        if res.in_place:
            # Use the md5 of the bytes actually written (a repacked
            # surgical restore differs from the vanilla source md5).
            self.source_md5 = res.new_md5 or res.vmd5
            # Clear only what the frozen snapshot held, not everything:
            # edits queued or re-edited during the restore stay pending.
            base = res.cs if res.cs is not None else ChangeSet()
            for (guid, path), e in list(base.dials.items()):
                self.cs.drop_dial_if(guid, path, e)
            for (guid, kind), e in list(base.rels.items()):
                self.cs.drop_rel_if(guid, kind, e)
            for key, e in list(base.extras.items()):
                self.cs.drop_extra_if(key, e)
            for key, e in list(base.fert.items()):
                self.cs.drop_fert_if(key, e)
            if not self.cs:
                self.modes = {}
            self.proj = res.new_proj
        return res.vmd5

