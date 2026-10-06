#!/usr/bin/env python3
"""Per-target snapshot store.

- A save to one target (e.g. the live game file) keeps its pre-save
  snapshot no matter how many other targets save.
- Snapshots are listed per target (id/target/md5/reason) and restorable
  atomically with md5 verification.
- Flat pre-flash-*.rda files from earlier releases migrate into the tree
  and remain part of the skip set.
- The CLI lists and restores snapshots.
"""
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

from annoedit.backup import BackupStore, BackupError          # noqa: E402
from annoedit import cli                                      # noqa: E402


class PerTargetSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p5snap_")
        self.addCleanup(shutil.rmtree, self.W, ignore_errors=True)
        self.store = BackupStore(root=self.W + "/store")
        self.live = self.W + "/gamedir/data1.rda"
        os.makedirs(os.path.dirname(self.live))
        with open(self.live, "wb") as f:
            f.write(b"LIVE-ORIGINAL")

    def _save_over(self, target, data, reason="export"):
        # the commit path: read old bytes, snapshot, replace
        if not os.path.isfile(target):
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "wb") as f:
                f.write(b"PRE-EXISTING-" + os.path.basename(target)
                        .encode())
        old = open(target, "rb").read()
        _, written = self.store.snapshot_pre_flash_bytes(
            old, _md5(old), skip_md5s=(), target=target, reason=reason)
        with open(target, "wb") as f:
            f.write(data)
        return written

    def test_live_snapshot_survives_export_overwrites(self):
        # THE regression: one save-to-live, then SIX export overwrites
        # — the live pre-save snapshot must survive them all (the old
        # global 5-slot rotation evicted it, leaving the live save with
        # NO undo).
        self._save_over(self.live, b"LIVE-EDITED-1", reason="flash")
        for i in range(6):
            exp = self.W + f"/exports/data1_export_{i}.rda"
            self._save_over(exp, b"EXPORT-%d" % i)
        rows = self.store.snapshots(self.live)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "flash")
        self.assertEqual(rows[0]["md5"], _md5(b"LIVE-ORIGINAL"))
        # the export targets each have their own pool too
        self.assertEqual(len(self.store.snapshots(
            self.W + "/exports/data1_export_5.rda")), 1)

    def test_snapshot_listing_and_ids(self):
        self._save_over(self.live, b"LIVE-EDITED-1", reason="flash")
        rows = self.store.snapshots()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["target"], os.path.abspath(self.live))
        self.assertEqual(r["reason"], "flash")
        self.assertIn("/", r["id"])             # '<key>/<sid>' id form
        # a fresh store sees nothing
        self.assertEqual(BackupStore(root=self.W + "/empty").snapshots(), [])

    def test_restore_snapshot_roundtrip(self):
        self._save_over(self.live, b"LIVE-EDITED-1", reason="flash")
        sid = self.store.snapshots(self.live)[0]["id"]
        got = self.store.restore_snapshot(sid, self.live)
        self.assertEqual(got, _md5(b"LIVE-ORIGINAL"))
        self.assertEqual(open(self.live, "rb").read(), b"LIVE-ORIGINAL")
        # The restore routes through the commit protocol: the
        # CURRENT target bytes (LIVE-EDITED-1) are snapshotted
        # BEFORE the replace — the restore is itself undoable
        # (the STRONGER invariant; the old pin asserted the
        # snapshot count never grew, pinning the no-pre-restore-
        # snapshot data-loss shape).
        rows = self.store.snapshots(self.live)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["reason"] for r in rows},
                         {"flash", "restore-snapshot"})
        # the restore's own snapshot restores the edited state back
        sid2 = [r["id"] for r in rows if r["reason"] == "restore-snapshot"][0]
        self.store.restore_snapshot(sid2, self.live)
        self.assertEqual(open(self.live, "rb").read(), b"LIVE-EDITED-1")

    def test_restore_snapshot_refusals(self):
        self._save_over(self.live, b"LIVE-EDITED-1")
        rows = self.store.snapshots(self.live)
        sid, src = rows[0]["id"], rows[0]["path"]
        with self.assertRaises(BackupError):    # unknown id
            self.store.restore_snapshot("deadbeef/x", self.live)
        with open(src, "wb") as f:              # corrupt snapshot
            f.write(b"CORRUPT-BYTES")
        with self.assertRaises(BackupError):
            self.store.restore_snapshot(sid, self.live)
        # a target INSIDE the store itself is refused
        self._save_over(self.live, b"LIVE-EDITED-2")
        sid2 = self.store.snapshots(self.live)[0]["id"]
        with self.assertRaises(BackupError):
            self.store.restore_snapshot(sid2, self.store.root)
        with self.assertRaises(BackupError):   # bad id form
            self.store.restore_snapshot("no-slash", self.live)

    def test_legacy_flat_snapshots_migrate(self):
        # pre-per-target releases wrote pre-flash-*.rda at the store
        # ROOT — they must move into pre-flash/legacy/ and keep
        # counting for the skip set, not be orphaned forever.
        import hashlib, time as _t
        data = b"LEGACY-BYTES"
        md5 = hashlib.md5(data).hexdigest()
        legacy = os.path.join(self.store.root,
                              f"pre-flash-{md5}-{int(_t.time())}.rda")
        with open(legacy, "wb") as f:
            f.write(data)
        self.assertIn(md5, self.store.snapshot_skip_md5s(md5))
        self.assertFalse(os.path.exists(legacy))
        moved = os.path.join(self.store.root, "pre-flash", "legacy",
                             os.path.basename(legacy))
        self.assertTrue(os.path.isfile(moved))
        # still skipped after migration (scan covers the tree)
        self.assertIn(md5, self.store.snapshot_skip_md5s(md5))

    def test_cli_snapshots_and_restore(self):
        # the CLI constructs its own BackupStore from ANN0140_HOME —
        # redirect it to this test's store root (the recurring
        # home-isolation gotcha)
        os.environ["ANN0140_HOME"] = self.W
        os.environ["ANN0140_BACKUPS_DIR"] = self.store.root
        self.addCleanup(os.environ.pop, "ANN0140_BACKUPS_DIR", None)
        self._save_over(self.live, b"LIVE-EDITED-1", reason="flash")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["snapshots"])
        self.assertEqual(rc, 0)
        self.assertIn("flash", buf.getvalue())
        sid = self.store.snapshots(self.live)[0]["id"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["restore-snapshot", sid, self.live])
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.live, "rb").read(), b"LIVE-ORIGINAL")
        # unknown id -> clean error, exit 2
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["restore-snapshot", "nope/x", self.live])
        self.assertEqual(rc, 2)

    def test_commit_archive_records_target_and_reason(self):
        # the commit path (not the GUI) writes the per-target manifest
        import hashlib as _h
        from annoedit import ops
        tmp = self.live + ".newtmp"
        with open(tmp, "wb") as f:
            f.write(b"BUILD-BYTES")
        commit = ops.commit_archive(
            self.store, self.live, tmp, snapshot_reason="flash")
        self.assertTrue(commit["snapshot_written"])
        rows = self.store.snapshots(self.live)
        self.assertEqual(rows[0]["reason"], "flash")
        self.assertEqual(rows[0]["target"], os.path.abspath(self.live))
        self.assertEqual(rows[0]["md5"], _md5(b"LIVE-ORIGINAL"))
        self.assertEqual(open(self.live, "rb").read(), b"BUILD-BYTES")


def _md5(b):
    import hashlib
    return hashlib.md5(b).hexdigest()


if __name__ == "__main__":
    unittest.main(verbosity=2)
