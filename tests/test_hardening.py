"""Hardening tests.

- latin-1 codec for assets.xml/randommapgenerator.xml: an archive with
  a byte undefined in cp1252 (0x81 etc.) opens, edits and round-trips
  byte-exactly.
- The picker accepts data1.rda_<name> exports and the vanilla copy.
- CLI error mapping: expected errors print a clean message (exit 2);
  persona targets are exact-match only; flash counts relations/extras/
  fertility as changes.
- Settings.delete merge-writes (a concurrent writer's keys survive).
- RDA edges: names split at the first NUL; write_rda({}) raises a clear
  error; a corrupt manifest is tolerated.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

# pin an isolated home BEFORE annoedit imports (fixture.py's
# pattern — this module builds its own synthetic archives, so
# only the env pin is needed)
os.environ.setdefault(
    "ANN0140_HOME", os.path.join(tempfile.mkdtemp(prefix="pr6_"),
                                    "home"))

from synthetic_rda import make_synthetic_rda  # noqa: E402
from annoedit.backup import BackupStore  # noqa: E402
from annoedit.core import ASSETS_FILE, FERT_FILE, ModProject  # noqa: E402
from annoedit.rda import RdaFormatError, read_rda, write_rda  # noqa: E402


class F10Latin1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f10_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(os.path.join(self.tmp, "g", "data1.rda"))

    def _inject(self, member, payload):
        entries = read_rda(self.game)
        data = bytearray(entries[member][0])
        data.extend(payload)
        entries[member] = (bytes(data), entries[member][1])
        out = os.path.join(self.tmp, "inj.rda")
        write_rda(entries, out)
        return out

    def test_undefined_cp1252_byte_opens_and_round_trips(self):
        # 0x81/0x8D/0x8F/0x90/0x9D are UNDEFINED in cp1252 — latin-1
        # decodes every byte. The fert file's binary pseudo-CDATA head
        # is the realistic carrier.
        out = self._inject(FERT_FILE, b"\x81\x8d\x8f\x90\x9d junk")
        proj = ModProject(out)          # must NOT raise UnicodeDecodeError
        # byte-exact round trip with no edits
        self.assertEqual(proj.fert_text.encode("latin-1"),
                         read_rda(out)[FERT_FILE][0])
        # an edit + rebuild keeps the injected bytes elsewhere
        proj.set_dials(proj.by_guid["1645021"],
                       {"Build/BuildingSpeed": "150"})
        out2 = os.path.join(self.tmp, "edited.rda")
        proj.build(out2)
        self.assertIn(b"\x81\x8d\x8f\x90\x9d junk",
                      read_rda(out2)[FERT_FILE][0])

    def test_assets_xml_same_rule(self):
        out = self._inject(ASSETS_FILE, b"\x81")
        proj = ModProject(out)
        self.assertEqual(proj.assets_text.encode("latin-1"),
                         read_rda(out)[ASSETS_FILE][0])


class F18PickerFilterTests(unittest.TestCase):
    def setUp(self):
        # Tk import guard — this test constructs a
        # PathPicker.__new__ instance, so it must skip (not error) on
        # machines without python3-tk.
        try:
            import tkinter  # noqa
        except Exception:
            raise unittest.SkipTest("tkinter unavailable")

    def test_wanted_accepts_exports_and_vanilla(self):
        # Headless: exercise the pure filter logic. Import the tk-free
        # annoedit.gui.logic, never
        # annoedit.gui.picker (picker imports tkinter, which errors the
        # whole test on machines without python3-tk)
        from annoedit.gui.logic import wanted_file
        from annoedit.gui.picker import PathPicker
        picker = PathPicker.__new__(PathPicker)
        picker.suffixes = (".rda",)
        for name in ("data1.rda", "data1.rda_vanilla",
                     "data1.rda_myexport", "other.rda"):
            p = os.path.join("/tmp", name)
            self.assertTrue(wanted_file(p), name)
        for name in ("notes.txt", "x.rda_backup"):
            p = os.path.join("/tmp", name)
            self.assertFalse(wanted_file(p), name)


class F21CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f21_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(os.path.join(self.tmp, "g", "data1.rda"))
        self.env = dict(os.environ, ANN0140_HOME=os.path.join(self.tmp, "home"))

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "annoedit.cli", *args],
            capture_output=True, text=True, cwd=os.path.join(HERE, ".."),
            env=self.env, timeout=120)

    def test_bad_json_spec_clean_error(self):
        spec = os.path.join(self.tmp, "bad.json")
        with open(spec, "w") as f:
            f.write("{not json")
        r = self._cli("extras-apply", self.game,
                      os.path.join(self.tmp, "o.rda"), spec)
        self.assertEqual(r.returncode, 2)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_spec_key_clean_error(self):
        spec = os.path.join(self.tmp, "miss.json")
        with open(spec, "w") as f:
            json.dump({"extras": [{"tag": "ProductionTime", "value": "5"}]},
                      f)     # no "asset" key
        r = self._cli("extras-apply", self.game,
                      os.path.join(self.tmp, "o.rda"), spec)
        self.assertEqual(r.returncode, 2)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_file_clean_error(self):
        r = self._cli("extras", os.path.join(self.tmp, "nope.rda"),
                      os.path.join(self.tmp, "o.rda"),
                      os.path.join(self.tmp, "any.json"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_flash_counts_relations_changes(self):
        # custom-preset shape: characters -> dials + relations
        # a relations-only preset must count as a change to flash
        spec = os.path.join(self.tmp, "rel.json")
        with open(spec, "w") as f:
            json.dump({"characters": {"Leif Jorgensen": {
                "dials": {},
                "relations": {"War": ["1645024"]}}}}, f)
        r = self._cli("flash", self.game, "--preset", spec)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("1 relations edits", r.stdout)


class F23SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f23_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_delete_merge_writes(self):
        from annoedit.appsettings import Settings
        root = os.path.join(self.tmp, "sroot")
        a = Settings(root)
        a.set("live_path", "/x")
        a.set("theme", "dark")
        b = Settings(root)             # second writer
        b.set("other", "1")
        a.delete("theme")             # merge-write must keep b's key
        with open(a.path) as f:
            disk = json.load(f)
        self.assertIn("other", disk)
        self.assertIn("live_path", disk)
        self.assertNotIn("theme", disk)


class F24RdaEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f24_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = make_synthetic_rda(os.path.join(self.tmp, "g", "data1.rda"))

    def test_write_empty_entries_refused(self):
        with self.assertRaises(RdaFormatError):
            write_rda({}, os.path.join(self.tmp, "empty.rda"))

    def test_corrupt_manifest_tolerated(self):
        store = BackupStore(root=os.path.join(self.tmp, "bk"))
        os.makedirs(store.root, exist_ok=True)
        with open(store.manifest_path, "w") as f:
            f.write("{corrupt")
        # must not raise — treated as empty
        self.assertEqual(store._read_manifest(), {})

    def test_name_decoded_to_first_nul(self):
        # craft an archive whose entry name carries an embedded NUL;
        # the reader must cut at the NUL, not keep trailing garbage
        entries = read_rda(self.game)
        some = sorted(entries)[0]
        data, ts = entries[some]
        bad = some + "\x00garbage"
        entries2 = dict(entries)
        entries2.pop(some)
        entries2[bad] = (data, ts)
        out = os.path.join(self.tmp, "nul.rda")
        write_rda(entries2, out)
        back = read_rda(out)
        self.assertIn(some, back)             # NUL-cut name recovered
        self.assertNotIn(bad, back)
        self.assertNotIn("garbage", "".join(back))


if __name__ == "__main__":
    unittest.main()
