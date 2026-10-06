# Changelog — annoedit

Release history, newest first. Entries before 2.29.1 reference test files
by their former names; see the 2.29.1 entry for the mapping.

## 2.29.1 (2026-10-06)

Release-polish build. No change to what the editor writes: the golden-bytes
hashes are unchanged and all 540 tests are green (including the GUI suite
under Xvfb).

- README rewritten: features, architecture, safety model, and an honest
  comparison with RDAExplorer (with credit to its authors). Docs refreshed
  to match the current save pipeline (replay, drift, ledger, per-target
  snapshots); screenshots added under `docs/images/`.
- Inline comments and docstrings cleaned up across the package, tools and
  tests: internal tracking tags, dates and change-history narration
  removed; each comment now explains what the code does and why.
  Docstrings that had drifted from the code were corrected (core scope
  guard, `hardened_build` exclusions, `vanilla_registry.member_class`,
  `ChangeSet.add_dial`, `Session.target_drift`).
- Fixed user-facing text: a missing space in the EXTRAS insert-refusal
  message and in the `annoedit store` help text; a garbled message in the
  off-UI-thread assertion; jargon in the out-of-range confirmation.
- Fixed documentation paths: the golden-bytes recorder is
  `tests/golden_bytes.py` (not `tools/`).
- `tools/smoke.sh` no longer defaults to a developer-specific archive path;
  pass the archive or set `ANN0140_TEST_RDA`.
- Packaging: richer `pyproject.toml` metadata and a new `annoedit-gui`
  launcher (`pip install .`).
- Removed `tools/tag_scan.py` (an internal development aid).
- Test modules renamed after what they cover:
  - `test_audit_2170.py` -> `test_save_restore_guards.py`
  - `test_audit_2210.py` -> `test_drift_live_project.py`
  - `test_audit_281.py` -> `test_core_regressions.py`
  - `test_audit_2_13.py` -> `test_replay_restore_regressions.py`
  - `test_audit_2_26.py` -> `test_snapshot_restore_protocol.py`
  - `test_audit_p0.py` -> `test_export_and_persona_loading.py`
  - `test_audit_p1.py` -> `test_data_safety.py`
  - `test_audit_p1_10.py` -> `test_conflict_granularity.py`
  - `test_audit_p1_6.py` -> `test_corrupt_archives_protected_paths.py`
  - `test_audit_p2.py` -> `test_threading.py`
  - `test_audit_p2120.py` -> `test_strict_open_and_commit.py`
  - `test_audit_p2_6.py` -> `test_absolute_queueing.py`
  - `test_audit_p3.py` -> `test_changeset_integrity.py`
  - `test_audit_p3_9.py` -> `test_single_locator.py`
  - `test_audit_p4.py` -> `test_drift_per_key.py`
  - `test_audit_p4_9.py` -> `test_change_plan.py`
  - `test_audit_p5.py` -> `test_global_revert_and_hardened.py`
  - `test_audit_p5snap.py` -> `test_per_target_snapshots.py`
  - `test_audit_p6.py` -> `test_missing_members_and_flags.py`
  - `test_audit_phase0.py` -> `test_cli_smoke_and_vanilla_protocol.py`
  - `test_audit_phase2.py` -> `test_extras_conflict_policy.py`
  - `test_audit_phase3.py` -> `test_vanilla_registry_restore_set.py`
  - `test_audit_phase4.py` -> `test_locking_and_hygiene.py`
  - `test_audit_ported.py` -> `test_engine_guards.py`
  - `test_audit_pr2.py` -> `test_session_transactions.py`
  - `test_audit_pr3.py` -> `test_typed_validation.py`
  - `test_audit_pr4.py` -> `test_baselines_and_drift.py`
  - `test_audit_pr5.py` -> `test_performance.py`
  - `test_audit_pr6.py` -> `test_hardening.py`
  - `test_audit_repros.py` -> `test_regression_repros.py`
  - `test_polish_v230.py` -> `test_gui_polish.py`
  - `test_live_features.py` -> `test_app_services.py`
  - `test_f35_reader.py` -> `test_reader_tolerance.py`
  - `test_phase4_gates.py` -> `test_source_gates.py`

## 2.29.0 (2026-10-06)

The WRITE LEDGER (tenth-audit Phase 2): what this tool wrote to a
save target is now recorded as FACTS, per target, next to that
target's pre-save snapshots (pre-flash/<target-key>/ledger.json) — the
value written and the base value it replaced, updated on every
successful commit, cleared on restore.

