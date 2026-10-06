#!/usr/bin/env python3
"""Reader tolerance for real-world archive shapes.

Other packers and mod managers store members inside a compressed block
differently than our writer does:
  * an empty member (an empty .ini marker) as 0 raw bytes;
  * a non-empty member stored RAW (not zlib) with fcomp == funsize.

"Not zlib" is not the same as "corrupt": the size invariant
(len(data) == funsize) is the real corruption signal, so those two shapes
are accepted (warn only) even in strict mode, while a truncated zlib
stream with a size mismatch stays a hard refusal in strict mode.
"""
import os
import struct
import sys
import tempfile
import unittest
import warnings
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from annoedit.rda import (                               # noqa: E402
    MAGIC_V20, HDR_PAD, FILENAME_SIZE,
    RdaFormatError, read_rda, write_rda)


def craft_rda(path, members):
    """Hand-build a single-block RDA V2.0 archive.

    members: list of (name, stored_bytes, fcomp, funsize). The block is
    COMPRESSED (flags=1, dir zlib-compressed) exactly like the shape the
    field report hit — per-file compression follows the block flag, so
    every member here goes through the decompress path with whatever
    bytes we actually stored.
    """
    out = bytearray(b"\x00" * (len(MAGIC_V20) + HDR_PAD + 4))
    dirents = []
    for name, stored, fcomp, funsize in members:
        off = len(out)
        out += stored
        dirents.append((name, off, fcomp, funsize))
    dirbuf = bytearray()
    for name, off, fcomp, funsize in dirents:
        nb = name.encode("utf-16-le")
        dirbuf += nb + b"\x00" * (FILENAME_SIZE - len(nb))
        dirbuf += struct.pack("<5I", off, fcomp, funsize, 0, 0)
    cdir = zlib.compress(bytes(dirbuf))
    out += cdir
    block_off = len(out)                      # header FOLLOWS the directory
    out += struct.pack("<5I", 1, len(dirents), len(cdir),
                       len(dirbuf), 0)          # BlockInfo; next=0 ends chain
    out[:len(MAGIC_V20) + HDR_PAD + 4] = (
        MAGIC_V20 + b"\x00" * HDR_PAD + struct.pack("<I", block_off))
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


class RawMemberInCompressedBlockTests(unittest.TestCase):
    def setUp(self):
        self.W = tempfile.mkdtemp(prefix="f35_")
        self.addCleanup(lambda: __import__("shutil").rmtree(
            self.W, ignore_errors=True))

    def test_empty_member_raw_in_compressed_block_strict_ok(self):
        """0-byte .ini marker inside a compressed block: strict open
        succeeds and returns b'' (the field-report archive opens again)."""
        p = craft_rda(self.W + "/empty_marker.rda", [
            ("addondata/config/gui/disabled_addon01.ini", b"", 0, 0),
            ("addondata/config/other.txt", zlib.compress(b"hello"), 13, 5),
        ])
        entries = read_rda(p, strict=True)
        self.assertEqual(entries["addondata/config/gui/disabled_addon01.ini"][0],
                         b"")

    def test_raw_stored_member_size_match_accepted_strict(self):
        """Non-empty member stored raw (not zlib) with fcomp == funsize:
        accepted with a warning, never a strict refusal."""
        p = craft_rda(self.W + "/raw_member.rda", [
            ("addondata/config/gui/disabled_addon01.ini", b"0", 1, 1),
        ])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            entries = read_rda(p, strict=True)
        self.assertEqual(entries["addondata/config/gui/disabled_addon01.ini"][0],
                         b"0")
        self.assertTrue(any("compressed block" in str(x.message) for x in w))

    def test_truncated_zlib_size_mismatch_still_refused(self):
        """A genuinely corrupt member (truncated zlib stream, size does
        NOT match the declared funsize) stays a hard strict refusal."""
        trunc = zlib.compress(b"x" * 50)[:4]          # not decompressable
        p = craft_rda(self.W + "/truncated.rda", [
            ("addondata/config/gui/broken.ini", trunc, 4, 50),
        ])
        with self.assertRaises(RdaFormatError):
            read_rda(p, strict=True)

    def test_truncated_zlib_lenient_keeps_raw_and_warns(self):
        """Lenient mode keeps the raw bytes and warns (never silent)."""
        trunc = zlib.compress(b"x" * 50)[:4]
        p = craft_rda(self.W + "/truncated_lenient.rda", [
            ("addondata/config/gui/broken.ini", trunc, 4, 50),
        ])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            entries = read_rda(p, strict=False)
        self.assertEqual(entries["addondata/config/gui/broken.ini"][0], trunc)
        self.assertTrue(any("keeping raw stored bytes" in str(x.message)
                            for x in w))

    def test_rewrite_re_stores_zlib_and_round_trips(self):
        """After opening a field-report archive, a save re-stores the
        empty member zlib-compressed — data-identical, and the archive
        round-trips through our own writer cleanly."""
        p = craft_rda(self.W + "/orig.rda", [
            ("addondata/config/gui/disabled_addon01.ini", b"", 0, 0),
        ])
        entries = read_rda(p, strict=True)
        out = self.W + "/rewritten.rda"
        write_rda(entries, out)
        again = read_rda(out, strict=True)
        self.assertEqual(again["addondata/config/gui/disabled_addon01.ini"][0],
                         b"")


if __name__ == "__main__":
    unittest.main()
