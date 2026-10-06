#!/usr/bin/env python3
"""Missing archive members and unsupported block flags.

- A missing required member raises ArchiveMemberMissing and the CLI
  labels it correctly.
- A memory-resident (flag 4) block is refused even in non-strict mode;
  a negative directory position raises cleanly.
"""
import io
import os
import contextlib
import shutil
import struct
import tempfile
import unittest

os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

from annoedit import cli                                  # noqa: E402
from annoedit.core import ModProject, ArchiveMemberMissing  # noqa: E402
from annoedit.rda import read_rda, write_rda, RdaFormatError  # noqa: E402
from tests.synthetic_rda import make_synthetic_rda        # noqa: E402


class R11Tests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p6_")
        self.addCleanup(shutil.rmtree, self.W, ignore_errors=True)
        self.A = make_synthetic_rda(self.W + "/vanilla.rda")

    def test_p6_missing_member_exception(self):
        e = read_rda(self.A)
        del e["addondata/config/ai/properties.xml"]
        X = self.W + "/noschema.rda"
        write_rda(e, X)
        with self.assertRaises(ArchiveMemberMissing):
            ModProject(X)

    def test_p6_cli_labels_missing_member_honestly(self):
        e = read_rda(self.A)
        del e["addondata/config/ai/properties.xml"]
        X = self.W + "/noschema.rda"
        write_rda(e, X)
        buf = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = cli.main(["list", X])
        self.assertEqual(rc, 2)
        self.assertNotIn("spec item", err.getvalue())
        self.assertIn("archive member missing", err.getvalue())


class M6Flag4Tests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="p6f_")
        self.addCleanup(shutil.rmtree, self.W, ignore_errors=True)
        self.A = make_synthetic_rda(self.W + "/vanilla.rda")

    def test_p6_flag4_block_raises_even_non_strict(self):
        # A memory-resident block must FAIL CLOSED, even when
        # strict=False (the old code read foff as an ABSOLUTE offset and
        # silently misread). Build a fake archive with a flag-4 dir
        # block by hand.
        # RDA header: magic + pad + first-block offset (1024); the file
        # must exceed the 1048-byte minimum so the header check passes
        magic = "Resource File V2.0".encode("utf-16-le")   # 36 bytes
        hdr = magic + b"\x00" * 1008 + struct.pack("<I", 1048)
        blk = struct.pack("<IIIII", 4, 0, 16, 16, 0)
        blob = hdr + blk + b"\x00" * 4096
        P = self.W + "/flag4.rda"
        with open(P, "wb") as f:
            f.write(blob)
        with self.assertRaises(RdaFormatError) as cm:
            read_rda(P, strict=False)
        self.assertIn("memory-resident", str(cm.exception))

    def test_p6_negative_pos_raises_cleanly(self):
        # A negative directory position must raise RdaFormatError
        # not OSError('negative seek')
        magic = "Resource File V2.0".encode("utf-16-le")   # 36 bytes
        hdr = magic + b"\x00" * 1008 + struct.pack("<I", 1048)
        blk = struct.pack("<IIIII", 0, 1, 10 ** 9, 540, 0)
        P = self.W + "/negpos.rda"
        with open(P, "wb") as f:
            f.write(hdr + blk + b"\x00" * 4096)
        with self.assertRaises(RdaFormatError) as cm:
            read_rda(P, strict=False)
        self.assertIn("negative", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
