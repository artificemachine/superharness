# Handoff — superharness (2026-05-07)

> Status: branch `feat/test-unification-task`, uncommitted changes
> PyPI latest: v1.47.5
> `shux status`: clean — no issues, no active tasks, inbox clear

## What just happened (this session)

Three watcher bug fixes + regression test suites. All changes are on `feat/test-unification-task`, not yet committed.

### Fix 1 — Flood prevention: `auto_enqueue_approved()` in `inbox_watch.py`

Root cause of the 53-item flood bug: `auto_enqueue_approved()` only blocked re-enqueue of **active** (pending/launched/running) items. When dispatch failed, the item left the active set and the next watcher tick created a fresh item at `retry_count=0`, looping forever.

Three sub-fixes:
- **`failed_counts` guard**: COUNT failed items per task from SQLite; skip re-enqueue when `failed_counts[task_id] >= max_retries`
- **`StateError` catch**: wrapped `inbox_dao.enqueue` in `try/except` to swallow race-condition duplicates gracefully
- **YAML sync fix**: appended `new_items` (SQLite-only) not already in `current_items` back to YAML — fixed 2 pre-existing test failures in `test_auto_dispatch.py`

4 regression tests: `tests/unit/test_auto_enqueue_flood_prevention.py`

### Fix 2 — Zombie max-age cap: `_reconcile_zombies()` in `inbox_watch.py`

Root cause of the 406-minute stale launched item: alive-PID non-plan-only items had no wall-clock cap — the reconciler just `continue`d past them forever.

Added **Check 2c**: non-plan-only launched items with alive PIDs running > 2 hours get SIGTERM'd and marked failed. Plan-only items keep the existing 15-min cap (Check 2b). Updated docstring to list all 5 checks.

4 regression tests: `tests/unit/test_reconcile_zombie_max_age.py`

### Fix 3 — Auto-archive handoff filter: `_auto_archive_stale_tasks()` in `inbox_watch.py`

Root cause of stale `in_progress` tasks not being archived: the handoff check used `if handoffs: continue` — any handoff file, including a plan-phase one, blocked auto-archive. A task with a plan handoff from a failed gemini dispatch would sit `in_progress` indefinitely.

Fix: only `-report-` or `-done-` filenames exempt a task. Plan handoffs (`-plan-`) are ignored for the archive decision.

5 regression tests: `tests/unit/test_auto_archive_stale_tasks.py`

## Files changed (not yet committed)

- `src/superharness/commands/inbox_watch.py` — 3 fixes above
- `tests/unit/test_auto_enqueue_flood_prevention.py` — new (4 tests)
- `tests/unit/test_reconcile_zombie_max_age.py` — new (4 tests)
- `tests/unit/test_auto_archive_stale_tasks.py` — new (5 tests)

## First thing next session

Commit and PR all 3 fixes as a single patch:

```bash
git add src/superharness/commands/inbox_watch.py \
        tests/unit/test_auto_enqueue_flood_prevention.py \
        tests/unit/test_reconcile_zombie_max_age.py \
        tests/unit/test_auto_archive_stale_tasks.py \
        CHANGELOG.md HANDOFF.md
git commit -m "fix(watcher): flood prevention, zombie max-age cap, auto-archive handoff filter (vX.Y.Z)"
gh pr create ...
```

Bump version (patch: fix commit) in `pyproject.toml` + `CHANGELOG.md` before committing.

Also: PR #190 (`fix/auto-dispatch-valid-agents-v1.47.5`) may still be open — check `gh pr list` and merge first if so.

## Tasks completed this session (report_ready — awaiting shux close)

- `feat.dashboard-auto-restart-on-upgrade` — report_ready (implementation verified, 8/8 tests GREEN)
- `feat.refactor-do-dispatch-decomposition` — report_ready (decomposition was already done, dead stubs removed, 11 tests added)

## Known remaining issues

- Pre-existing CI failures on unit/integration/E2E (same failures on `main`) — `test_enqueue_writes_inbox` is the main one (SQLite-only mode doesn't write `inbox.yaml`). Tracked separately.
- Watcher lock hash differs between Python environments (pyenv 3.11 vs pipx/homebrew 3.14) — each computes a different hash for the same project path, so two instances can both think they hold the lock. Fix: normalize to `os.path.realpath()` in `watcher_lock_path()`.
- `_classify_task()` in `auto_dispatch.py` still has a hardcoded `mini→codex-cli / else→claude-code` tier mapping — needs model router awareness of all 4 agents. Low urgency.

## Previous roadmap items (deferred)

- **PR #2-B**: split-brain test fixtures (`test_task_workflow_v2_phase1.py`, `test_task_failed_reason.py`)
- **PR #2-C**: reconciler bugs (`_reconcile_zombies` never defined, `zombie_reconcile.py` missing)
- **PR #3-B**: ancillary commands YAML→SQLite (`onboard.py`, `inbox_watch.py`, `handoff_write.py`, `recap.py`, `preflight.py`, `recall.py`)
