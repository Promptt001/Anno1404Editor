#!/usr/bin/env python3
"""rda — in-memory RDA V2.0 reader/writer for Anno 1404 History Edition.

Format summary (full write-up in docs/technical/rda-format.md):
- 1048-byte header: UTF-16 magic "Resource File V2.0", padding, and the
  offset of the first block.
- Each block is a directory of 540-byte entries (520-byte UTF-16 name +
  5x u32: offset, compressed size, size, timestamp, reserved) followed by
  a 20-byte BlockInfo (flags, count, dir size, decompressed size, next).
  The BlockInfo sits AFTER the directory it describes.
- Block flags: 1 = zlib, 2 = encrypted (LCG keystream, seed 0xA2C2A,
  XOR per 16-bit word), 4 = memory-resident, 8 = deleted.
- The writer stores .xml/.txt/.cfg/.ini zlib-compressed and everything
  else raw, one block per extension.
- Entry names use FORWARD slashes; backslashes crash the game.

Reading is defensive: every struct read is length-checked, cyclic or
out-of-bounds block chains raise RdaFormatError, and strict=True turns
any recoverable anomaly into a hard error (the editor always reads
data1.rda strictly so a save can never silently drop members).

Writing is atomic: pack to a temp file beside the target, fsync, keep
the target's file mode, then os.replace() it into place.
"""
import array
import io
import os
import struct
import tempfile
import warnings
import zlib


def _read_exact(f, n, what, path):
    """Read exactly n bytes or raise RdaFormatError (never a bare struct.error)."""
    b = f.read(n)
    if len(b) != n:
        raise RdaFormatError(
            f"{path}: truncated archive ({what}: wanted {n} bytes, "
            f"got {len(b)})")
    return b


def _unpack(f, fmt, what, path):
    """struct.unpack on a length-checked read."""
    return struct.unpack(fmt, _read_exact(f, struct.calcsize(fmt), what, path))


def _warn(msg):
    """Emit a block warning via the warnings module (a GUI has no stdout)."""
    warnings.warn(msg, RuntimeWarning, stacklevel=2)

MAGIC_V20 = "Resource File V2.0".encode("utf-16-le")
HDR_PAD = 1008
FILENAME_SIZE = 520
COMPRESSED_EXTENSIONS = {".xml", ".txt", ".cfg", ".ini"}
SEED = 0xA2C2A


class RdaFormatError(Exception):
    """Not a valid RDA V2.0 archive, or (strict mode) a corrupt block inside."""


def _keystream(n, seed):
    """n XOR words of the RDA LCG keystream ((num>>16)&0x7FFF per word).

    The seed is constant (0xA2C2A) for every block in every archive, so
    the stream is cached per (seed, n) — a cached stream of the same or
    larger length is sliced, so a big one covers every smaller call.
    """
    cache = _KEYSTREAM_CACHE.get(seed)
    if cache is None or len(cache) < n:
        num = seed
        out = array.array("H", bytes(2 * n))
        for i in range(n):
            num = (num * 214013 + 2531011) & 0xFFFFFFFF
            out[i] = (num >> 16) & 0x7FFF
        _KEYSTREAM_CACHE[seed] = out
        cache = out
    return cache[:n] if len(cache) > n else cache


_KEYSTREAM_CACHE = {}


def release_keystream_cache():
    """Drop the cached keystream (a long-lived GUI process otherwise
    holds an entry as large as the biggest encrypted block it has read
    - the full real archive's file data is ~38 MB). The next read
    regenerates it once (~2 s). Call after big read bursts (post-build)
    to hand the memory back between user actions."""
    _KEYSTREAM_CACHE.clear()


