#!/usr/bin/env python3
"""exports — the user's saved data1.rda manager.

The tool keeps every data1.rda copy the user makes under one
directory (default ~/.anno1404gameeditor/exports/):

    data1.rda_vanilla          the player-provided vanilla archive
                               (captured write-once, never overwritten)
    data1.rda_<exportname>     named exports the user builds

File naming is EXACTLY 'data1.rda_' + the export name the user
assigned (validated to a safe charset; 'vanilla' is reserved).

The store is display-free and unit-testable; the GUI/CLI only wire
dialogs around it, exactly like BackupStore.
"""
import hashlib
import json
import os
import string
import time


class ExportsError(Exception):
    """Raised on export-store failures: bad names, missing files."""


SAFE_CHARS = set(string.ascii_letters + string.digits + "-_.")
RESERVED_NAMES = {"vanilla", "backup", "exports"}


def slug_export_name(name):
    """Sanitize a user-assigned export name -> safe filename stem.

    Spaces become underscores; anything outside [A-Za-z0-9-_.] is
    dropped. Raises ExportsError on empty or reserved results.
    """
    s = str(name or "").strip().replace(" ", "_")
    s = "".join(c for c in s if c in SAFE_CHARS)
    if not s:
        raise ExportsError("export name must contain letters/digits")
    if s.strip("._-") == "":
        raise ExportsError("export name must contain letters or digits")
    if s.lower() in RESERVED_NAMES:
        raise ExportsError(f"{s!r} is a reserved export name")
    # A name ending in .json would overwrite another export's metadata;
    # .tmp collides with the atomic-write temp names.
    if s.endswith((".json", ".tmp")):
        raise ExportsError(
            f"{s!r} is not a valid export name (reserved suffix)")
    return s


