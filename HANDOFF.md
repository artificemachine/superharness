# Handoff — superharness v1.44.18 (2026-05-01)

> Branch: `main`
> Published: v1.44.18 on PyPI + GitHub
> Installed locally: `pipx install superharness` (v1.44.18)
> Morpheme: v0.10.0 on GitHub (artificemachine/morpheme, private)

## Session summary

Executed the dashboard YAML→SQLite migration plan (docs/plans/dashboard-yaml-to-sqlite.md). 4-step TDD migration: added 3 new state_reader functions, removed dead YAML fallbacks from 10 dashboard functions, migrated inbox reads, and fixed 6 read-modify-write paths to use SQLite exclusively. 14 new tests, zero regressions. Post-audit found and fixed 3 gaps. Published to PyPI as v1.44.18.

## What was shipped

| PR | What | Version |
|----|------|---------|
| #1 | **Idempotent migrations** — `_column_exists`, `_add_column_if_missing`, pre-migration backups, savepoint per version | v1.44.12 |
| #2-A | **Dropped obsolete test** — `test_parallel_checkout_safety.py` (548 lines, v1.42 inbox primitives) | v1.44.13 |
| #5 | **Daemon detached subprocess** — replaced `threading.Thread` with `os.fork` + `os.setsid` + `os.execvpe`. Monitor now survives CLI exit. 2 new tests. | v1.44.14 |
| #2-B | **Split-brain conftest** — auto-seeds SQLite from YAML in `clean_harness` fixture. Partial fix; 20 tests still need individual rewrites. | v1.44.15 (test-only, no release tag) |
| #4 (morpheme) | **Poller visibility + /health** — `errorCount`, `lastErrorMessage`, `lastSuccessAt` tracked. `GET /health` returns 200/503. 152/152 tests pass. | v0.10.0 |
| #3 | **Dashboard YAML→SQLite migration** — 14 dead YAML reads removed from dashboard-ui.py. Added `get_failures()`, `get_decisions()`, `get_ledger_entries()` to state_reader. Fixed 6 read-modify-write paths (set_task_status, contract_task, kanban_board, task delete, set_owner, owner removal, discussion-close archival). 14 new TDD tests. Post-audit gap fixes: removed YAML write in cleanup_inbox, removed inbox_file.exists() guard, bumped __version__, updated CLAUDE.md. | v1.44.18 |

## How to continue

### Remaining roadmap items (deferred)

1. **PR #2-B — split-brain test fixtures (remaining 20 tests)**
   - Files: `tests/unit/test_task_workflow_v2_phase1.py` (8 failing), `tests/unit/test_task_failed_reason.py` (12 failing)
   - Pattern: each test writes contract.yaml, runs shux commands, and asserts against YAML — but shux reads SQLite. Fix: add `seed_sqlite_from_yaml(project)` after YAML write, change assertions to use `get_task_from_sqlite`.
   - Helper already exists in `tests/helpers.py`

2. **PR #2-C — reconciler bugs**
   - `_reconcile_zombies(project_dir)` called at `inbox_watch.py:1931` but never defined/imported — NameError at runtime
   - Reconciler files (`zombie_reconcile.py`, `watcher_gc.py`) don't exist — logic is inline or missing
   - Tests: `test_zombie_reconcile.py` (2 failing), `test_watcher_auto_gc.py` (9 failing)

3. **PR #3 — dashboard YAML→SQLite** ✅ DONE
   - Remaining YAML reads in dashboard-ui.py: 12 (all legitimate — handoffs, discussions, agent-pulse). Verified with `tests/unit/dashboard/test_dashboard_sqlite_only.py`.
   - Bonus: removed YAML from `inbox_counts()` and `inbox_owner_counts()` (not in original plan).
   - Gap fixes applied: removed dead YAML write in `cleanup_inbox` handler, removed `inbox_file.exists()` guard in `task_instructions()`.
   - Static check: only `_tasks_from_yaml()` (non-harness fallback) reads `contract.yaml` via `yaml.safe_load`.

4. **PR #3-B — Next-wave: ancillary commands YAML→SQLite** (new)
   - Files still reading/writing tombstone YAML:
     | File | Severity | What |
     |------|----------|------|
     | `commands/onboard.py:315-331` | **HIGH** | Full read-modify-write to contract.yaml, no SQLite mirroring |
     | `commands/inbox_watch.py:1543-1586` | **HIGH** | Reads contract.yaml, mutates, yaml.dump back, then mirrors to SQLite |
     | `commands/inbox_watch.py:2328-2361` | **HIGH** | Discussion reconcile: same inverted pattern |
     | `commands/handoff_write.py:88,116` | Medium | Reads contract.yaml for TDD policy + task existence |
     | `commands/recap.py:53,96` | Medium | Reads inbox.yaml + contract.yaml for recap |
     | `engine/preflight.py:154` | Medium | Reads contract.yaml for dependency checking |
     | `engine/recall.py:109` | Medium | Reads contract.yaml for title-matching recall |
   - Approach: migrate each to use `state_reader` for reads, `tasks_dao`/`inbox_dao` for writes

### Quick setup for next session

```bash
cd ~/DevOpsSec/superharness && git checkout main && git pull
pipx upgrade superharness          # should install v1.44.18
shux --version                     # should be 1.44.18
uv run pytest tests/unit/dashboard/ -q  # should be 14 passed
```

### Current test baseline
- Dashboard unit: 14/14 pass (all new), 0 regressions
- Unit (relevant subsets): 401 passed, 53 pre-existing failures (parity deprecated, yaml_sync deprecated, dashboard port-detection, stale-YAML integration tests)
- ShipGuard: 2 CRITICAL — false positives in `test_redact.py`

### New files
- `tests/unit/dashboard/test_state_reader_coverage.py` — 7 tests for new state_reader functions
- `tests/unit/dashboard/test_dashboard_sqlite_only.py` — 7 tests verifying no contract/inbox YAML reads

### Files to ignore
- `.superharness/state.sqlite3*` — daemon runtime state
- `.superharness/daemon-monitor.py` — auto-generated, harmless in .superharness/
- `uv.lock` — dev dependency lock
