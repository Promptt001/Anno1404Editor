#!/usr/bin/env python3
"""Snapshot/restore protocol regressions.

- Snapshot restore goes through the commit protocol (protected paths,
  pre-restore snapshot).
- CLI reports are JSON-safe after a write.
- The per-target snapshot pool never evicts another target's snapshots.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

# synthetic_rda lives NEXT TO this file (tests/); the annoedit package
# lives one level up. Insert both so this module imports cleanly under
# unittest discovery and direct invocation alike.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from annoedit.backup import BackupStore, BackupError          # noqa: E402
from annoedit import cli, ops                                  # noqa: E402
from synthetic_rda import make_synthetic_rda                   # noqa: E402


def _redirect_home(new_home, new_exports):
    """Point the home at new_home/new_exports, RESTORING the previous
    values on cleanup (a bare pop destroys a runner-provided
    ANN0140_HOME and later tests write into the real home)."""
    saved = {k: os.environ.get(k) for k in
             ("ANN0140_HOME", "ANN0140_EXPORTS_DIR")}
    os.environ["ANN0140_HOME"] = new_home
    os.environ["ANN0140_EXPORTS_DIR"] = new_exports

    def _restore():
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return _restore


class HotfixBatchTests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p0t_")
        self.addCleanup(shutil.rmtree, self.W, ignore_errors=True)
        self.store = BackupStore(root=self.W + "/store")
        self.live = self.W + "/gamedir/data1.rda"
        os.makedirs(os.path.dirname(self.live))
        with open(self.live, "wb") as f:
            f.write(b"LIVE-ORIGINAL")

    def test_restore_over_vanilla_copy_refused(self):
        # The trust anchor: a stored snapshot must never be restorable
        # over the stored vanilla copy in the exports store.
        import hashlib
        old = open(self.live, "rb").read()
        self.store.snapshot_pre_flash_bytes(
            old, hashlib.md5(old).hexdigest(), skip_md5s=(),
            target=self.live, reason="flash")
        sid = self.store.snapshots(self.live)[0]["id"]
        exp_root = self.W + "/exp"
        os.makedirs(exp_root)
        van = os.path.join(exp_root, "data1.rda_vanilla")
        with open(van, "wb") as f:
            f.write(b"VANILLA-BYTES")
        from annoedit.exports import ExportStore
        exp = ExportStore(root=exp_root)
        before = open(van, "rb").read()
        with self.assertRaises(Exception):
            self.store.restore_snapshot(sid, van, exports_store=exp)
        self.assertEqual(open(van, "rb").read(), before)

    def test_restore_creates_pre_restore_snapshot(self):
        # Restoring an old snapshot over live must keep a snapshot of
        # the CURRENT bytes — the restore itself is undoable.
        import hashlib
        old = open(self.live, "rb").read()
        self.store.snapshot_pre_flash_bytes(
            old, hashlib.md5(old).hexdigest(), skip_md5s=(),
            target=self.live, reason="flash")
        with open(self.live, "wb") as f:
            f.write(b"LIVE-EDITED")
        sid = self.store.snapshots(self.live)[0]["id"]
        self.store.restore_snapshot(sid, self.live)
        self.assertEqual(open(self.live, "rb").read(), b"LIVE-ORIGINAL")
        reasons = {r["reason"] for r in self.store.snapshots(self.live)}
        self.assertIn("restore-snapshot", reasons)
        # the restore's own snapshot brings the edited state back
        sid2 = [r["id"] for r in self.store.snapshots(self.live)
                if r["reason"] == "restore-snapshot"][0]
        self.store.restore_snapshot(sid2, self.live)
        self.assertEqual(open(self.live, "rb").read(), b"LIVE-EDITED")

    def test_cli_restore_snapshot_exit2_on_protected(self):
        import hashlib
        os.makedirs(self.W + "/exp", exist_ok=True)
        self.addCleanup(_redirect_home(self.W + "/home", self.W + "/exp"))
        van = os.path.join(self.W, "exp", "data1.rda_vanilla")
        with open(van, "wb") as f:
            f.write(b"VANILLA-BYTES")
        old = open(self.live, "rb").read()
        self.store.snapshot_pre_flash_bytes(
            old, hashlib.md5(old).hexdigest(), skip_md5s=(),
            target=self.live, reason="flash")
        sid = self.store.snapshots(self.live)[0]["id"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            # CLI route: BackupStore() default + ExportStore() default
            rc = cli.main(["restore-snapshot", sid, van])
        self.assertEqual(rc, 2, buf.getvalue())
        self.assertEqual(open(van, "rb").read(), b"VANILLA-BYTES")

    def test_jsonable_drops_non_json_values(self):
        # The CLI report sanitizer: bytes entries dropped, scalars kept.
        rep = {"out": "x.rda", "dial_edits": 3, "entries":
               {"addondata/config/ai/aiprofiles.xml": b"\x00raw"}}
        out = cli._jsonable(rep)
        self.assertNotIn("entries", out)
        self.assertEqual(out["dial_edits"], 3)

    def test_cli_apply_json_writes_valid_json(self):
        # apply --json must exit 0 and print valid JSON AFTER writing.
        os.makedirs(self.W + "/exp", exist_ok=True)
        self.addCleanup(_redirect_home(self.W + "/home2", self.W + "/exp"))
        src = make_synthetic_rda(os.path.join(self.W, "src.rda"))
        outp = os.path.join(self.W, "out.rda")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["apply", src, outp, "--char", "Leif",
                           "--persona", "The Admiral", "--json"])
        self.assertEqual(rc, 0, buf.getvalue())
        txt = buf.getvalue()
        data = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
        self.assertIn("md5", data)
        self.assertTrue(os.path.isfile(outp))

    def test_honest_badges_after_vanilla_click(self):
        # After a Vanilla click on an UNCHANGED character, the
        # per-character badge counts must be empty (no rule no-op rows).
        from annoedit.session import Session
        t = self.W
        van = make_synthetic_rda(os.path.join(t, "van.rda"))
        op = make_synthetic_rda(os.path.join(t, "op.rda"))
        s = Session(backup_root=os.path.join(t, "b"),
                    exports_root=os.path.join(t, "e"))
        s.provide_vanilla(van)
        s.open(op)
        s.set_mode(s.roster[0], "vanilla")
        c = s.pending_counts()
        self.assertEqual(c["dials"], 0)
        self.assertEqual(c["_by_guid"], {})


if __name__ == "__main__":
    unittest.main()