class ExportStore:
    """The exports directory: named saved copies of data1.rda."""

    PREFIX = "data1.rda_"
    VANILLA = PREFIX + "vanilla"

    def __init__(self, root=None):
        """root defaults to ~/.anno1404gameeditor/exports/.

        ANN0140_EXPORTS_DIR env var overrides the default (tests use it
        to keep the real home dir untouched).
        """
        if root is None:
            from .homevar import exports_root
            root = exports_root()
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    # -- paths ------------------------------------------------------------

    def path_for(self, export_name):
        """Store path of one named export (data1.rda_<name>)."""
        return os.path.join(self.root, self.PREFIX + export_name)

    @property
    def vanilla_path(self):
        """Store path of the stored vanilla copy (data1.rda_vanilla)."""
        return os.path.join(self.root, self.VANILLA)

    def _meta_path(self, export_name):
        return self.path_for(export_name) + ".meta.json"

    # -- meta -------------------------------------------------------------

    def _read_meta(self, export_name):
        p = self._meta_path(export_name)
        if not os.path.isfile(p):
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write_meta(self, export_name, meta):
        tmp = self._meta_path(export_name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, self._meta_path(export_name))

    # -- vanilla copy md5 ---------------------------------------------------
    # data1.rda_vanilla is captured once together with its md5. Restore
    # verifies the copy against this md5 so a corrupted or replaced file is
    # detected instead of trusted.

    _VANILLA_META = "vanilla.meta.json"

    @property
    def _vanilla_meta_path(self):
        return os.path.join(self.root, self._VANILLA_META)

    def vanilla_copy_md5(self):
        """The md5 recorded when the vanilla copy was captured, or None.

        The recorded md5 lets restore VERIFY the stored
        copy before overwriting the live game file (the file on disk may
        have been corrupted, replaced or truncated since capture).
        """
        if not os.path.isfile(self._vanilla_meta_path):
            return None
        try:
            with open(self._vanilla_meta_path, encoding="utf-8") as f:
                m = json.load(f)
            return m.get("md5")
        except (OSError, ValueError):
            return None

    def _record_vanilla_md5(self, md5):
        """Persist the vanilla copy's md5 (atomic replace).

        The record is committed DURABLY and BEFORE the copy lands: an
        md5 record whose file does not exist yet is harmless
        (has_vanilla_copy checks the file), while a copy whose md5
        was never recorded would silently skip restore verification
        forever. Crash windows therefore never degrade safety.
        """
        # atomically commit the record before the copy is made
        tmp = self._vanilla_meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"md5": md5}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._vanilla_meta_path)

    # -- vanilla capture --------------------------------------------------

    def has_vanilla_copy(self):
        """True if the stored vanilla data1.rda_vanilla file exists."""
        return os.path.isfile(self.vanilla_path)

    def capture_vanilla_copy(self, rda_path):
        """Copy the player's vanilla archive to data1.rda_vanilla (write-once).

        Returns (md5, created): created=False means an identical copy
        already existed. The stored copy is NEVER overwritten.
        """
        from .backup import md5_of
        if not os.path.isfile(rda_path):
            raise ExportsError(f"no such archive: {rda_path}")
        md5 = md5_of(rda_path)
        if os.path.isfile(self.vanilla_path):
            with open(self.vanilla_path, "rb") as f:
                same = md5_of_stream(f) == md5
            if same:
                return md5, False
            raise ExportsError(
                "a different vanilla copy is already stored as "
                "data1.rda_vanilla — delete it via the export manager "
                "first if this is the one you want")
        # Commit the md5 record BEFORE the copy starts, and hash the copy
        # while it is read (one pass), so the stored md5 always describes
        # the stored bytes. A crash can leave "record, no file" (harmless:
        # has_vanilla_copy checks the file) or an orphan .tmp (swept
        # later), but never a copy without a record.
        self._record_vanilla_md5(md5)
        tmp = self.vanilla_path + ".tmp"
        h = hashlib.md5()
        with open(rda_path, "rb") as src, open(tmp, "wb") as out:
            while True:
                b = src.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
                out.write(b)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != md5:
            os.unlink(tmp)
            raise ExportsError(
                "the source file changed while it was being copied "
                f"({rda_path}) — the stored vanilla was NOT written; "
                "try again")
        os.replace(tmp, self.vanilla_path)
        return md5, True

    # -- named exports ------------------------------------------------------

    def save_named_export(self, rda_path, export_name, note="",
                          source_md5=None):
        """Save rda_path into the store as data1.rda_<exportname>.

        Overwriting an existing export of the same name is allowed (the
        user re-exports); returns the store path.
        """
        if str(export_name).strip().lower() == "vanilla":
            raise ExportsError("'vanilla' is reserved")
        name = slug_export_name(export_name)
        if not os.path.isfile(rda_path):
            raise ExportsError(f"no such archive: {rda_path}")
        from .backup import md5_of
        md5 = source_md5 or md5_of(rda_path)
        dest = self.path_for(name)
        if os.path.abspath(rda_path) == os.path.abspath(dest):
            # Already built into the store: only the meta needs writing
            # (copying a file onto itself would be destructive).
            self._write_meta(name, {
                "name": name,
                "note": note or "",
                "md5": md5,
                "source_path": os.path.abspath(rda_path),
                "size": os.path.getsize(rda_path),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            return dest
        tmp = dest + ".tmp"
        with open(rda_path, "rb") as src, open(tmp, "wb") as out:
            while True:
                b = src.read(1024 * 1024)
                if not b:
                    break
                out.write(b)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, self.path_for(name))
        self._write_meta(name, {
            "name": name,
            "note": note or "",
            "md5": md5,
            "source_path": os.path.abspath(rda_path),
            "size": os.path.getsize(rda_path),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return self.path_for(name)

    def save_named_build(self, export_name, build_fn, note=""):
        """Build a fresh export INTO the store: build_fn(tmp_path) -> report
        builds into a temp file in this store's directory, then the temp
        file is atomically os.replace'd to path_for(name) and the meta is
        written. -> report (with export_name/export_stored_path added).

        This is the only sanctioned way to write a named export: the
        whole store is a protected zone for Session._guard_write, so a
        build can never target exports/data1.rda_<name> directly.
        """
        name = slug_export_name(export_name)
        dest = self.path_for(name)
        tmp = dest + ".build.tmp"
        try:
            report = build_fn(tmp) or {}
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        try:
            os.replace(tmp, dest)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        from .backup import md5_of
        md5 = report.get("md5") or md5_of(dest)
        self._write_meta(name, {
            "name": name,
            "note": note or "",
            "md5": md5,
            "source_path": "",
            "size": os.path.getsize(dest),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        report["export_name"] = name
        report["export_stored_path"] = dest
        return report

    def list_exports(self):
        """-> [{name, path, md5, size, saved_at, note}] sorted by name.

        data1.rda_vanilla is listed FIRST (it is the user's stored
        vanilla copy, not a named export).
        """
        out = []
        if os.path.isfile(self.vanilla_path):
            out.append({"name": "vanilla", "path": self.vanilla_path,
                        "md5": None, "size": os.path.getsize(self.vanilla_path),
                        "saved_at": "", "note": "the stored vanilla copy"})
        for fn in sorted(os.listdir(self.root)):
            if not fn.startswith(self.PREFIX) or fn.endswith(".meta.json") \
                    or fn.endswith(".tmp") or fn == self.VANILLA:
                continue
            name = fn[len(self.PREFIX):]
            meta = self._read_meta(name)
            out.append({
                "name": name,
                "path": os.path.join(self.root, fn),
                "md5": meta.get("md5"),
                "size": os.path.getsize(os.path.join(self.root, fn)),
                "saved_at": meta.get("saved_at", ""),
                "note": meta.get("note", ""),
            })
        return out

    def load_export_path(self, export_name):
        """-> absolute path of one stored export; raise if missing."""
        if str(export_name).strip().lower() == "vanilla":
            # Checked before slug_export_name, which rejects the
            # reserved name.
            if not self.has_vanilla_copy():
                raise ExportsError("no stored vanilla copy "
                                   "(data1.rda_vanilla)")
            return self.vanilla_path
        name = slug_export_name(export_name)
        if name == "vanilla":
            if not self.has_vanilla_copy():
                raise ExportsError("no stored vanilla copy "
                                   "(data1.rda_vanilla)")
            return self.vanilla_path
        p = self.path_for(name)
        if not os.path.isfile(p):
            raise ExportsError(f"no saved export named {name!r}")
        return p

    def delete_export(self, export_name):
        """Delete one stored export (refuses the vanilla copy)."""
        if str(export_name).strip().lower() == "vanilla":
            # Reserved name: checked before slug_export_name.
            raise ExportsError(
                "the vanilla copy (data1.rda_vanilla) is managed via "
                "backup/restore — delete it only via the export manager "
                "explicitly if you must")
        name = slug_export_name(export_name)
        if name == "vanilla":
            raise ExportsError(
                "the vanilla copy (data1.rda_vanilla) is managed via "
                "backup/restore — delete it only via the export manager "
                "explicitly if you must")
        p = self.path_for(name)
        if not os.path.isfile(p):
            raise ExportsError(f"no saved export named {name!r}")
        os.unlink(p)
        try:
            os.unlink(self._meta_path(name))
        except OSError:
            pass
        return name

    def rename_export(self, old, new):
        """Rename one stored export (and its meta). -> new name."""
        oldn = slug_export_name(old)
        newn = slug_export_name(new)
        if oldn == newn:
            return newn
        if not os.path.isfile(self.path_for(oldn)):
            raise ExportsError(f"no saved export named {oldn!r}")
        # Case-insensitive filesystems (Windows/macOS): compare with
        # normcase and do a case-only rename via a temp hop.
        if os.path.exists(self.path_for(newn)) and \
                os.path.normcase(self.path_for(newn)) != \
                os.path.normcase(self.path_for(oldn)):
            raise ExportsError(f"an export named {newn!r} already exists")
        tmp = self.path_for(oldn) + ".case-rename.tmp"
        os.replace(self.path_for(oldn), tmp)
        os.replace(tmp, self.path_for(newn))
        mp = self._meta_path(oldn)
        if os.path.isfile(mp):
            meta = self._read_meta(oldn)
            meta["name"] = newn
            # On a case-insensitive filesystem a case-only rename makes
            # the new meta path the SAME file as the old one, so unlinking
            # the old path would delete the fresh meta. Hop via a temp.
            if os.path.normcase(mp) == os.path.normcase(self._meta_path(newn)):
                tmp = mp + ".meta-rename.tmp"
                os.replace(mp, tmp)
                self._write_meta(newn, meta)
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            else:
                self._write_meta(newn, meta)
                os.unlink(mp)
        return newn

    def delete_vanilla_copy(self):
        """Explicitly delete the stored data1.rda_vanilla copy."""
        if not self.has_vanilla_copy():
            raise ExportsError("no stored vanilla copy")
        os.unlink(self.vanilla_path)
        try:
            os.unlink(self._vanilla_meta_path)   # drop the recorded md5
        except OSError:
            pass
        return self.vanilla_path


def md5_of_stream(f, chunk=1024 * 1024):
    """MD5 of an open binary stream (helper; avoids double reads)."""
    import hashlib
    h = hashlib.md5()
    while True:
        b = f.read(chunk)
        if not b:
            break
        h.update(b)
    return h.hexdigest()