def _decrypt(buf, seed):
    """RDA block decryption (same algorithm as RDAExplorer's
    BinaryExtension.Decrypt): LCG num = num*214013+2531011, XOR each
    16-bit word with (num>>16)&0x7FFF.

    The XOR runs as one big-integer operation against a cached
    keystream, which is far faster than a per-word Python loop.
    """
    if seed == 0:
        raise ValueError("invalid decryption seed")
    n = len(buf) // 2
    body = buf[:n * 2]
    ks = _keystream(n, seed).tobytes()
    # big-int XOR: C-speed over the whole block (no per-word Python loop)
    res = (int.from_bytes(body, "little")
           ^ int.from_bytes(ks, "little")).to_bytes(n * 2, "little")
    if len(buf) % 2:
        res += buf[-1:]
    return res


def _read_rda_stream(f, fsize, path, strict=False):
    """The stream core of read_rda: works on any binary
    stream (file object or BytesIO). See read_rda for semantics."""
    warns = []
    # fsize comes from the caller (on-disk size, or len(blob) for an
    # in-memory read) so the bytes are validated against the same
    # snapshot that is being parsed.
    if fsize < len(MAGIC_V20) + HDR_PAD + 4:
        raise RdaFormatError(
            f"{path}: too small to be an RDA archive ({fsize} bytes)")
    magic = f.read(len(MAGIC_V20))
    if magic != MAGIC_V20:
        raise RdaFormatError(
            f"{path}: not an Anno 1404 RDA V2.0 file (bad magic) — "
            "is this really an addon/data1.rda?")
    f.seek(len(MAGIC_V20) + HDR_PAD)
    first_block = _unpack(f, "<I", "first block offset", path)[0]
    if first_block == 0 or first_block >= fsize:
        raise RdaFormatError(
            f"{path}: no directory blocks (first block offset "
            f"{first_block} vs file size {fsize}) — truncated or corrupt file")

    files = []
    names_seen = {}          # name -> block offset, to detect duplicates
    block_offset = first_block
    visited = set()          # a cyclic chain must not hang the reader
    last_end = 1048          # end of the previous block's directory
    while block_offset < fsize and block_offset != 0:
        if block_offset in visited:
            raise RdaFormatError(
                f"{path}: cyclic block chain at offset {block_offset}")
        visited.add(block_offset)
        f.seek(block_offset)
        flags, file_count = _unpack(f, "<II", f"block header @{block_offset}", path)
        directory_size, decompressed_size, next_block = _unpack(
            f, "<III", f"block sizes @{block_offset}", path)
        if next_block not in (0, fsize) and next_block > fsize:
            # A next pointer past EOF would end the loop early and
            # silently drop every later block. Refuse in both modes:
            # this is corruption, not something to be lenient about.
            raise RdaFormatError(
                f"{path}: block @{block_offset} next pointer {next_block} "
                f"is past the end of the file (size {fsize}) — truncated "
                "or corrupt block chain")
        if flags & 8:  # deleted block
            block_offset = next_block
            continue
        pos = block_offset - directory_size
        if flags & 4:  # memoryresident
            # Memory-resident blocks store one compressed buffer with
            # per-file RELATIVE offsets. Anno 1404's data1.rda has none,
            # so fail closed rather than guess, even when strict=False.
            raise RdaFormatError(
                f"{path}: memory-resident block @{block_offset} "
                "is unsupported — the reader refuses to guess "
                "relative file offsets")
        # Bound-check every region before reading it: the directory must
        # start at/after the header and must not overlap the previous
        # block's directory.
        if pos < 1048 or pos < last_end:
            raise RdaFormatError(
                f"{path}: block @{block_offset} directory region "
                f"[{pos}, {pos + directory_size}) is invalid — the "
                f"directory position is negative or overlaps the "
                f"previous block region (last_end={last_end}, header "
                f"end 1048, file size {fsize}) — corrupt or truncated "
                f"block chain")
        last_end = pos + directory_size
        f.seek(pos)
        buf = _read_exact(f, directory_size,
                          f"dir block @{block_offset} directory region", path)
        if flags & 2:
            buf = _decrypt(buf, SEED)
        if flags & 1:
            try:
                buf = zlib.decompress(buf)
            except zlib.error as e:
                w = f"dir block @{block_offset}: {e} — skipping block"
                if strict:
                    raise RdaFormatError(f"{path}: {w}")
                warns.append(w)
                _warn(w)
                block_offset = next_block
                continue
        if file_count * (FILENAME_SIZE + 20) != decompressed_size:
            w = f"dir block @{block_offset}: count/size mismatch — skipping block"
            if strict:
                raise RdaFormatError(f"{path}: {w}")
            warns.append(w)
            _warn(w)
            block_offset = next_block
            continue
        off = 0
        for _ in range(file_count):
            # Names are NUL-padded; cut at the first NUL so trailing
            # garbage after it is ignored.
            name = buf[off:off + FILENAME_SIZE].decode(
                "utf-16-le").split("\x00", 1)[0]
            off += FILENAME_SIZE
            foff, fcomp, funsize, fts, funk = struct.unpack("<5I", buf[off:off + 20])
            off += 20
            norm = name.replace("\\", "/")
            if norm in names_seen:
                # A duplicate name would silently shadow one copy, and a
                # round-trip verify cannot notice (the member sets compare
                # equal), so it has to be caught here.
                if strict:
                    raise RdaFormatError(
                        f"{path}: duplicate entry name {norm!r} in block "
                        f"@{block_offset} (first seen in block "
                        f"@{names_seen[norm]}) — corrupt or hand-crafted "
                        "archive")
                _warn(f"duplicate entry name {norm!r} (block "
                      f"@{block_offset}) — keeping the last copy")
            else:
                names_seen[norm] = block_offset
            files.append((name, foff, fcomp, funsize, flags, fts))
        block_offset = next_block

    if not files:
        raise RdaFormatError(
            f"{path}: no readable entries — truncated or corrupt file")


    entries = {}
    for name, foff, fcomp, funsize, fl, fts in files:
        # Bound-check the file region against EOF before reading it.
        if foff + fcomp > fsize:
            w = (f"file region past EOF: {name} [{foff}, {foff + fcomp}) "
                 f"vs file size {fsize}")
            if strict:
                raise RdaFormatError(f"{path}: {w} — truncated archive")
            warns.append(w)
            _warn(w)
            continue
        f.seek(foff)
        data = _read_exact(f, fcomp, f"file region {name}", path)
        if fl & 2:
            data = _decrypt(data, SEED)
        if fl & 1:
            if fcomp == 0 and funsize == 0:
                # Empty member stored as zero bytes inside a compressed
                # block (other packers do this) - legitimately empty.
                data = b""
            else:
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    if len(data) == funsize:
                        # Stored RAW inside a compressed block and the size
                        # matches the declared uncompressed size: accept
                        # (warn only). "Not zlib" is not the same as
                        # "corrupt" - the size invariant below is the real
                        # corruption signal.
                        _warn(f"{name}: stored uncompressed in a "
                              f"compressed block - accepted (size matches)")
                    else:
                        w = (f"decompress {name}: keeping raw stored "
                             f"bytes")
                        if strict:
                            raise RdaFormatError(f"{path}: {w}")
                        warns.append(w)
                        _warn(w)
        if len(data) != funsize:
            w = f"size mismatch {name}: got {len(data)} expected {funsize}"
            if strict:
                raise RdaFormatError(f"{path}: {w}")
            warns.append(w)
            _warn(w)
        entries[name.replace("\\", "/")] = (data, fts)
    if strict and warns:
        raise RdaFormatError(f"{path}: {len(warns)} warnings: {warns[:3]}")
    return entries


