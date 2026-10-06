# Safety and verification

The tool's core promise: **you can always go back, and nothing outside the
files it knows about ever changes.** Both properties are enforced in code
and checked by tests, not left to good intentions.

## Where things are stored

Everything lives under `~/.anno1404gameeditor/` (or `$ANN0140_HOME`):

| Item | Behavior |
|---|---|
| **Provided vanilla copy** | `Provide vanilla…` stores the pristine archive once as `exports/data1.rda_vanilla`, write-once, with its md5 recorded *before* the copy lands (a crash can never leave an unrecorded copy). It is strictly parsed before it is accepted, classified against a registry of known-vanilla hashes, verified against its md5 before every restore, and is the source of the Vanilla column |
| **First-open snapshot** | The first archive you open is also copied to `backups/vanilla-<md5>.rda` (write-once). It is labelled unverified and used for Restore only when no vanilla copy was provided |
| **Pre-save snapshots** | Before every save, the bytes about to be replaced are kept under `backups/pre-flash/<target-key>/`, rotated **per save target** (the last 5 each), with target, md5 and reason recorded. Skipped when the same bytes are already preserved. `annoedit snapshots` lists them, `annoedit restore-snapshot` restores one (md5-verified, and itself snapshotted first) |
| **Write ledger** | Per target, what the tool wrote and the value it replaced. It lets the next save revert an edit you cleared, and tell your own earlier writes apart from another mod's changes |
| **Named exports** | `exports/data1.rda_<name>` plus metadata, managed via **Saved exports…** |
| **Activity log** | `annoedit.log`, auto-rotated: every open, provide, save, restore and export |

## Protections on every write

- **Protected paths.** No write path (GUI, CLI, restore, snapshot restore)
  may target the stored vanilla copy, the backup store or the export store.
  Exports go into the store only through its own entry point.
- **Session lock.** An advisory lock on `backups/session.lock` (`flock` on
  Linux/macOS, `msvcrt` on Windows) is taken for every write, so two tool
  instances, or the GUI and CLI at once, cannot interleave.
- **Atomic replace.** A game file is replaced by exactly one `os.replace`
  of a verified temp file in the same directory, after an `fsync`, keeping
  the file's mode. On Windows, a locked file produces a clear "close the
  game (and Steam)" message.
- **Snapshot before replace.** If the pre-save snapshot cannot be written,
  the save aborts with the target untouched.
- **Changed-on-disk guard.** The save refuses if the target changed since
  you opened it (in-place save) or since you reviewed it (save to live).
- **Nothing after the replace may fail the save.** Post-commit bookkeeping
  (reloading, ledger, log) is best-effort and can never report a written
  file as a failed save.

## The save pipeline (GUI `Save to live` = CLI `flash`)

1. **Freeze** the pending edits (a snapshot of the ChangeSet). Edits you
   make while the save runs stay pending; they are never half-included.
2. **Drift check** (save to live): compare the opened archive, the live
   file and your pending edits. Conflicts (live values your edit would
   overwrite) are shown before anything is written; unrelated live
   differences are kept; unexplained differences inside the tracked files
   (another mod) are reported.
3. **Review.** Every change as one row (character, dial, old -> new).
   The rows come from the change plan (`annoedit/plan.py`), the same plan
   the build uses. The plan's hash and the live file's md5 form the consent
   anchor.
4. **Build** into a temp file next to the target, **replaying** the pending
   edits onto the target's own members (by identity, not offset). Every
   member the editor does not touch is copied unchanged.
5. **Verify** before replacing (any failure aborts, target untouched):
   - every edit passed the independent oracle (see the
     [edit engine](edit-engine.md));
   - the profile files and `assets.xml` parse as XML;
   - **scope guard**: only the two AI profile files, `assets.xml` and
     `randommapgenerator.xml` may differ from the base;
   - the plan hash still matches what you approved;
   - **round trip**: the packed temp file is re-read strictly, and every
     member's bytes and the member name set must match.
6. **Snapshot** the current target bytes, then **replace** atomically.
7. Update the ledger and log; reload in place if you saved over the
   archive you have open.

## Restore Vanilla

Restore copies **from** the stored vanilla copy (verified against its md5),
never onto it. By default it is **surgical**: only the members the editor
can change (plus the schema-defaults file `properties.xml`) are restored,
and only where they differ from vanilla; everything else in the live file,
such as other mods, is kept. Tracked members that carried edits the editor
does not model are restored too, but listed. When the result is
data-identical to vanilla, the pristine vanilla bytes are copied as-is, so
the restored file is byte-identical. A restore snapshots the current file
first, and `annoedit restore <archive> --full` replaces the whole file.
Restore never needs to parse the target first, so it also works on a
corrupt file.

## Reading archives

Every archive the editor might write back is read **strictly**: a block
pointer past the end of the file, a region past its bounds, a cyclic block
chain, a duplicate entry name or a memory-resident block fails the open.
A lenient read that silently skipped a damaged member would otherwise let
the next save "verify" an archive with members missing.

## Threading

Long operations (open, save, restore, drift check, export) run on a worker
thread as pure functions (`annoedit/ops.py`) over frozen inputs. Only the
UI thread mutates session state; the test suite enforces this. A second
background job is refused while one is running.

## What the test suite checks

`python3 tests/run_tests.py` runs 540 tests with the standard library only.
A synthetic RDA archive is generated on the fly, so no game data is needed;
tests that need the real archive skip cleanly unless `ANN0140_TEST_RDA`
points at one.

- **Format**: round trips, strict-read refusals, cipher, reader tolerance
  for other packers' quirks.
- **Engines**: span-engine property tests on random nested XML,
  comment-blind locators, insert shapes, the oracle, typed validation.
- **Golden bytes**: six canonical workflows (persona, hardened,
  vanilla-on-modded, relations, extras with inserts and multi-occurrence
  edits, fertility) produce exactly the pinned bytes.
- **Session and safety**: transactions, locking, protected paths,
  snapshots, ledger reverts, drift classification, consent anchors,
  surgical restore, threading rules.
- **GUI**: under Xvfb, including end-to-end workflows driven through the
  real App methods. `--require-gui` turns any skipped GUI test into a
  failure.
- **Real data** (when available): hardened-build pins, and the personas
  reproducing the in-game-verified build byte for byte.
- **CLI smoke** (`tools/smoke.sh <archive>`): personas, list, dial lookup,
  dry run, flash, restore on a temp copy, verified by md5.

## Known limits

- **Old saves may keep AI values.** The personas were verified on *new*
  endless games; fertility applies to newly generated islands only.
- **Verified in game: the three personas.** EXTRAS, fertility, arbitrary
  relations edits and Hardened are verified by tests only.
- **Value ranges are not fully known.** The schema documents ranges, and
  the tool warns when you exceed them, but the in-game-verified personas
  use out-of-range values successfully (e.g. `SpyDetectValue` 85 against a
  documented max of 70), so out-of-range edits are allowed after
  confirmation.
- **No delete-leaf operation.** Values a modded archive added and vanilla
  lacks cannot be removed by Vanilla mode or by the ledger; they are
  listed, and a snapshot restore is their exact undo.
- **Campaign behavior is untested.** The personas target endless play.
- The game file is *your* copy: the tool never ships or downloads game
  data, and presets are pure dial values.

Back to [docs index](../index.md)
