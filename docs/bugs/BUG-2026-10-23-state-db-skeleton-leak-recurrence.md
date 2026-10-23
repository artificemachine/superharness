# BUG 2026-10-23 — skeleton `state.db` leak is still active: 63,493 empty directories (~21 GB) on shux 1.86.4

**Severity:** medium — no data loss, but unbounded disk growth. On the reporting machine it contributed to the data volume reaching 98% full.
**Status:** open. Recurrence of `BUG-2026-09-18-state-db-skeleton-leak.md`; that report's inventory-only `shux state-gc` shipped, the leak did not stop.

## Summary

Five weeks after the 2026-09-18 report (22,485 directories archived and pruned by hand), `~/.local/state/superharness` holds **63,493 directories** again. Growth is in bursts, not steady: 10-05 6,503; 10-07 4,073; 10-15 3,244; 10-19 3,625 (birth time, `stat -f %SB`). Bursts of 1,000 to 3,700 per hour point at automated test runs, not interactive use.

## Evidence (measured 2026-10-23, macOS, shux 1.86.4)

- `state.db` sizes: 63,337 of 63,493 are exactly 348,160 bytes (schema only); 129 are 339,968; 2 are 319,488; the largest is 7.4 MB. Four sampled 348,160-byte databases had 0 rows in `tasks`, `handoffs`, `ledger`, `inbox`.
- Hash-to-path matching (`sha256(abspath)[:12]`, against every directory still on disk under the dev tree and `$TMPDIR`): 1,696 of 63,493 matched. The rest belong to paths that no longer exist, so they cannot be attributed. Matches: about 1,526 under `$TMPDIR/tmp*/` project directories, a few dozen under pytest `tmp_path` trees of a project scaffolder's test suite, plus two hits per real project checkout.
- One confirmed producer: the ai-forge template's post-generation hook runs `shux init` in every scaffolded project when `shux` is on `PATH`. ai-forge stubbed `shux` in its own `new` tests on 2026-10-08 (its issue #12), yet bursts continued on 10-13 through 10-20, so other producers remain.

## Impact

- Every caller that runs `shux` against a throwaway directory (test suites, scaffolders, CI-like scripts) leaves a 340 KB database and a `state.db.bak.v0` behind forever.
- Age is not evidence of emptiness (112 of 3,372 aged databases held rows in the first report), so the leak cannot be cleaned safely with `find -mtime`.

## Suggested direction (not a fix plan)

1. Do not create the directory or schema on the first read path; create on first write (first report's iteration 2).
2. Offer callers a documented way to opt out of persistent state for throwaway projects, for example an ephemeral state root that is removed with the project directory.
3. Find the remaining producers by logging the project path when a new state directory is created (debug level), then rerun the burst workloads.

## Second defect: `shux state-gc` is blind and not read-only (shux 1.86.4)

- **Blind:** `shux state-gc --older-than-days 1 --json` reported 0 candidates, 7 kept, 63,524 ignored. 63,379 were ignored with `state.db: unknown table 'operator_memory'`. The installed schema has an `operator_memory` table that is in neither `BUSINESS_TABLES` nor `TECHNICAL_TABLES` in `commands/state_gc.py`, although the module comment says `test_business_table_set_matches_live_schema` prevents this drift.
- **Not read-only in effect:** before the run 144 directories had a `state.db-shm` sidecar; after it, 63,530 did (created 01:57 to 02:00 local, during the run, 0-byte `-wal` and a 32 KB `-shm` each). Opening a WAL-mode database without `immutable=1` creates them. A second `state-gc` run therefore classifies nearly every directory as `sidecar present` and ignores it, so the inventory destroys its own usefulness.
- Fix direction: open with `file:...?immutable=1` (or `mode=ro` plus a check that does not need the `-shm`), and derive the known-table set from the live schema instead of a hand-kept list.

## Open question

Which workloads produced the other ~61,800 directories? The paths are gone and the hash is one-way, so only point 3 can answer it.

## Progress 2026-10-23 — throwaway projects no longer leave a permanent state directory

Confirmed producer: `shux init` (`commands/init_project.py`) wrote the database to the permanent XDG path directly, bypassing the resolver, so every scaffolded or test-created project under `$TMPDIR` left a 340 KB directory forever.

Fix (direction 2 of "Suggested direction", for the temp-directory case): `resolve_new_project_state_db_path()` in `utils/paths.py`. A project with no state yet that lives under the OS temporary directory, with no state root configured (neither `SUPERHARNESS_STATE_DIR` nor `XDG_STATE_HOME`), keeps its state in its own `.superharness/state.sqlite3`, which is removed with the project. `resolve_active_state_db_path()` uses the same helper for new projects, and `shux init` calls it.

Deliberately unchanged:
- An existing XDG or legacy database always wins.
- An explicit `SUPERHARNESS_STATE_DIR` or `XDG_STATE_HOME` is honoured (the test suite pins `XDG_STATE_HOME`, so it is unaffected).
- Dispatch worktrees under `$TMPDIR` still map to the original project through `SUPERHARNESS_STATE_PROJECT`.
- Projects outside the temp tree keep the permanent XDG path.

Verified: `tests/unit/test_state_throwaway_projects.py` (8 tests, including a subprocess `shux init` that failed before the change), plus the path, init and state-reader suites.

### Second defect fixed: `shux state-gc` is no longer blind and no longer writes

- **Blind:** `operator_memory` is created on first use by `engine/operator_memory.py`, not by `init_db()`, so the drift test (which only built `init_db()`) could not see it. It is now in `BUSINESS_TABLES`, and `test_business_table_set_matches_live_schema` and the test fixtures create it the way production does.
- **Not read-only:** databases are opened `immutable=1`. Measured on a sidecar-free WAL database: on SQLite 3.53.4 (the installed `shux`), `mode=ro` created `state.db-shm` and `state.db-wal` and the old code returned `ignored | state.db: unknown table 'operator_memory'`; on SQLite 3.51.0 `mode=ro` fails to open at all. With the fix both give `candidate | content-free` and the tree is unchanged. A directory that already has a sidecar or journal is still `ignored` before any open, so the immutable open never races a live WAL connection.
- Tests: `tests/unit/test_state_gc_blind_spots.py` (3 tests, red before) and the updated `tests/unit/test_state_gc_inventory.py`.
- The 63,000-odd sidecars the 1.86.4 run left behind are not cleaned up by this change; a later inventory still classifies those directories `sidecar present`.

Still open: direction 1 (create on first write) for writers outside the temp tree, and direction 3 (log the project path when a state directory is created) to attribute the remaining producers. Existing skeletons are not removed; `shux state-gc` stays inventory-only.
