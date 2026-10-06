"""backup — the safety subsystem: vanilla capture, restore, atomic flash.

Design rules:
  * The stored VANILLA backup is write-once: once captured, the tool never
    overwrites it. Restoring copies FROM it, never TO it.
  * All writes to the game's data1.rda are ATOMIC: build a temp file in the
    same directory, fsync, then os.replace() — a crash can never leave a
    half-written archive behind.
  * A session lock guards restore/flash sequences so two tool instances (or a
    double click) can't interleave.
  * Everything here is display-free and unit-testable; the GUI only wires
    dialogs around it.
"""
import hashlib
import json
import warnings
import os
import tempfile
import threading
import time
from datetime import datetime

try:                       # POSIX (Linux / Steam Deck / macOS)
    import fcntl
    msvcrt = None
except ImportError:        # Windows: no fcntl, use msvcrt locking instead
    fcntl = None
    import msvcrt


class BackupError(Exception):
    """Raised on backup-store failures: missing vanilla, lock contention."""



def fsync_dir(path):
    """Best-effort directory fsync (a rename is not durable until
    the containing directory entry is synced; POSIX-only, never fatal)."""
    try:
        fd = os.open(os.path.dirname(os.path.abspath(path)) or ".", os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _warn(msg):
    """Warnings module (a GUI has no stdout) — mirrors rda.py."""
    warnings.warn(msg, RuntimeWarning, stacklevel=2)


def md5_of(path, chunk=1024 * 1024):
    """MD5 hex digest of the file at path, hashed `chunk` bytes at a time."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _sha1_prefix(path, n=12):
    """Short sha1 of a target path — the per-target snapshot key.

    Snapshots are rotated PER SAVE TARGET (pre-flash/<key>/), so writes
    to one target (e.g. repeated export overwrites) can never evict
    another target's pre-save snapshots."""
    return hashlib.sha1(os.path.normcase(
        os.path.abspath(path)).encode("utf-8", "replace")).hexdigest()[:n]


def atomic_write_bytes(path, data):
    """Atomically (re)place path with data. Crash-safe: temp+fsync+rename.

    The target's existing file mode is preserved
    mkstemp creates 0600 files, which must never leak onto the live
    game archive.
    """
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    mode = None
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".flash_", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        try:
            os.replace(tmp, path)
        except PermissionError:
            # Windows: the game or Steam holds the file open. Say so
            # instead of showing a bare traceback.
            raise BackupError(
                f"cannot replace {path}: the file is locked — close the "
                "game (and Steam) first and try again") from None
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class BackupStore:
    """Manages the app-side backup directory.

    Layout (default ~/.anno1404gameeditor/backups/):
        vanilla-<md5>.rda        the captured vanilla archive (write-once)
        manifest.json           {vanilla_md5, captured_at, source_path, size}
        pre-flash snapshots     pre-flash-<md5>-<ts>.rda (kept, prunable)
    """

    KEEP_SNAPSHOTS = 5  # prune older pre-flash snapshots beyond this count

    def __init__(self, root=None):
        if root is None:
            from .homevar import backups_root
            root = backups_root()
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    # -- manifest ---------------------------------------------------------

    @property
    def manifest_path(self):
        """Full path of the store's manifest.json."""
        return os.path.join(self.root, "manifest.json")

    def _read_manifest(self):
        if not os.path.isfile(self.manifest_path):
            return {}
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except ValueError as e:
                # A corrupt manifest is treated as empty (with a
                # warning); the next capture rewrites a clean one.
                _warn(f"backup manifest corrupt ({e}) — treated as empty")
                return {}

    def _write_manifest(self, m):
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2)
        os.replace(tmp, self.manifest_path)

    # -- vanilla capture ----------------------------------------------------

    def vanilla_path(self, md5):
        """Store path of the vanilla archive file captured with this md5."""
        return os.path.join(self.root, f"vanilla-{md5}.rda")

    @property
    def has_vanilla(self):
        """True if a vanilla backup is recorded and its file is present."""
        m = self._read_manifest()
        return bool(m.get("vanilla_md5")) and os.path.isfile(
            self.vanilla_path(m["vanilla_md5"]))

    def capture_vanilla(self, rda_path):
        """Copy the FIRST-OPENED archive into the store (write-once, once).

        This is a first-open snapshot, not a verified vanilla. It is
        captured at most once (only when the manifest has no snapshot
        yet) and never re-captured for a new md5, so the store cannot
        grow by one archive copy per export/reopen. Orphaned
        vanilla-*.rda files the manifest does not reference are pruned
        on every capture call.

        Returns (md5, created) where created=False means nothing was
        written (a snapshot already exists — identity is NOT verified,
        because this is an unverified fallback, not the provided vanilla).
        """
        if not os.path.isfile(rda_path):
            raise BackupError(f"no such archive: {rda_path}")
        # Runs under the store session lock: the capture rewrites the
        # manifest and prunes *.tmp files in the store root, which must
        # never race a second tool instance's in-flight writes. The lock
        # is re-entrant within this store instance, so callers already
        # holding it are unaffected.
        with self.session_lock():
            return self._capture_vanilla_locked(rda_path)

    def _capture_vanilla_locked(self, rda_path):
        """The locked body of capture_vanilla — assumes the store lock."""
        m = self._read_manifest()
        if m.get("vanilla_md5"):
            # Capture once: an existing snapshot is never replaced, and
            # never duplicated for a different md5.
            self.prune_orphans()
            return m["vanilla_md5"], False
        md5 = md5_of(rda_path)
        dst = self.vanilla_path(md5)
        tmp = dst + ".tmp"
        with open(rda_path, "rb") as src, open(tmp, "wb") as out:
            while True:
                b = src.read(1024 * 1024)
                if not b:
                    break
                out.write(b)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dst)
        m.update({
            "vanilla_md5": md5,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "source_path": os.path.abspath(rda_path),
            "size": os.path.getsize(rda_path),
        })
        self._write_manifest(m)
        self.prune_orphans()
        return md5, True

    # Pruning of *.tmp files only ever happens under the store lock, so it
    # can never delete another instance's in-flight write.

    def store_report(self):
        """The store's disk usage: {root, total_bytes, files,
        vanilla_bytes, snapshot_bytes, snapshot_count}. The store can hold
        several archive-sized files (rolling pre-flash snapshots, the
        first-open snapshot and the stored vanilla copy)."""
        total = 0; files = 0
        van = 0; snaps = 0; snap_bytes = 0
        for fn in sorted(os.listdir(self.root)):
            fp = os.path.join(self.root, fn)
            if os.path.isdir(fp):
                # the per-target snapshot tree (pre-flash/<key>/...)
                if fn == "pre-flash":
                    for dirpath, _dn, fns in os.walk(fp):
                        for f2 in sorted(fns):
                            fp2 = os.path.join(dirpath, f2)
                            try:
                                sz = os.path.getsize(fp2)
                            except OSError:
                                continue
                            total += sz; files += 1
                            if f2.startswith("pre-flash-") and \
                                    f2.endswith(".rda"):
                                snaps += 1; snap_bytes += sz
                continue
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            total += sz; files += 1
            if fn == "data1.rda_vanilla" or fn.startswith("vanilla-"):
                van += sz
            if fn.startswith("pre-flash-"):
                snaps += 1; snap_bytes += sz
        return {"root": self.root, "total_bytes": total, "files": files,
                "vanilla_bytes": van, "snapshot_count": snaps,
                "snapshot_bytes": snap_bytes}

    def prune_orphans(self):
        """Delete vanilla-*.rda snapshots the manifest does not reference
        plus leftover .tmp files. -> list of removed names."""
        m = self._read_manifest()
        keep = set()
        if m.get("vanilla_md5"):
            keep.add(os.path.basename(self.vanilla_path(m["vanilla_md5"])))
        removed = []
        for fn in sorted(os.listdir(self.root)):
            if fn.endswith(".tmp"):
                try:
                    os.unlink(os.path.join(self.root, fn))
                    removed.append(fn)
                except OSError:
                    pass
                continue
            if fn.startswith("vanilla-") and fn.endswith(".rda") \
                    and fn not in keep:
                try:
                    os.unlink(os.path.join(self.root, fn))
                    removed.append(fn)
                    # Remove the memoized-md5 sidecar with its archive,
                    # or it could later describe a different file with
                    # the same name.
                    side = os.path.join(self.root, fn + ".md5")
                    if os.path.isfile(side):
                        try:
                            os.unlink(side)
                        except OSError:
                            pass
                except OSError:
                    pass
        return removed

    # -- restore -----------------------------------------------------------

    def restore_vanilla(self, rda_path):
        """Atomically copy the stored vanilla backup OVER rda_path.

        The stored backup itself is never touched. Raises if no vanilla
        captured. Returns the restored md5.
        """
        if not self.has_vanilla:
            raise BackupError("no vanilla backup captured yet")
        m = self._read_manifest()
        src = self.vanilla_path(m["vanilla_md5"])
        with open(src, "rb") as f:
            data = f.read()
        atomic_write_bytes(rda_path, data)
        return m["vanilla_md5"]

    # -- per-target pre-flash snapshots ------------------------------------

    def snap_dir(self, target_path):
        """Store dir for ONE save target's snapshots:
        pre-flash/<sha1(target)[:12]>/. The rotation is PER TARGET: one
        target's saves (e.g. repeated export overwrites) can never evict
        another target's pre-save snapshots."""
        d = os.path.join(self.root, "pre-flash", _sha1_prefix(target_path))
        os.makedirs(d, exist_ok=True)
        return d

    def _migrate_legacy_snapshots(self):
        """Move legacy root-level pre-flash-*.rda files into
        pre-flash/legacy/ (the flat pre-per-target layout). Best-effort
        and idempotent: nothing at root level -> no-op. Keeps the skip
        set honest (it scans the whole pre-flash tree)."""
        try:
            names = os.listdir(self.root)
        except OSError:
            return
        legacy = None
        for n in names:
            if n.startswith("pre-flash-") and n.endswith(".rda"):
                if legacy is None:
                    legacy = os.path.join(self.root, "pre-flash", "legacy")
                    os.makedirs(legacy, exist_ok=True)
                try:
                    os.replace(os.path.join(self.root, n),
                               os.path.join(legacy, n))
                except OSError:
                    pass

    def _snap_manifest(self, sdir):
        """Read one target's snapshot manifest.json -> dict ({} when
        missing or corrupt)."""
        p = os.path.join(sdir, "manifest.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                m = json.load(f)
                if isinstance(m, dict):
                    return m
        except (OSError, ValueError):
            pass
        return {}

    def _snap_write_manifest(self, sdir, m):
        p = os.path.join(sdir, "manifest.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2)
        os.replace(tmp, p)

    def snapshot_pre_flash(self, rda_path, md5=None, skip_md5s=(),
                          target=None):
        """Keep one rolling snapshot of the archive right before a
        flash. Reads the file once and delegates to
        snapshot_pre_flash_bytes (same naming, pruning and skip rules).
        -> the md5."""
        with open(rda_path, "rb") as f:
            data = f.read()
        _md5, _written = self.snapshot_pre_flash_bytes(
            data, md5 or md5_of(rda_path), skip_md5s=skip_md5s,
            target=target or rda_path)
        return _md5

    def snapshot_pre_flash_bytes(self, data, md5, skip_md5s=(),
                                 target=None, reason="pre-flash"):
        """Snapshot from in-memory bytes (the target content the caller
        already read) instead of re-reading the file.

        target — the save TARGET the snapshot belongs to: per-target
        rotation under pre-flash/<sha1(target)[:12]>/ with a manifest
        entry {target, md5, ts, reason} per snapshot, pruned per target
        (KEEP_SNAPSHOTS each). target=None keeps the legacy flat pool
        (compatibility for external callers).

        -> (md5, written): 'written' says whether THIS call stored
        anything (False when skipped as already preserved, or no data)."""
        if md5 in skip_md5s or not data:
            return md5, False
        ts = int(time.time())
        if target is None:
            dst = os.path.join(self.root,
                               f"pre-flash-{md5}-{ts}.rda")
            atomic_write_bytes(dst, data)
            snaps = sorted(
                (n for n in os.listdir(self.root)
                 if n.startswith("pre-flash-") and n.endswith(".rda")),
                key=lambda n: os.path.getmtime(os.path.join(self.root, n)))
            for old in snaps[:-self.KEEP_SNAPSHOTS]:
                try:
                    os.unlink(os.path.join(self.root, old))
                except OSError:
                    pass
            return md5, True
        self._migrate_legacy_snapshots()
        sdir = self.snap_dir(target)
        dst = os.path.join(sdir, f"pre-flash-{md5}-{ts}.rda")
        atomic_write_bytes(dst, data)
        sid = f"{md5[:12]}-{ts:x}"
        m = self._snap_manifest(sdir)
        m[sid] = {"target": os.path.abspath(target), "md5": md5,
                  "ts": ts, "reason": reason,
                  "file": os.path.basename(dst), "size": len(data)}
        # Per-target rotation: drop this target's oldest entries beyond
        # KEEP_SNAPSHOTS.
        over = sorted(m.items(), key=lambda kv: kv[1].get("ts") or 0)
        for k, e in over[:max(0, len(m) - self.KEEP_SNAPSHOTS)]:
            try:
                os.unlink(os.path.join(sdir, e.get("file", "")))
            except OSError:
                pass
            del m[k]
        self._snap_write_manifest(sdir, m)
        return md5, True

    def snapshots(self, target=None):
        """List stored pre-save snapshots, newest first.
        target — optional filter to one save target's pool.
        -> [{id, target, md5, ts, reason, path, size}] where id is the
        '<key>/<sid>' form 'annoedit restore-snapshot' takes."""
        out = []
        pf = os.path.join(self.root, "pre-flash")
        if not os.path.isdir(pf):
            return out
        want = None if target is None else _sha1_prefix(target)
        for key in sorted(os.listdir(pf)):
            sdir = os.path.join(pf, key)
            if not os.path.isdir(sdir):
                continue
            if want is not None and key != want:
                continue
            for sid, e in self._snap_manifest(sdir).items():
                fp = os.path.join(sdir, e.get("file", ""))
                try:
                    sz = e.get("size") or os.path.getsize(fp)
                except OSError:
                    sz = 0
                out.append({"id": f"{key}/{sid}",
                            "target": e.get("target"), "md5": e.get("md5"),
                            "ts": e.get("ts"), "reason": e.get("reason"),
                            "path": fp, "size": sz})
        out.sort(key=lambda e: e.get("ts") or 0, reverse=True)
        return out

    def read_snapshot(self, sid):
        """The VERIFIED bytes of a stored snapshot (pure read, no
        write — restore routes the write through the commit protocol).

        sid — the '<key>/<sid>' id listed by snapshots(). Raises
        BackupError on an unknown id, a missing snapshot file or an
        md5 mismatch (a corrupt snapshot — never restore unverified
        bytes over a game file).
        -> (data: bytes, md5: str)."""
        key, _, ident = sid.partition("/")
        if not key or not ident:
            raise BackupError(f"unknown snapshot id {sid!r}")
        sdir = os.path.join(self.root, "pre-flash", key)
        e = self._snap_manifest(sdir).get(ident)
        if not e:
            raise BackupError(f"unknown snapshot id {sid!r}")
        src = os.path.join(sdir, e.get("file", ""))
        if not os.path.isfile(src):
            raise BackupError(f"snapshot file missing: {src}")
        with open(src, "rb") as f:
            data = f.read()
        got = hashlib.md5(data).hexdigest()
        if got != e.get("md5"):
            raise BackupError(
                f"snapshot fails its md5 check ({src}) — it may be "
                "corrupt; refusing to restore")
        return data, got

    def restore_snapshot(self, sid, target_path, exports_store=None):
        """Restore a stored pre-save snapshot OVER target_path.

        THE WRITE GOES THROUGH THE COMMIT PROTOCOL (ops.commit_archive
        under the store session lock): protected targets (the stores,
        the stored vanilla copy) are refused up front, and the CURRENT
        target bytes are snapshotted BEFORE the replace, so restoring a
        snapshot is itself undoable.

        sid — the '<key>/<sid>' id listed by snapshots(). Raises
        BackupError on an unknown id, a missing snapshot file, an md5
        mismatch, or a protected target (inside either store).
        -> the restored md5."""
        from . import ops
        from .exports import ExportStore
        data, got = self.read_snapshot(sid)
        norm = os.path.normcase(os.path.realpath(
            os.path.abspath(target_path)))
        root = os.path.normcase(os.path.realpath(self.root))
        if norm == root or norm.startswith(root + os.sep):
            raise BackupError(
                f"refusing to restore over {target_path} — it is inside "
                "the backup store")
        # Route the replace through the single commit path (lock,
        # pre-restore snapshot of the current target, protected-path
        # refusal, mode preservation). The verified snapshot bytes are
        # staged to a tmp file in the target's own directory first.
        tdir = os.path.dirname(os.path.abspath(target_path)) or "."
        fd, tmp = tempfile.mkstemp(prefix=".annoedit-", suffix=".tmp",
                                   dir=tdir)
        # The protected-path policy needs both store roots: this backup
        # store and the exports store (where the stored vanilla copy
        # lives). commit_archive only checks the latter when it is
        # passed, so always pass one.
        if exports_store is None:
            exports_store = ExportStore()
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            with self.session_lock():
                ops.commit_archive(
                    self, target_path, tmp, exports_store=exports_store,
                    snapshot_reason="restore-snapshot")
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return got

    def snapshot_skip_md5s(self, current_md5):
        """Md5s already on file in the store — an existing pre-flash
        snapshot (by md5, anywhere in the per-target tree), the stored
        vanilla copy, the first-open snapshot. A snapshot of a
        byte-identical archive adds nothing."""
        skip = set()
        try:
            names = os.listdir(self.root)
        except OSError:
            return skip
        self._migrate_legacy_snapshots()
        cands = [n for n in names
                 if n.startswith("pre-flash-") and n.endswith(".rda")]
        pf = os.path.join(self.root, "pre-flash")
        if os.path.isdir(pf):
            for d in os.listdir(pf):
                sub = os.path.join(pf, d)
                if not os.path.isdir(sub):
                    continue
                for n in os.listdir(sub):
                    if n.startswith("pre-flash-") and n.endswith(".rda"):
                        cands.append(os.path.join("pre-flash", d, n))
        for rel in cands:
            parts = os.path.basename(rel).split("-")
            if len(parts) >= 3 and parts[2] == current_md5:
                skip.add(current_md5)
                break
        m = {}
        try:
            m = self._read_manifest()
        except Exception:
            m = {}
        if m.get("vanilla_md5"):
            # A recorded md5 only counts as preserved while the file still
            # exists with the recorded size (no re-hash: the capture
            # verified it). Otherwise a deleted backup would wrongly
            # suppress the pre-save snapshot.
            vp = self.vanilla_path(m["vanilla_md5"])
            ok = os.path.isfile(vp)
            if ok and m.get("size") is not None:
                try:
                    ok = os.path.getsize(vp) == m["size"]
                except OSError:
                    ok = False
            if ok:
                skip.add(m["vanilla_md5"])
        # vanilla-*.rda files the manifest does not reference: hash once
        # and memoize the result in a sidecar so later saves never re-hash.
        for n in names:
            if n.startswith("vanilla-") and n.endswith(".rda"):
                p = os.path.join(self.root, n)
                side = p + ".md5"
                if os.path.isfile(side):
                    try:
                        with open(side, encoding="utf-8") as f:
                            skip.add(f.read().strip())
                        continue
                    except OSError:
                        pass
                try:
                    h = md5_of(p)
                    skip.add(h)
                    try:
                        with open(side, "w", encoding="utf-8") as f:
                            f.write(h)
                    except OSError:
                        pass
                except OSError:
                    pass
        return skip

    # -- session lock ------------------------------------------------------

    def session_lock(self):
        """Context manager: an advisory flock on the store's lock file.

        Prevents two tool instances from interleaving restore/flash on the
        same machine. Re-entrant within one store
        instance (nested locks share the same _Flock and track depth); a
        second process still gets BackupError instead of silent corruption.
        """
        path = os.path.join(self.root, "session.lock")
        fl = getattr(self, "_lock_obj", None)
        if fl is None or fl.path != path:
            fl = _Flock(path)
            self._lock_obj = fl
        return fl


class _Flock:
    """Advisory session lock, re-entrant within one instance: nested
    `with` on the same object tracks depth and unlocks only at the
    outermost exit, while a second PROCESS gets BackupError.

    The depth counter is guarded by a threading.RLock because both a
    background worker and the Tk thread can enter the lock; the file
    lock still blocks other processes."""

    def __init__(self, path):
        self.path = path
        self.depth = 0
        self.fh = None
        self._mu = threading.RLock()

    def __enter__(self):
        with self._mu:
            if self.depth:           # already held by THIS instance
                self.depth += 1
                return self
            fh = open(self.path, "a+")
            try:
                if fcntl is not None:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fh.close()
                raise BackupError(
                    "another editor session holds the backup store "
                    f"lock ({self.path}) " + chr(0x2014) + " close it first")
            self.fh = fh
            self.depth = 1
            return self
        fh = open(self.path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            raise BackupError(
                "another editor session holds the backup store lock "
                f"({self.path}) — close it first")
        self.fh = fh
        self.depth = 1
        return self

    def __exit__(self, *exc):
        with self._mu:
            if self.depth > 1:       # inner nesting: keep it held
                self.depth -= 1
                return False
            try:
                if fcntl is not None:
                    fcntl.flock(self.fh, fcntl.LOCK_UN)
                else:
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            finally:
                self.fh.close()
                self.fh = None
            self.depth = 0
            return False


# -- change report -----------------------------------------------------------


def format_change_report(report, applied):
    """Human-readable pre-flash report.

    report  — dict from core's build ({out, files, blocks, changed, md5, ...})
    applied — {character (GUID): {dial path: new value, ...}}
    """
    lines = []
    lines.append("=== Pre-flash change report ===")
    lines.append(f"archive md5 (new): {report.get('md5')}")
    lines.append(f"entries:           {report.get('files')}")
    lines.append(f"files changed:     {len(report.get('changed', []))}")
    for f in report.get("changed", []):
        lines.append(f"  - {f}")
    lines.append("")
    total = 0
    for char, dials in applied.items():
        lines.append(f"{char}:")
        for path, val in dials.items():
            lines.append(f"    {path} -> {val}")
            total += 1
        lines.append("")
    lines.append(f"total dial edits:  {total}")
    # Data-identical, not byte-identical: write_rda repacks every block
    # and normalises layout/compression.
    lines.append("Every other file in the archive keeps its exact data "
                 "(content); the archive container is repacked, so the "
                 ".rda bytes are not bit-for-bit identical.")
    return "\n".join(lines)
