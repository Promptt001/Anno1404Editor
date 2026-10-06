#!/usr/bin/env python3
"""Global revert, Hardened baseline and name-resolution semantics.

- A per-character Vanilla click leaves global EXTRAS/fertility alone;
  revert-globals is an explicit action (and refuses without a reference).
- Hardened derives from the stored vanilla copy when there is one, and is
  labelled "relative" otherwise.
- Exact name matches win over prefix matches.
- The CLI revert-globals command; insert anchors persist in named presets.
"""
import io
import os
import contextlib
import shutil
import tempfile
import unittest

os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

from annoedit.session import Session                    # noqa: E402
from annoedit.appsettings import Settings                # noqa: E402
from annoedit import cli                                 # noqa: E402
from tests.synthetic_rda import make_synthetic_rda       # noqa: E402

LEIF = "1645021"


def _mk_session(tag):
    root = tempfile.mkdtemp(prefix=tag)
    return Session(backup_root=root + "/b", exports_root=root + "/e",
                   settings=Settings(root + "/s")), root


class Phase5Tests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p5_")
        self.addCleanup(shutil.rmtree, self.W, ignore_errors=True)
        self.A = make_synthetic_rda(self.W + "/vanilla.rda")

    def test_p5_vanilla_mode_leaves_globals_alone(self):
        M = self.W + "/mod.rda"; make_synthetic_rda(M, variant=1)
        s, _ = _mk_session("p5a"); s.provide_vanilla(self.A); s.open(M)
        s.set_mode(s.proj.by_guid[LEIF], "vanilla")
        self.assertEqual(len(s.cs.extras), 0)
        self.assertEqual(len(s.cs.fert), 0)
        s.close()

    def test_p5_explicit_global_revert_queues(self):
        M = self.W + "/mod2.rda"; make_synthetic_rda(M, variant=1)
        s, _ = _mk_session("p5b"); s.provide_vanilla(self.A); s.open(M)
        s.revert_globals_to_reference()
        # the modded archive differs from vanilla in extras/fert ->
        # reverts queued
        self.assertTrue(len(s.cs.extras) + len(s.cs.fert) > 0)
        s.close()

    def test_p5_global_revert_without_reference_refuses(self):
        M = self.W + "/mod3.rda"; make_synthetic_rda(M, variant=1)
        s, _ = _mk_session("p5c"); s.open(M)
        # no provided vanilla copy -> _queue_global_revert returns
        # silently (nothing to revert TO) — the action is a no-op, not
        # a crash
        s.revert_globals_to_reference()
        self.assertEqual(len(s.cs.extras), 0)
        s.close()

    def test_p5_hardened_from_vanilla_baseline(self):
        # With a provided vanilla copy and a MODDED opened archive
        # Hardened derives from the VANILLA roster, not the modded one
        M = self.W + "/mod4.rda"; make_synthetic_rda(M, variant=1)
        s, _ = _mk_session("p5d"); s.provide_vanilla(self.A); s.open(M)
        s.set_mode(s.proj.by_guid[LEIF], "hardened")
        self.assertNotEqual(s.modes.get(LEIF), "hardened_rel")
        s.close()

    def test_p5_hardened_rel_labelled_without_baseline(self):
        M = self.W + "/mod5.rda"; make_synthetic_rda(M, variant=1)
        s, _ = _mk_session("p5e"); s.open(M)
        s.set_mode(s.proj.by_guid[LEIF], "hardened")
        self.assertEqual(s.modes.get(LEIF), "hardened_rel")
        s.close()

    def test_p5_exact_name_resolution_prefix_case(self):
        # A name that is an exact match (case-insensitive) resolves
        # to itself even when it is a substring of another name
        s, _ = _mk_session("p5f"); s.open(self.A)
        names = list(s.proj.by_name)
        self.assertTrue(names)
        # build a synthetic prefix case: use the exact name of a char
        name = names[0]
        guids = s._resolve_guids(s.proj.by_guid[LEIF], [name])
        self.assertEqual(guids, [s.proj.by_name[name].guid])
        # and a unique prefix still resolves
        prefix = name[:4]
        hits = [n for n in s.proj.by_name if prefix.lower() in n.lower()]
        if len(hits) == 1:
            guids = s._resolve_guids(s.proj.by_guid[LEIF], [prefix])
            self.assertEqual(guids, [s.proj.by_name[hits[0]].guid])
        s.close()

    def test_p5_cli_revert_globals(self):
        M = self.W + "/mod6.rda"; make_synthetic_rda(M, variant=1)
        # Revert-globals now WRITES. The CLI Session
        # uses the env-driven store roots — point ANN0140_HOME at a fresh
        # temp home and provide the vanilla there FIRST, so the CLI sees
        # the SAME reference this test provided.
        from annoedit.appsettings import Settings
        from annoedit.session import Session
        home = tempfile.mkdtemp(prefix="p5cli_")
        old_home = os.environ.get("ANN0140_HOME")
        old_exp = os.environ.get("ANN0140_EXPORTS_DIR")
        os.environ["ANN0140_HOME"] = home
        # the legacy var takes PRECEDENCE over ANN0140_HOME (homevar) —
        # the suite runner exports it, so neutralize it here so the CLI
        # Session sees THIS test's home
        os.environ["ANN0140_EXPORTS_DIR"] = os.path.join(home, "exports")
        self.addCleanup(os.environ.__setitem__, "ANN0140_HOME",
                        old_home or "/tmp/pd_home")
        self.addCleanup(os.environ.__setitem__, "ANN0140_EXPORTS_DIR",
                        old_exp or "")
        s = Session(backup_root=os.path.join(home, "backups"),
                    exports_root=os.path.join(home, "exports"),
                    settings=Settings(os.path.join(home, "settings")))
        s.provide_vanilla(self.A)
        s.close()
        # no OUT and no --flash: refuse via SystemExit (stderr) — the old
        # command silently queued edits in memory, printed 'queued …' and
        # wrote NOTHING
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["revert-globals", M])
        self.assertIn("refusing to queue edits without writing", str(cm.exception.code))
        # --flash writes IN PLACE toward the reference
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            try:
                rc = cli.main(["revert-globals", M, "--flash"])
            except SystemExit:
                rc = 1
        self.assertIn("reverted globals IN PLACE", buf2.getvalue())
        from annoedit.core import ModProject
        self.assertEqual(
            ModProject(M).extras_catalog() == ModProject(self.A).extras_catalog(),
            True, "extras reverted toward the provided vanilla reference")

    def test_p5_anchors_persist_in_named_preset(self):
        # Save a named preset with an anchored insert; reload ->
        # the anchor rides along (dial_map anchors=True shape)
        s, _ = _mk_session("p5g"); s.open(self.A)
        leif = s.proj.by_guid[LEIF]
        # find an insert path: a path NOT in leif.dials
        candidates = [p for p in s.proj.defaults
                      if p not in leif.dials][:1]
        if not candidates:
            self.skipTest("fixture lacks an insertable dial")
        path = candidates[0]
        s._queue_dial(leif, path, "5", "Military/MaxUnitCount")
        # a value WITH an anchor present in dial_map(anchors=True)
        ia = s.cs.dial_map(LEIF, anchors=True)
        self.assertIsInstance(ia.get(path), tuple)
        # named preset save/load carries the anchor
        # (needs a persona-free path: use save/load on temp root)
        p = s.save_named_preset(leif, "p5anchor", "note")
        self.assertTrue(os.path.isfile(p))
        import json
        data = json.load(open(p, encoding="utf-8"))
        spec = data["characters"][leif.name]
        self.assertIn("insert_after", spec)
        self.assertEqual(spec["insert_after"].get(path),
                         "Military/MaxUnitCount")
        s.close()


if __name__ == "__main__":
    unittest.main()