- Clearing a previously-saved edit is now EXACT: save, clear the edit,
  save again — the second save REVERTS the key to the value it
  replaced (the old model left the written value in the game file
  forever and mis-filed it as a foreign change with no dialog at all).
- Drift classification is ledger-driven, not guessed: a live value
  the session has no pending edit on is either MINE-NOW-CLEARED (the
  save reverts it — shown in the review), MINE-BUT-CHANGED (someone
  else touched it after our write — a real conflict the save
  surfaces), or FOREIGN (kept by the replay). The old 'landed' guess
  bucket (pending == live) is gone: a pending edit whose value
  already sits in the live file is simply a no-op for the replay.
- The review dialog shows revert rows (what the operator approves is
  what the build writes). In-place saves keep their baseline role:
  after an in-place save the session reloads the written file, so no
  revert is queued on the next save.
- EXTRAS replay-guard inheritance fixed: a reset queued over a prior
  manual edit of the same leaf no longer inherits the manual edit's
  queue-time expected_old/occ_count (a reset replaces whatever is
  there — the stale guard used to refuse a legitimate save).
- The build's EXTRAS and fertility passes now iterate the ONE change
  plan: rule rows whose target asset/pair is ABSENT from the build
  base are dropped (the old build refused the whole save at find_asset
  when a revert-globals reset row named an asset only the reference
  carried), and every row's no-op drop matches the review exactly.
- Restoring vanilla clears the target's ledger (the tool's recorded
  writes no longer describe the restored file).

Known limits (stated honestly): the ledger reverts REPLACE-shaped
writes only — a write that INSERTED a leaf absent from the opened
archive cannot be reverted by writing a value back (no delete-leaf
operation exists); the review reports those as not auto-revertable
and a stored snapshot restore remains their exact undo.

## 2.28.0 (2026-10-06)

Tenth-audit Phase 1 reminders — safety holes closed:

