#!/usr/bin/env python3
"""applog — the app's log file (every session, open, flash, restore…).

One append-only log at ~/.anno1404gameeditor/annoedit.log (the
ANN0140_LOG_FILE env var overrides the path — tests use it to keep the
real home untouched). Entries are one line each:

    2026-10-03T14:20:01  open  path=/…/data1.rda  md5=aa4546d0d9f4…  files=4474

The log is capped: when it exceeds MAX_BYTES it is rotated once (kept
as annoedit.log.1, previous rotation dropped), so it can never grow
without bound. Failures to log are silently ignored — logging must
never break the editor.
"""
import os
import sys
import time

MAX_BYTES = 512 * 1024
KEEP = 1


def log_path():
    """Absolute path of the log file (env override aware)."""
    from .homevar import log_file_path
    return log_file_path()


def log(event, **kv):
    """Append one timestamped entry; best-effort, never raises."""
    try:
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.isfile(p) and os.path.getsize(p) > MAX_BYTES:
            # One rotation: os.replace overwrites any existing ".1".
            os.replace(p, p + f".{KEEP}")
        parts = [f"{k}={v}" for k, v in kv.items()]
        line = time.strftime("%Y-%m-%dT%H:%M:%S") + "  " + event
        if parts:
            line += "  " + "  ".join(parts)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:   # noqa: BLE001 — logging must never raise
        pass


def tail(n=40):
    """Last n log lines (for display); empty list when no log yet."""
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip("\n") for l in lines[-n:]]
    except OSError:
        return []


def startup_note():
    """Log the process start (call once at app/CLI entry)."""
    log("startup", pid=os.getpid(),
        python=f"{sys.version_info.major}.{sys.version_info.minor}")
