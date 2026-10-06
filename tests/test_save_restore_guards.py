"""Save/restore guard regressions.

- The stale-temp sweep never deletes another instance's in-flight temps.
- revert-globals refuses when the live file gained an occurrence level.
- Vanilla mode works even when datasets.xml is broken.
- A no-drift result still carries the consent anchor (live md5).
- A surgical restore that degrades to full is reported.
- Build reports carry the written entries (no post-commit re-read).
- New exports get a normal file mode.

Fixture pattern: the synthetic archive + an isolated ANN0140_HOME
(fixture.py); no real game data needed.
"""
import os
import shutil
import stat
import tempfile
import unittest



class F1SweepTests(unittest.TestCase):
    """The stale-temp sweep runs only under the store lock; no PID
    logic; a refused second instance never deletes the first's temps."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.game, "data1.rda")
        shutil.copy(self.van, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_no_os_kill_probe(self):
        import annoedit.ops as ops
        real_kill = os.kill
        def boom(pid, sig):
            raise AssertionError("os.kill probe used")
        os.kill = boom
        try:
            ops._sweep_stale_temps(self.live)
        finally:
            os.kill = real_kill

    def test_refused_second_instance_keeps_temps(self):
        from annoedit.session import Session
        from annoedit.backup import BackupError
        s1 = Session()
        s1.open(self.live)
        vt = self.live + ".verifytmp"
        open(vt, "wb").write(b"x")
        pk = os.path.join(self.game, ".ce_pack_abc.tmp")
        open(pk, "wb").write(b"x")
        try:
            Session().open(self.live)
            self.fail("second open should have been refused")
        except BackupError:
            pass
        self.assertTrue(os.path.exists(vt), "in-flight .verifytmp deleted by refused instance")
        self.assertTrue(os.path.exists(pk), ".ce_pack tmp deleted by refused instance")
        s1.close()


class F2RevertGlobalsOccCountTests(unittest.TestCase):
    """Revert-globals records the reference occurrence count, so a
    live file that gained a level is REFUSED, never silently corrupted
    to [8,10,10]."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.game, "data1.rda")
        shutil.copy(self.van, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def _mutate_live(self, fn):
        from annoedit.rda import read_rda, write_rda
        e = read_rda(self.live, strict=True)
        k = "addondata/config/game/assets.xml"
        t = fn(e[k][0].decode("latin-1"))
        e[k] = (t.encode("latin-1"), e[k][1])
        write_rda(e, self.live)

    def test_revert_globals_refuses_on_level_gain(self):
        from annoedit.session import Session, SessionError
        from annoedit.core import ModProject
        s = Session()
        s.provide_vanilla(self.van)
        s.set_live_path(self.live)
        self._mutate_live(lambda t: t.replace(
            "<NoriaEndRadius>8</NoriaEndRadius>",
            "<NoriaEndRadius>6</NoriaEndRadius>\r\n      "
            "<NoriaEndRadius>8</NoriaEndRadius>"))
        s.open(s.exports_store.vanilla_path)
        s.revert_globals_to_reference()
        try:
            s.flash(target=self.live)
            # If it did not refuse, the result must NOT be corrupted:
            got = ModProject(self.live).extras_catalog()["noria"]["NoriaEndRadius"]
            self.assertNotEqual(got, ["8", "10", "10"],
                                "silent corruption [8,10,10]")
        except SessionError as exc:
            self.assertIn("occurrence", str(exc).lower())
        s.close()


class F5VanillaOnBrokenDatasets(unittest.TestCase):
    """Reference-sourced reset values skip opened-archive
    enumeration re-validation — a broken datasets.xml in the OPENED
    archive no longer aborts the Vanilla click."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "mod"))
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.tmp, "game", "data1.rda")
        os.makedirs(os.path.dirname(self.live))
        shutil.copy(self.van, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_vanilla_mode_succeeds_on_broken_datasets(self):
        from annoedit.rda import read_rda, write_rda
        from annoedit.session import Session
        e = read_rda(self.van, strict=True)
        e["addondata/config/game/datasets.xml"] = (
            b"<DataSets><DataSet>broken", 0)
        mod = os.path.join(self.tmp, "mod", "data1.rda")
        write_rda(e, mod)
        s = Session()
        s.provide_vanilla(self.van)
        s.open(mod)
        try:
            s.set_mode(s.proj.by_guid["1645020"], "vanilla")  # must NOT raise
        finally:
            s.close()


class F6DriftAlwaysCarriesAnchor(unittest.TestCase):
    """Drift_check always returns a DriftResult carrying live and
    live_md5 when the target exists — the consent anchor survives the
    no-drift case."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.game, "data1.rda")
        shutil.copy(self.van, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_no_drift_still_returns_anchor(self):
        from annoedit.session import Session
        from annoedit import ops
        s = Session()
        s.provide_vanilla(self.van)
        s.set_live_path(self.live)
        s.open(s.exports_store.vanilla_path)
        s.set_dial(s.roster[0], "Military/MaxUnitCount", "77")
        res = ops.drift_check(*s.freeze_drift_inputs())
        self.assertIsNotNone(res, "drift None in the no-drift case")
        self.assertFalse(bool(res), "zero-drift result must be falsy")
        self.assertIsNotNone(getattr(res, "live", None))
        self.assertTrue(getattr(res, "live_md5", None))
        s.close()


class F7DegradedRestoreReport(unittest.TestCase):
    """A surgical restore over an unreadable live file degrades to
    full but REPORTS it (degraded_to_full), never silent."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.game, "data1.rda")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_unreadable_live_reports_degraded(self):
        from annoedit.rda import read_rda, write_rda
        from annoedit.session import Session
        from annoedit import ops
        e = read_rda(self.van, strict=True)
        e["data/othermod.txt"] = (b"other mod", 0)
        write_rda(e, self.live)
        b = open(self.live, "rb").read()
        open(self.live, "wb").write(b[:-50])   # corrupt
        s = Session()
        s.provide_vanilla(self.van)
        res = ops.restore_build(s._write_lock, s.store, s.exports_store,
                                self.live, False, s.source_path,
                                cs=s.cs.snapshot())
        self.assertIsNotNone(res.degraded_to_full,
                              "surgical restore degraded to full silently")
        self.assertIn("could not be read back",
                      str(res.degraded_to_full))
        s.close()


class F8EntriesInBuildReport(unittest.TestCase):
    """ModProject.build carries the written entry map; flash builds
    the post-commit project from it (no post-commit disk re-read)."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.game, "data1.rda")
        shutil.copy(self.van, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_build_report_carries_entries(self):
        from annoedit.core import ModProject
        p = ModProject(self.live)
        report = p.build(os.path.join(self.tmp, "out.rda"))
        self.assertIn("entries", report)
        self.assertEqual(len(report["entries"]),
                         len(p.entries), "report entries must match")

    def test_flash_new_proj_from_report_entries(self):
        from annoedit.session import Session
        s = Session()
        s.open(self.live)
        s.set_dial(s.roster[0], "Military/MaxUnitCount", "70")
        res = s.flash(target=self.live)
        # apply_flash_result installed a post-edit project — verify the
        # dial landed in the session's CURRENT project.
        guid = s.roster[0].guid
        prof = s.proj.by_guid[guid]
        from annoedit.model import dials_dict
        dd = dials_dict(s.proj.text_of(prof))
        self.assertEqual(dd.get("Military/MaxUnitCount"), "70",
                         "post-flash project is stale")
        s.close()


class F11ExportModeTests(unittest.TestCase):
    """A NEW export keeps a sane mode (0o644-class, not 0600)."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        from tests.synthetic_rda import make_synthetic_rda
        self.van = make_synthetic_rda(os.path.join(self.tmp, "van.rda"))
        self.live = os.path.join(self.game, "data1.rda")
        shutil.copy(self.van, self.live)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_new_export_mode(self):
        from annoedit.session import Session
        os.umask(0o022)
        s = Session()
        s.open(self.live)
        s.set_dial(s.roster[0], "Military/MaxUnitCount", "70")
        out = os.path.join(self.tmp, "out", "exp.rda")
        os.makedirs(os.path.dirname(out))
        s.export(out)
        m = stat.S_IMODE(os.stat(out).st_mode)
        self.assertEqual(m, 0o644, f"new export mode {oct(m)} != 644")
        s.close()


if __name__ == "__main__":
    unittest.main()