- EXTRAS/fertility drift conflicts are now classified at the same
  granularity as the edit key: per OCCURRENCE for extras (a live change
  at occurrence #1 alone no longer blocks a save for a pending #0 edit),
  per SIDE for fertility (a live change to South alone no longer blocks
  a pending North edit; a pair can be half LANDED, half conflict).
- Single-flight background jobs: a second background task is refused
  while one runs (a synchronous archive open from the Saved-exports
  manager racing a 30-60 s save could swap the session back to the OLD
  archive). The Saved exports button is disabled while busy. FlashResult
  now carries the frozen source_path and the save-completion callback
  drops the in-place reload when a different archive was opened while
  the build ran (the file on disk is fine; only the stale in-memory
  refresh is skipped).
- capture_vanilla runs under the store's session lock (write-once
  vanilla capture + the store-root *.tmp sweep can no longer race a
  second tool instance's in-flight temp files).

## 2.27.0 (2026-10-06)

Trustworthy signal (the tenth external audit's Phase 0) — the byte
contract and the release gate now prove themselves WITHOUT game data:

- Golden BYTES fixtures: six canonical edit workflows (persona apply,
Hardened, Vanilla reset on a modded archive, relations rewrite, EXTRAS
incl. missing-tag INSERT + multi-instance occurrence edit + ambiguous
`Name [GUID]` addressing, fertility) are driven through the real
Session stack against the synthetic archive and the four edited
members' exact output bytes are pinned as fixtures
(tests/golden_fixtures.json + tests/golden_bytes.py, recorded via
`python3 tests/golden_bytes.py record`). A refactor that still parses
and round-trips green but changes ONE emitted byte now fails loudly
with a unified diff (tests/test_golden_bytes.py) — on a data-less box.
- Release gate: `ANN0140_SKIP_GUI_GATE=1` is GONE. A headless release
cut now requires EVIDENCE — `ANN0140_GUI_RESULTS` pointing at a
`tests/results.json` written by a `--require-gui` run of the SAME
tree (verified via the new content tree hash, tools/tree_hash.py; tools/gate_verify.py). The suite records its
verdict + tree hash on every run; a gate refusal no longer leaves a
zip behind (the artifact is promoted only after all gates pass);
`ANN0140_PY` selects the interpreter for boxes where `python3` lacks
tk but another binary has it.
- CI: `CI=true` or `ANN0140_CI=1` implies `--require-gui` — a headless
CI run that skips GUI tests is a hard failure, never a green build.
- Tests: tests/test_release_gate.py (10 checks — tree hash stability /
scratch immunity / content sensitivity, gate_verify acceptance + all
refusal classes, gate_mode rules, the no-bare-bypass source pin),
tests/test_golden_bytes.py (2).

## 2.26.2 (2026-10-06)

Reader tolerance for real-world archive shapes (field report — see the
10th external audit's F-35):

- Fixed: the strict reader refused archives that store an empty member
  (an empty `.ini` marker) as zero raw bytes inside a compressed block —
  other packers and mod managers write this shape, and strict mode is
  used for every open, so such a working archive could not be opened at
  all. Empty members and raw-stored members whose size matches the
  declared uncompressed size are now accepted (warn only); only a size
  mismatch stays fatal in strict mode.
- Note: on the next save the member is re-stored zlib-compressed — the
  data is identical and the game reads both forms.
- Tests: empty member in a compressed block opens in strict mode; a
  non-empty raw-stored member (size matching) is accepted; a truncated
  zlib stream with a size mismatch still refuses (strict) or keeps raw
  bytes and warns (lenient); a rewrite round-trips through our own
  writer.

## 2.26.1 (2026-10-06)

Tenth external audit, critical + high hotfix batch (full findings and
the write-ledger design follow-up are recorded in the project notes):

- Fixed: GUI "Save to live" raised TypeError for every user (the
  build callback signature had drifted; save-to-live was broken on all
  GUI paths since 2.25.0).
- Fixed: per-character pending badges counted rule no-op rows (~980
  pending shown after a Vanilla click on an unchanged character);
  totals and per-character counts now come from the same change plan
  call.
- Fixed: `restore-snapshot` bypassed the commit protocol — it could
  overwrite the stored vanilla copy and destroyed the current target
  with no pre-restore snapshot. It now routes through the single
  commit path (lock, pre-restore snapshot, protected-path refusal).
- Fixed: `apply --json` / `flash --json` crashed AFTER writing the
  archive (non-JSON bytes in the report); reports are sanitized before
  output now.
- Fixed: surgical restore silently reverted other mods'
  `config/ai/properties.xml`; a differing schema file is now reported
  as unmodelled.
- Test fixes: the golden workflow export test asserted a wrong path and
  a value the synthetic fixture already contains natively (it could
  never pass); the golden harness now isolates the exports store the
  same way it isolates the backups store.


## 2.26.0 — ninth external audit: Phase 5 per-target snapshot store

- **Snapshots are rotated per save target** (`pre-flash/<sha1(target)[:12]>/`),
  so repeated export overwrites can no longer evict the live game file's
  pre-save snapshot (its only undo). Each target keeps its own rolling set.
- **Snapshots are no longer anonymous**: every one records its target, md5,
  timestamp and reason (`flash` / `restore` / `export`) in a per-target
  manifest.
- **List and restore them**: `annoedit snapshots [target]` lists them newest
  first; `annoedit restore-snapshot <id> <target>` restores one over a game
  archive — atomic, mode-preserving, md5-verified (a corrupt snapshot is
  refused, never restored unverified).
- **Legacy layout migrates**: flat root-level `pre-flash-*.rda` files from
  older releases move into `pre-flash/legacy/` and keep counting for the
  skip set.

## 2.25.0 — ninth external audit: Phase 4 one change plan

Regression net: `tests/test_audit_p4_9.py` (11 checks — plan invariants,
the three drift buckets, the plan-hash consent anchor, honest counts).

- ONE change plan (`annoedit/plan.py`): the drop decision for absolute-
  queued rule rows (`reset`/`harden`) — which of Vanilla/Hardened/
  revert-globals' hundreds of queued rows are REAL changes — now lives
  in ONE pure function shared by the review rows, the build's no-op
  drop, and every display count. Previously three implementations
  (review, build, drift) could disagree; the review is now BOUND to the
  build: what the operator approves is by construction what the build
  writes.
- Consent anchor = (target, base_md5, **plan_hash**): the build
  recomputes the plan against the same base and REFUSES on a hash
  mismatch — a base or pending change between the review and the save
  can no longer silently change what is written.
- Drift's per-key classification is now THREE buckets on all four
  surfaces: conflict (the replay overwrites an unseen live value),
  LANDED (the user's own earlier save already wrote it — no-op), kept
  (foreign changes, survive). Previously a landed edit was counted as
  "kept", so the dialog claimed the user was NOT editing keys they
  HAD edited.
- Honest pending counts: the roster badges, status summaries and
  discard-prompts show the REAL changes the build would make (a
  Vanilla click on an unchanged character no longer shows ~980
  pending rows or triggers "discard edits?" for non-changes).
- The per-character "Reset to vanilla" click ALWAYS confirms now,
  with the honest real-change count in the message.

## 2.24.0 — ninth external audit: Phase 3 one locator

Regression net: `tests/test_audit_p3_9.py` (16 checks — the confirmed
repros R3/R3b/R6/R4/R15 plus the independent-oracle damage classes).

- The relations reader and writer now share ONE locator (a child-axis
  span walk over the `<Relations>` node): both are comment-blind, both
  refuse duplicate real kind blocks, and the reader RAISES on a broken
  structure instead of silently returning `{}`. Previously a
  commented-out `<War>` block made the reader return the commented
  GUIDs (a silent wrong read) or made every relations edit fail with a
  misleading oracle error, and a second `<Relationships>` block read
  as "no relations" everywhere (Vanilla mode, drift, review, CLI).
- The oracle's duplicate-kind counter (a raw regex over unmasked text
  that counted commented blocks) is gone — the shared reader refuses
  duplicates itself, correctly.
- Independent ElementTree oracle: after every dial/relations edit the
  edited asset is parsed with `xml.etree` (blind to comments by
  construction) and compared against the expected canonical form
  (the old tree with the requested edits applied abstractly, insert
  positions mirrored). Damage the shared locator cannot see — a GUID
  moved inside `<Relations>` during a dial edit, a clobbered sibling,
  an emptied leaf — now fails the edit before it is committed.
- Duplicate profile identity (two assets, same Name+GUID) is REFUSED
  at parse time and `_locate_values` requires exactly one identity
  match: previously the roster showed one copy while edits landed in
  the other.
- Fertility parse and edit share one locator too: comment-masked scans
  everywhere, duplicate tier keys and duplicate `<FertilityRates>`
  blocks refused. Previously a duplicated tier made the catalog show
  one copy while the edit silently rewrote the other (an invisible
  edit).
- `extras.occurrences`' SpanError fallback regex is comment-masked.
- Drift fails CLOSED on an unreadable relations structure
  (DriftUnavailable, never a silent empty compare), and a broken
  vanilla reference aborts a Vanilla click cleanly with a rollback
  (SessionError), never by copying a silent `{}` into the pending
  state.

## 2.23.0 — ninth external audit: Phase 0 golden workflows + Phase 2

Regression net: `tests/test_golden_workflows.py` (four end-to-end user
flows driving the real App methods — display-gated — plus headless
per-target rows tests and source pins).

- Added the four golden workflow tests (audit Insight D): first-use
  save-to-live; opened≠live save-as-export (the export must contain
  exactly the reviewed rows); another-mod survival on save-to-live;
  vanilla-mode + surgical-restore md5 equality.
- The Review dialog now re-binds its rows to the chosen save target
  (audit H2, interim fix): *Save as export…* builds from the OPENED
  archive, so the dialog recomputes and re-displays the opened-based
  rows (including the no-op rule-row drops the build makes) before
  anything is approved; a cancelled prompt or refused overwrite restores
  the live-based rows; *Save to live* re-displays the live-based rows.
  Previously the rows were computed against the live file while the
  export built from the opened file — the operator approved one list
  and a different one was written.

## 2.22.0 — ninth external audit (targets the 2.21.0 zip): Phase 1 hotfixes

Regression net: `tests/test_audit_2210.py`.

- Fixed a crash in the first-use save-to-live flow: when no tracked
  member differed between the opened file and the live file, the drift
  check handed the Review dialog a raw entries dict as `DriftResult.live`;
  the review's row computation calls `base.by_guid` on it and raised
  `AttributeError` (Critical, reproduced headless and under xvfb by the
  audit). The no-diff branch now builds a full `ModProject`, and the
  `DriftResult` constructor refuses any `live` that is not a
  `ModProject` or `None`, so the bug class cannot be constructed.
- The EXTRAS-conflict dialog printed a bound method
  (`<bound method Session.live_path …>`) instead of the actual live
  file path; the message now shows the real path (call the method).
- A test no longer imports the tkinter module it only reads as text
  (`app.py` is located by path), so the suite stays clean on machines
  without python3-tk.

## 2.21.0 — eighth external audit (targets the 2.18.0 zip): full pass

Phase 0 — quick fixes, each with its regression test
(`tests/test_audit_phase0.py`):
- `annoedit log` no longer crashes: `-n` moved to the `log` subparser;
  a CLI smoke test now parses every subcommand (M-1).
- The vanilla-copy md5 record is now committed DURABLY BEFORE the copy
  and the copy is hashed while it is read (no TOCTOU); restore refuses
  a copy present without a record instead of silently skipping
  verification forever (H-1).
- The stale-temp sweep matches the CURRENT temp names
  (`.annoedit-*.tmp/.verifytmp`, legacy names too) and sweeps the LIVE
  directory as well as the opened archive's (M-6).
- Malformed profile structure raises `EditError` from `_relations_node`
  instead of silently reading relations as `{}` (M-7).
- The no-`--char` persona branch counts relations too (M-14);
  `revert-globals` reports honest counts and "nothing to revert" is
  reachable (M-15).
- Relations clash messages name BOTH conflicting kinds (L-1);
  `normalize_flags`' unreachable branch documented/removed (L-2);
  unused `_INT_TYPES`/`normalize_float` removed (L-3); pyflakes-clean
  imports across tests + tools (L-13).
- README/doc claims corrected where the code disagreed: absolute
  queueing scope, validation exemptions, glossary IP note, "immutable"
  model, manual no-op drops, review/build drop rules (§6).

Phase 1 — performance (H-5), pinned by `tests/test_perf_budget.py`:
- `parse_assets` is cached per text object (ModProject replaces the
  text on every edit, so identity implies freshness).
- New one-pass batch engine `extras.set_extras(text, edits)`; the
  build applies ALL pending EXTRAS edits in ONE pass (descending splice
  order, byte-identical to the sequential equivalent on disjoint
  leaves), and the replay guard reads from ONE parse with a per-(asset,
  tag) cache. The revert-globals cliff (~0.3 s x ~1000 edits on real
  data) is gone: a 20-edit batch now costs about ONE parse.

Phase 2 — conflict policy + honest revert:
- EXTRAS drift conflicts are BLOCKING: the replay guard refuses them
  at build time, so the old "Continue anyway?" consent was a dead end.
  The dialog now explains and names the LIVE file to open instead
  (S3/H-3); the build refusal message points there too.
- "Revert to vanilla (global)" reports the tool's own allow-listed
  INSERTS (e.g. ProductionTime on the four donor buildings) as
  un-revertable (no delete op exists) instead of silently keeping them
  (H-2) — recorded in `Session._last_unrevertable_extras`, surfaced as
  a GUI warning on both tabs.
- A Vanilla click without a vanilla reference (no baseline, or the
  character absent from it) drops pending edits only and the mode
  label says "Cleared (no vanilla reference)" — never claims `vanilla`
  (M-8).

Phase 3 — identity and trust:
- Real-data census (vanilla assets.xml): the multi-instance noria
  tags live under DIFFERENT parents (Green/Moisture/Saturated ground
  states, not "levels"). New `extras.parent_paths()`; the EXTRAS edit
  prompt now shows each occurrence's parent path and warns when the
  occurrences live under different parents (H-4 display half; the
  path-qualified keying remains the deeper fix).
- New `annoedit/vanilla_registry.py`: per-member SHA-256 table (+ whole
  file md5) for the current History Edition vanilla build (a hash is
  not game data). `provide_vanilla` records a verified/modded/partial
  verdict and the GUI surfaces "VERIFIED vanilla build" or a loud
  warning (S4).
- The surgical-restore set now includes the schema-defaults
  `properties.xml` (effective AI behaviour depends on it); the EDIT
  scope stays the 4 members (M-12).
- `tests/test_audit_phase3.py` pins all of the above.

Phase 4 — hygiene:
- `_Flock`'s depth counter is guarded by an internal `threading.RLock`
  (a background load and a Tk-thread close no longer race the counter)
  (M-9).
- `release_keystream_cache()` frees the multi-MB decrypt keystream in
  long-lived GUI processes (M-11).
- Settings writes use a UNIQUE temp name (two processes no longer race
  the fixed `settings.json.tmp`) (L-8).
- `text_span` raises on unclosed fragment nodes instead of slicing
  `[open_end:-1]` (L-4); prune removes `.md5` sidecars with their
  archives (L-10).

## 2.19.0 / 2.20.0 — earlier (see docs/index.md)

- 2.20.0 shipped the Phase 0 fixes above (superseded by this release
  packaging; the fixes listed under 2.21.0 Phase 0 landed in 2.20.0).
- 2.19.0: comment cleanup for publication (all internal audit-tag
  references removed; invariants kept in docstrings, history here).

## Earlier history

The pre-2.3.x era (charactereditor rename, EXTRAS/fertility port,
live-feedback rounds, relations feature, static polish, audits one
through seven) is condensed in the workspace `CHE.md` and the
`analysis/` archives.
