#!/usr/bin/env python3
"""appsettings — the app's persistent settings (JSON, tiny, atomic).

Lives at ~/.anno1404gameeditor/settings.json by default; the
ANN0140_SETTINGS_DIR env var overrides the directory (tests use it to
keep the real home untouched — same pattern as the exports store).

Known keys (all optional, nothing is required):
    live_path        absolute path of the game's live addon/data1.rda
                     (where Flash writes; NOT necessarily where the
                     vanilla copy was provided from)
    last_picker_dir  remembered by the in-app file picker
"""
import json
import os
import tempfile


class SettingsError(Exception):
    """Raised on settings-store failures: unreadable file, bad writes."""


class Settings:
    """Key/value settings persisted to one JSON file, written atomically."""

    def __init__(self, root=None):
        if root is None:
            from .homevar import settings_dir
            root = settings_dir()
        self.root = root
        os.makedirs(self.root, exist_ok=True)
        self.path = os.path.join(self.root, "settings.json")
        self._data = self._load()

    def _load(self):
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        # Unique temp name per write, so two processes saving at once
        # can never interleave into the same temp file.
        fd, tmp = tempfile.mkstemp(
            prefix=os.path.basename(self.path) + ".",
            suffix=".tmp", dir=os.path.dirname(self.path) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self, key, default=None):
        """Return one setting value (default when unset)."""
        return self._data.get(key, default)

    def set(self, key, value):
        """Store one setting and persist immediately."""
        if value is not None and not isinstance(value, (str, int, float,
                                                        bool)):
            raise SettingsError(f"unsupported setting value: {value!r}")
        # Merge-write: re-read the on-disk dict and overlay this key, so a
        # GUI and a CLI writing concurrently never drop each other's keys.
        try:
            with open(self.path, encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                disk.pop(key, None)
                disk[key] = value
                self._data = disk
        except (OSError, ValueError):
            self._data[key] = value
        self._save()
        return value

    def delete(self, key):
        """Remove one setting (no error when absent).

        Merge-write like set(): re-read the on-disk dict and remove the
        key there, so a concurrent writer's keys survive.
        """
        try:
            with open(self.path, encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                disk.pop(key, None)
                self._data = disk
        except (OSError, ValueError):
            pass
        self._data.pop(key, None)
        self._save()

    def as_dict(self):
        """Copy of all settings (for display/tests)."""
        return dict(self._data)
