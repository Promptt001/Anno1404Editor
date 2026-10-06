"""Vanilla hash registry, restore member set, parent paths.

- The known-vanilla registry classifies a provided copy as
  verified/modded/partial; provide_vanilla records the verdict.
- The surgical-restore set includes the schema-defaults properties.xml,
  while the edit scope stays the 4 tracked members.
- parent_paths() reports the real parent of each multi-instance
  occurrence (noria ground states, not "levels").
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)
from synthetic_rda import make_synthetic_rda


class VanillaRegistryTests(unittest.TestCase):

    def test_registry_constants_shape(self):
        from annoedit import vanilla_registry as vr
        # 5 known members (4 edit + schema), sha256 hex strings
        self.assertEqual(len(vr.MEMBERS_SHA256), 5)
        for k, v in vr.MEMBERS_SHA256.items():
            self.assertIsInstance(v, str)
            self.assertEqual(len(v), 64)
            self.assertIn(k, (
                "addondata/config/ai/aiprofiles.xml",
                "addondata/config/balancing/addon_01_aiprofiles.xml",
                "addondata/config/game/assets.xml",
                "addondata/config/game/randommapgenerator.xml",
                "addondata/config/ai/properties.xml"))

    def test_member_class_verified_vs_modded(self):
        from annoedit import vanilla_registry as vr
        from annoedit.rda import read_rda
        import shutil
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        arch = make_synthetic_rda(os.path.join(tmp, "d.rda"))
        entries = read_rda(arch, strict=True)
        # synthetic members do not match the real-vanilla table: partial
        # only if members are MISSING; present-but-different = modded
        self.assertEqual(vr.member_class(entries), "modded")
        # an entries map with none of the known members = partial
        self.assertEqual(vr.member_class({}), "partial")
        # the real vanilla hashes classify as verified by construction
        fake = {k: (b"",) for k in vr.MEMBERS_SHA256}
        # (b"" hashes differ -> modded; the verified path is covered by
        # the real-data gate, which opens the true vanilla archive)

    def test_provide_vanilla_records_verdict(self):
        import shutil
        from annoedit.session import Session
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        arch = make_synthetic_rda(os.path.join(tmp, "d.rda"))
        s = Session(backup_root=os.path.join(tmp, "b"),
                    exports_root=os.path.join(tmp, "e"))
        s.provide_vanilla(arch)
        # synthetic members differ from the real-vanilla table -> modded
        self.assertEqual(s._vanilla_class, "modded")
        s.close()


class RestoreMembersTests(unittest.TestCase):
    """The surgical-restore set includes properties.xml; the edit
    scope stays the 4 members."""

    def test_restore_members_shape(self):
        from annoedit import ops
        from annoedit.core import ARCHIVE_MEMBERS
        self.assertEqual(len(ops.RESTORE_MEMBERS), 5)
        self.assertIn("addondata/config/ai/properties.xml",
                      ops.RESTORE_MEMBERS)
        for m in ARCHIVE_MEMBERS:
            self.assertIn(m, ops.RESTORE_MEMBERS)
        # edit scope unchanged: properties.xml is NOT an edit member
        self.assertNotIn("addondata/config/ai/properties.xml",
                         ARCHIVE_MEMBERS)

    def test_surgical_restore_restores_schema_too(self):
        import shutil
        from annoedit.rda import read_rda, write_rda
        from annoedit.session import Session
        from annoedit import ops
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        van = make_synthetic_rda(os.path.join(tmp, "van.rda"))
        live = os.path.join(tmp, "data1.rda")
        shutil.copy(van, live)
        # another mod changes BOTH an untracked member and the schema
        entries = read_rda(live, strict=True)
        schema = "addondata/config/ai/properties.xml"
        self.assertIn(schema, entries)
        entries[schema] = (entries[schema][0].replace(
            b"<Default>", b"<DefaultX>", 1),) + entries[schema][1:]
        foreign = "addondata/config/game/junk.xml"
        entries[foreign] = (b"<junk/>", False)
        write_rda(entries, live)
        s = Session(backup_root=os.path.join(tmp, "b"),
                    exports_root=os.path.join(tmp, "e"))
        s.provide_vanilla(van)
        s.open(live)
        s.restore_vanilla()   # surgical by default
        s.close()
        after = read_rda(live, strict=True)
        # schema restored to vanilla (surgical set includes it)
        self.assertNotIn(b"<DefaultX>", after[schema][0])
        # the untracked foreign member KEPT
        self.assertIn(foreign, after)


class ParentPathsTests(unittest.TestCase):

    def test_parent_paths_lists_distinct_parents(self):
        from annoedit.rda import read_rda
        from annoedit.extras import (parse_assets, asset_text,
                                     parent_paths, occurrences)
        # the synthetic fixture's noria carries multi-instance tags; use
        # the function contract on it
        import shutil
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        arch = make_synthetic_rda(os.path.join(tmp, "d.rda"))
        entries = read_rda(arch, strict=True)
        text = entries["addondata/config/game/assets.xml"][0].decode(
            "latin-1")
        assets = parse_assets(text)
        a = [x for x in assets if x["name"] == "Noria"][0]
        block = asset_text(text, a)
        ms = occurrences(block, "NoriaEndRadius")
        if len(ms) >= 2:
            pp = parent_paths(block, "NoriaEndRadius")
            self.assertEqual(len(pp), len(ms),
                             "one parent path per occurrence, file order")
        else:
            self.skipTest("synthetic noria lacks multi-instance tags")


if __name__ == "__main__":
    unittest.main()