def read_rda(path, strict=False):
    """-> dict name -> (data: bytes, timestamp: int). Never touches the file on disk.
    strict=True: any block/file warning raises RdaFormatError instead of a
    best-effort skip/keep (data1.rda reads must be warning-free)."""
    with open(path, "rb") as f:
        return _read_rda_stream(f, os.path.getsize(path), path, strict)


def read_rda_with_md5(path, strict=False):
    """Read the archive bytes once, then hash and parse that same
    in-memory copy, so the returned md5 always describes exactly the
    entries returned (no window for the file to change in between)."""
    import hashlib
    with open(path, "rb") as f:
        blob = f.read()
    h = hashlib.md5(blob)
    return _read_rda_stream(io.BytesIO(blob), len(blob), path, strict), \
        h.hexdigest()


def write_rda(entries, out_path):
    """entries: dict name -> (data, timestamp).
    Atomic: packs to a temp file in the target directory, then os.replace()s
    it over out_path, so a failed pack never leaves a partial .rda behind.
    Returns (entry_count, block_count)."""
    if not entries:
        # An archive needs at least one block; refuse up front.
        raise RdaFormatError(
            "write_rda: refusing to write an archive with zero entries")
    names = sorted(entries)
    for arc in names:                     # names must fit the 520-byte slot
        nb = arc.encode("utf-16-le")
        if len(nb) + 2 > FILENAME_SIZE:   # keep room for the NUL pad
            raise RdaFormatError(
                f"entry name too long for the directory (>{FILENAME_SIZE // 2 - 1} "
                f"UTF-16 chars): {arc!r}")
    by_ext = {}
    for arc in names:
        by_ext.setdefault(os.path.splitext(arc)[1].lower(), []).append(arc)

    dirname = os.path.dirname(os.path.abspath(out_path)) or "."
    # Preserve the target's mode when it exists (mkstemp creates 0600).
    mode = None
    try:
        mode = os.stat(out_path).st_mode & 0o7777
    except OSError:
        pass
    fd, tmp_path = tempfile.mkstemp(prefix=".ce_pack_", suffix=".tmp", dir=dirname)
    out = os.fdopen(fd, "wb")
    block_infos = []  # [offset, flags, fileCount, dirSize, decSize, nextBlock]
    try:
        out.write(b"\x00" * (len(MAGIC_V20) + HDR_PAD + 4))  # header placeholder

        for ext in sorted(by_ext):
            compress = ext in COMPRESSED_EXTENSIONS
            dirents = []
            for arc in by_ext[ext]:
                data, ts = entries[arc]
                wdata = zlib.compress(data) if compress else data
                offset = out.tell()
                out.write(wdata)
                dirents.append((arc, offset, len(wdata), len(data), ts))
            dirbuf = bytearray()
            for arc, offset, csize, usize, ts in dirents:
                nb = arc.encode("utf-16-le")
                dirbuf += nb + b"\x00" * (FILENAME_SIZE - len(nb))
                dirbuf += struct.pack("<5I", offset, csize, usize, ts, 0)
            cdir = zlib.compress(bytes(dirbuf)) if compress else bytes(dirbuf)
            out.write(cdir)
            block_infos.append([out.tell(), 1 if compress else 0, len(dirents), len(cdir), len(dirbuf), 0])
            out.write(b"\x00" * 20)  # BlockInfo placeholder (seek back later)

        end = out.tell()
        for i, bi in enumerate(block_infos):
            bi[5] = block_infos[i + 1][0] if i + 1 < len(block_infos) else end
        for off, flags, count, dirsz, decsz, nxt in block_infos:
            out.seek(off)
            out.write(struct.pack("<5I", flags, count, dirsz, decsz, nxt))
        out.seek(0)
        out.write(MAGIC_V20 + b"\x00" * HDR_PAD + struct.pack("<I", block_infos[0][0]))
        out.flush()
        os.fsync(out.fileno())   # durable before the atomic replace
        out.close()  # flush + close temp before replace
        if mode is not None:
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, out_path)
        # Make the rename durable (POSIX dir entry sync)
        try:
            dfd = os.open(dirname or ".", os.O_RDONLY)
        except OSError:
            dfd = None
        if dfd is not None:
            try:
                os.fsync(dfd)
            except OSError:
                pass
            finally:
                os.close(dfd)
    except BaseException:
        try:
            out.close()
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return len(names), len(block_infos)
