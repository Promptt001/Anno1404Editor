#!/usr/bin/env python3
"""fixture — the canonical test fixture resolver.

Import this from every test module instead of hand-rolling a TEST_RDA path:

    from fixture import TEST_RDA, IS_SYNTHETIC, real_rda, with_session_tmp

Resolution order:

  1. ANN0140_TEST_RDA is set            -> that archive, IS_SYNTHETIC=False
  2. otherwise                          -> build the synthetic archive
                                          (tests/synthetic_rda.py) into a
                                          shared temp dir, IS_SYNTHETIC=True

So the suite runs everywhere: no test depends on a private copy of the
game archive unless it is explicitly marked @real_rda.

Isolation: importing this module pins ANN0140_HOME (the single
user-state root, annoedit/homevar.py) to a temp dir unless the runner
already set one — no test can then touch the real ~/.anno1404gameeditor,
no matter which store it opens (backups, exports, presets, settings, log).

real_rda is a class/method decorator marking the handful of tests that
genuinely need the REAL vanilla archive (md5 pins, persona equivalence,
persona names, the German i18n corpus). They skip (with a clear message)
whenever the fixture is synthetic.

home_untouched() asserts the real home dir was never created or modified
during this process — run_tests.py calls it after the suite.
"""
import atexit
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

# single-root isolation: never touch the real home dir
_HOME = os.path.join(os.path.expanduser("~"), ".anno1404gameeditor")
_HOME_EXISTS_AT_START = os.path.isdir(_HOME)
if _HOME_EXISTS_AT_START:
    _HOME_SNAPSHOT = {}
    for _dirpath, _dirnames, _filenames in os.walk(_HOME):
        for _fn in _filenames:
            _fp = os.path.join(_dirpath, _fn)
            try:
                _HOME_SNAPSHOT[_fp] = os.stat(_fp).st_mtime
            except OSError:
                pass
else:
    _HOME_SNAPSHOT = None

if not (os.environ.get("ANN0140_HOME") or os.environ.get("ANN0140_EXPORTS_DIR")
        or os.environ.get("ANN0140_SETTINGS_DIR") or os.environ.get("ANN0140_LOG_FILE")):
    # One shared temp root for this whole test process (and its CLI
    # subprocesses, which inherit the environment). Legacy per-store vars
    # are honoured by homevar with higher precedence, so tests that set
    # them explicitly keep working.
    os.environ["ANN0140_HOME"] = tempfile.mkdtemp(prefix="annoedit_test_home_")

# The threading rule, ON for the whole suite
# Session mutators assert they run on the UI (main) thread; workers must
# run the pure annoedit.ops functions. A test that mutates the Session
# from a worker thread fails loudly instead of racing (~1-in-30).
os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

_TMP_ROOTS = []


def _register_tmp(path):
    _TMP_ROOTS.append(path)
    return path


atexit.register(lambda: [shutil.rmtree(t, ignore_errors=True)
                         for t in _TMP_ROOTS])


def home_untouched():
    """-> (ok: bool, message: str). True iff the real home dir is unchanged."""
    if not _HOME_EXISTS_AT_START:
        return (not os.path.isdir(_HOME),
                f"real home dir {_HOME} was CREATED during the test run")
    now = {}
    for dirpath, _dirnames, filenames in os.walk(_HOME):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                now[fp] = os.stat(fp).st_mtime
            except OSError:
                pass
    created = sorted(set(now) - set(_HOME_SNAPSHOT))
    modified = sorted(fp for fp in set(now) & set(_HOME_SNAPSHOT)
                      if now[fp] != _HOME_SNAPSHOT[fp])
    if created or modified:
        return False, (f"real home dir {_HOME} modified during the run: "
                       f"created={created[:5]} modified={modified[:5]}")
    return True, ""


# the canonical test archive
_env_rda = os.environ.get("ANN0140_TEST_RDA")
if _env_rda:
    TEST_RDA = _env_rda
    IS_SYNTHETIC = False
else:
    from synthetic_rda import make_synthetic_rda
    _d = _register_tmp(tempfile.mkdtemp(prefix="annoedit_test_synthetic_"))
    TEST_RDA = make_synthetic_rda(os.path.join(_d, "data1.rda"))
    IS_SYNTHETIC = True


def real_rda(cls_or_fn):
    """Skip marker for tests that need the REAL vanilla data1.rda.

    Use as a class or method decorator. Skips with a clear message when
    the fixture is the synthetic archive (set ANN0140_TEST_RDA to run
    them against a real archive).
    """
    reason = ("needs the real vanilla data1.rda (set ANN0140_TEST_RDA)"
               if IS_SYNTHETIC else "")
    return unittest.skipUnless(not IS_SYNTHETIC, reason)(cls_or_fn)


HAVE_RDA = os.path.isfile(TEST_RDA)
