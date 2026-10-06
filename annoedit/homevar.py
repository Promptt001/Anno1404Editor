#!/usr/bin/env python3
"""homevar — the single user-state root for annoedit.

One env var, ANN0140_HOME, redirects EVERYTHING the tool writes outside the
game directory: backups, exports, presets, settings.json and annoedit.log.

    ANN0140_HOME=/tmp/isolated python3 -m annoedit.cli ...

Precedence per store (first match wins):

    1. the store's legacy var (ANN0140_EXPORTS_DIR / ANN0140_SETTINGS_DIR /
       ANN0140_LOG_FILE / ANN0140_PRESETS_DIR / ANN0140_BACKUPS_DIR)
    2. ANN0140_HOME           -> <home>/backups, exports, presets, ...
    3. ~/.anno1404gameeditor/<name>

The per-store vars keep working; anything that sets only ANN0140_HOME
never touches ~/.anno1404gameeditor. Test isolation is therefore one env
var, and a test can assert the real home stays untouched.
"""
import os

DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".anno1404gameeditor")


def home_root():
    """Resolve the annoedit user-state root (ANN0140_HOME > ~/.anno1404gameeditor)."""
    return os.environ.get("ANN0140_HOME") or DEFAULT_ROOT


def store_root(name, legacy_var=None):
    """Root for a named store: legacy env var > ANN0140_HOME/<name> > home/<name>."""
    if legacy_var:
        legacy = os.environ.get(legacy_var)
        if legacy:
            return legacy
    return os.path.join(home_root(), name)


def backups_root():
    """The backup store root (ANN0140_BACKUPS_DIR legacy var honoured)."""
    return store_root("backups", legacy_var="ANN0140_BACKUPS_DIR")


def exports_root():
    """The export store root (ANN0140_EXPORTS_DIR legacy var honoured)."""
    return store_root("exports", legacy_var="ANN0140_EXPORTS_DIR")


def user_presets_dir():
    """The user's named-preset dir (ANN0140_PRESETS_DIR > ANN0140_HOME/presets)."""
    return store_root("presets", legacy_var="ANN0140_PRESETS_DIR")


def user_personas_dir():
    """The user's own persona files dir (ANN0140_PERSONAS_DIR > ANN0140_HOME/personas).

    Kept separate from presets/ (named presets) so that saving a named
    preset can never create a persona or shadow a shipped persona's name.
    """
    return store_root("personas", legacy_var="ANN0140_PERSONAS_DIR")


def settings_dir():
    """The settings dir (ANN0140_SETTINGS_DIR > ANN0140_HOME)."""
    legacy = os.environ.get("ANN0140_SETTINGS_DIR")
    if legacy:
        return legacy
    return home_root()


def log_file_path():
    """The activity-log file path (ANN0140_LOG_FILE > ANN0140_HOME/annoedit.log)."""
    legacy = os.environ.get("ANN0140_LOG_FILE")
    if legacy:
        return legacy
    return os.path.join(home_root(), "annoedit.log")
