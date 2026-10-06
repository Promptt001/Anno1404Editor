# The RDA V2.0 archive format

`data1.rda` (and every other `.rda` file in the game) is a **"Resource File
V2.0"** container. This is the format this tool reads and writes, learned by
dissecting the game's files plus the community's C# RDAExplorer as a
reference; `annoedit/rda.py` implements it in a single standard-library
module.

## Header

| Offset | Size | Content |
|---|---|---|
| 0 | 36 B | UTF-16LE magic string `"Resource File V2.0"` (18 chars × 2 B) |
| 36 | 1008 B | zero padding |
| 1044 | 4 B | `firstBlockOffset` (u32) — offset of the first block info |

Total header: **1048 bytes**.

## Blocks

Block info records come AFTER the block's file data + directory (one
per block, chained via `nextBlockOffset`); each is **20 bytes (5 × u32)**:

| Field | Size | Meaning |
|---|---|---|
| `flags` | u32 | see below |
| `fileCount` | u32 | entries in this block's directory |
| `dirSize` | u32 | directory size in bytes |
| `decSize` | u32 | decompressed (unpadded) directory size |
| `nextBlockOffset` | u32 | offset of the next block info (the LAST
block's writer points at EOF, not 0) |

**Flags** (bitfield):

| Bit | Value | Meaning |
|---|---|---|
| 0 | 1 | directory block is **zlib-compressed** |
| 1 | 2 | directory block is **encrypted** |
| 2 | 4 | memory-resident (refused by this reader; Anno 1404's `data1.rda` has none) |
| 3 | 8 | deleted/unused |

A typical addon `data1.rda` is 3 blocks / 4,474 file entries.

## Directory entries

Each directory entry is **520 bytes + 5 × u32**:

| Field | Size | Meaning |
|---|---|---|
| filename | 520 B | UTF-16LE, NUL-padded |
| offset | u32 | file data offset |
| csize | u32 | compressed (stored) size |
| usize | u32 | uncompressed size |
| unixtime | u32 | timestamp |
| unk | u32 | unknown (0 in practice) |

## File data

- Text-ish files (`.xml .txt .cfg .ini`) are **zlib-compressed**;
  everything else is stored raw.
- Encrypted blocks (flag 2) apply to both directories and file data in
  some archives (the save-game `.sww` wrapper uses this too).

## Encryption

The game's stream cipher (seed-based, per-16-bit-word):

1. Seed `0xA2C2A` with an LCG step of `x = (x * 214013) + 2531011`.
2. For each 16-bit word of plaintext, XOR with `(counter >> 16) & 0x7FFF`.
3. **Decrypt before zlib-decompress** — the ciphertext is what's stored.

## The one gotcha that crashes the game

Archive entry names **must use forward slashes**
(`addondata/config/game/assets.xml`).

The first repacker we wrote used `os.sep`-style backslashes on the
matching OS — the game read *no files at all* from that archive and
crashed instantly at launch. Worse: a naive round-trip test did not catch
it, because an extractor that normalizes `\` → `/` on read would read the
broken archive back "correctly". The lesson is baked into this project:
**round-trip tests must compare raw entry names**, with no normalization,
before any archive ships.

## Scope of this tool's implementation

`annoedit/rda.py` implements exactly what the editor needs: read all
entries (compressed or encrypted) strictly, rewrite entries, repack, and
verify the result round-trips byte-identically. It never opens the game's
file for writing: outputs always go to a temp file that is verified and
then atomically renamed into place (see
[safety-and-verification](safety-and-verification.md)).

Not implemented (yet): RDA V2.2 (the later Anno titles' variant, with a
UTF-8 magic and 64-bit offsets) and memory-resident blocks.

Back to [docs index](../index.md)
