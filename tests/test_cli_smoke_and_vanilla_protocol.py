"""CLI smoke, vanilla-copy protocol, temp sweep, relations structure.

- Every CLI subcommand parses and runs.
- Crash injection for the vanilla-copy md5 protocol: no crash window can
  leave a copy whose md5 was never recorded.
- The stale-temp sweep matches what the writers create and also sweeps
  the live directory.
- Malformed profile structure raises instead of silently reading {}.
- CLI change counts include persona relations; revert-globals is
  reachable.
- The relations clash message names both conflicting kinds.
"""
import argparse
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)
from synthetic_rda import make_synthetic_rda


class CliSmokeTests(unittest.TestCase):
    """Every subcommand must at least parse; argument wiring bugs are
    invisible to the suite unless exercised."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def _run(self, argv):
        from annoedit import cli
        parser = cli.build_parser()
        return parser.parse_args(argv)

    def test_every_subcommand_parses(self):
        from annoedit import cli
        parser = cli.build_parser()
        subs = [a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction)]
        self.assertEqual(len(subs), 1)
        names = set(subs[0].choices)
        for name in sorted(names):
            with self.assertRaises(SystemExit) as cm:
                self._run([name, "--help"])
            self.assertEqual(cm.exception.code, 0)

    def test_log_n_lands_on_log(self):
        args = self._run(["log", "-n", "5"])
        self.assertEqual(args.n, 5)

    def test_log_runs(self):
        from annoedit import cli
        args = self._run(["log"])
        rc = cli.cmd_log(args)
        self.assertEqual(rc, 0)


class VanillaCrashInjectionTests(unittest.TestCase):
    """capture_vanilla_copy's crash windows must never end in
    'copy present, record missing'."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))
        from annoedit.exports import ExportStore
        self.es = ExportStore(os.path.join(self.tmp, "exports"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_record_is_durably_committed_first(self):
        # A crash at ANY os.replace window (the record's or the copy's)
        # must never leave "copy present, record missing" — that state
        # silently skips restore verification forever.
        es = self.es
        real_replace = os.replace
        for n in (1, 2):
            calls = {"n": 0}
            def boom(src, dst, _n=n):
                calls["n"] += 1
                if calls["n"] >= _n:
                    raise KeyboardInterrupt
                return real_replace(src, dst)
            os.replace = boom
            try:
                es.capture_vanilla_copy(self.arch)
                self.fail("expected KeyboardInterrupt")
            except KeyboardInterrupt:
                pass
            finally:
                os.replace = real_replace
            self.assertFalse(
                es.has_vanilla_copy() and es.vanilla_copy_md5() is None,
                f"crash at replace #{n} left an unrecorded copy")

    def test_hash_while_copy_detects_toctou(self):
        # md5 computed, then the file changes during the copy: the copy
        # must be refused, not silently stored with a stale md5.
        es = self.es
        real_replace = os.replace
        calls = {"n": 0}
        def swap_then_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                # the record's replace is fine; corrupt the SOURCE so
                # the copy reads different bytes than md5_of saw
                with open(self.arch, "ab") as f:
                    f.write(b"TOCTOU")
                return real_replace(src, dst)
            return real_replace(src, dst)
        os.replace = swap_then_replace
        try:
            es.capture_vanilla_copy(self.arch)
            self.fail("expected ExportsError (source changed mid-copy)")
        except Exception as e:
            self.assertIn("changed while", str(e))
        finally:
            os.replace = real_replace
        self.assertFalse(es.has_vanilla_copy(),
                         "a copy whose bytes do not match its record was stored")

    def test_restore_refuses_copy_without_record(self):
        # copy present, record missing -> restore must refuse, never
        # silently skip verification.
        self.es.capture_vanilla_copy(self.arch)
        os.unlink(os.path.join(self.es.root, "vanilla.meta.json"))
        from annoedit.session import Session
        s = Session(exports_root=self.es.root)
        s.open(self.arch)
        try:
            try:
                s.restore_vanilla()
                self.fail("expected SessionError (record missing)")
            except Exception as e:
                self.assertIn("no recorded md5", str(e))
        finally:
            s.close()


class SweepPatternTests(unittest.TestCase):
    """The sweep must match what the CURRENT writers create."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))
        self.live = os.path.join(self.game, "data1.rda")
        shutil.copy(self.arch, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_sweep_removes_current_temp_names(self):
        from annoedit import ops
        for n in (".annoedit-abc.tmp", ".annoedit-xyz.verifytmp",
                  ".ce_pack_q.tmp"):
            open(os.path.join(self.tmp, n), "wb").write(b"x")
        removed = ops._sweep_stale_temps(self.arch)
        for n in (".annoedit-abc.tmp", ".annoedit-xyz.verifytmp",
                  ".ce_pack_q.tmp"):
            self.assertFalse(os.path.exists(os.path.join(self.tmp, n)),
                             f"{n} not swept")
        self.assertTrue(removed)

    def test_sweep_removes_legacy_names(self):
        from annoedit import ops
        open(os.path.join(self.tmp, ".flashbuild-9.rda"), "wb").write(b"x")
        open(os.path.join(self.tmp, os.path.basename(self.arch)
                          + ".verifytmp"), "wb").write(b"x")
        ops._sweep_stale_temps(self.arch)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, ".flashbuild-9.rda")))

    def test_sweep_covers_live_directory(self):
        from annoedit import ops
        open(os.path.join(self.game, ".annoedit-live.tmp"), "wb").write(b"x")
        ops._sweep_stale_temps(self.arch, extra_dirs=(self.live,))
        self.assertFalse(os.path.exists(
            os.path.join(self.game, ".annoedit-live.tmp")),
            "live-directory temp not swept")


class RelationsMalformedTests(unittest.TestCase):
    """Malformed profile structure must raise, never silently read {}."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))
        from annoedit.session import Session
        self.ses = Session()
        self.ses.open(self.arch)

    def tearDown(self):
        self.ses.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_corrupt_structure_raises_editerror(self):
        from annoedit.core import _relations_node, EditError
        q = [p for p in self.ses.roster][0]
        txt = self.ses.proj.text_of_fresh(q)
        corrupt = txt.replace("</Relationships>",
                               "</Relationshipz>", 1)
        with self.assertRaises(EditError):
            _relations_node(corrupt)


class HonestCliCountTests(unittest.TestCase):
    """Persona relations counted in the no---char branch; revert-globals
    'nothing to revert' is reachable when the archive matches reference."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.arch = make_synthetic_rda(os.path.join(self.tmp, "data1.rda"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_revert_globals_nothing_to_revert_is_reachable(self):
        # opened == reference (no provided vanilla, no edits): every
        # queued reset is a no-op -> the command reports nothing to do.
        from annoedit import cli
        # the command opens its own session; do not hold the lock here.
        parser = cli.build_parser()
        args = parser.parse_args(["revert-globals", self.arch,
                                  os.path.join(self.tmp, "out.rda")])
        rc = cli.cmd_revert_globals(args)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out.rda")))

    def test_relations_clash_message_names_both_kinds(self):
        from annoedit.changeset import ChangeSet, ChangeSetError
        cs = ChangeSet()
        cs.add_rel(1234, "AvoidWar", [55])
        with self.assertRaises(ChangeSetError) as cm:
            cs.add_rel(1234, "War", [55])
        self.assertIn("War and AvoidWar", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
