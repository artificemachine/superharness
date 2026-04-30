# Handoff — superharness v1.44.14 (2026-04-30)

> Branch: `main`
> Published: v1.44.14 on PyPI + GitHub
> Morpheme: v0.10.0 on GitHub (artificemachine/morpheme, private)

## Session summary

Executed the improvement roadmap (docs/improvement-roadmap.md). Shipped 5 of 8 PRs. 3 test-refactor PRs deferred.

## What was shipped

| PR | What | Version |
|----|------|---------|
| #1 | **Idempotent migrations** — `_column_exists`, `_add_column_if_missing`, pre-migration backups, savepoint per version | v1.44.12 |
| #2-A | **Dropped obsolete test** — `test_parallel_checkout_safety.py` (548 lines, v1.42 inbox primitives) | v1.44.13 |
| #5 | **Daemon detached subprocess** — replaced `threading.Thread` with `os.fork` + `os.setsid` + `os.execvpe`. Monitor now survives CLI exit. 2 new tests. | v1.44.14 |
| #2-B | **Split-brain conftest** — auto-seeds SQLite from YAML in `clean_harness` fixture. Partial fix; 20 tests still need individual rewrites. | v1.44.15 (test-only, no release tag) |
| #4 (morpheme) | **Poller visibility + /health** — `errorCount`, `lastErrorMessage`, `lastSuccessAt` tracked. `GET /health` returns 200/503. 152/152 tests pass. | v0.10.0 |

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

3. **PR #3 — dashboard YAML→SQLite**
   - 131 `yaml.safe_load` calls across ~30 files
   - Key files: `dashboard-ui.py` (~32 calls), `dashboard_presenter.py`, `inbox_watch.py`, `task.py`
   - Approach: replace each with `read_contract` / `inbox_dao.get_all` / `tasks_dao.get`

### Quick setup for next session

```bash
cd ~/DevOpsSec/superharness && git checkout main && git pull
pipx upgrade superharness
shux --version  # should be 1.44.14
```

### Current test baseline
- 496 failed, 2116 passed (pre-existing; roadmap PR #2-B targets ~135 of these)
- ShipGuard: 2 CRITICAL — false positives in `test_redact.py` (test fixtures for credential redaction)

### Files to ignore
- `.superharness/state.sqlite3*` — daemon runtime state
- `.superharness/daemon-monitor.py` — auto-generated, harmless in .superharness/
- `uv.lock` — dev dependency lock
