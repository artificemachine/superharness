# Task Handoff: mod.4-autoschedule

**From:** claude-code
**To:** owner
**Date:** 2026-03-20T13:02:35Z
**Status:** DONE

---

## Summary

Completed **mod.4-autoschedule** — Auto-schedule module (watcher tick) using strict TDD RED → GREEN → REFACTOR cycle.

## Acceptance Criteria Met ✓

All 5 acceptance criteria met:
- ✓ 5 tests pass in test_module_auto_schedule.py

## What Was Done

### Phase 1: RED (Failing Tests)
Created `tests/unit/test_module_auto_schedule.py` with 5 test cases:
1. `test_scheduled_task_auto_enqueued` — Task with `scheduled_after <= today` → auto-enqueued
2. `test_future_task_not_enqueued` — Task with `scheduled_after` in future → skipped
3. `test_blocked_dependency_not_enqueued` — Task with unfinished `depends_on` → blocked
4. `test_already_enqueued_task_skipped` — Task already in inbox → idempotent skip
5. `test_done_task_not_enqueued` — Task with `status=done` → skipped

All tests initially failed (module not implemented).

### Phase 2: GREEN (Minimal Implementation)
Created implementation files:
- **`src/superharness/modules/actions/auto_schedule.py`** — Core logic:
  - `check_scheduled_tasks()` — Scans contract for tasks ready to delegate
  - Only processes tasks with `scheduled_after` field
  - Checks date readiness (`scheduled_after <= today`)
  - Checks dependencies (`depends_on` task must be `status=done`)
  - Prevents duplicate enqueues (idempotent)
  - Writes inbox.yaml atomically

- **`src/superharness/module_templates/auto-schedule.yaml`** — Module template:
  - Enabled by default: `false` (opt-in)
  - Hook: `on_watcher_tick` → `check_scheduled_tasks`
  - Settings: `check_depends_on: true`, `auto_target: claude-code`

- **Registered action** in `src/superharness/modules/__init__.py`:
  - Added `check_scheduled_tasks` to action registry

All 5 tests passing.

### Phase 3: REFACTOR (Wiring + Integration)
- **Wired into watcher** — `src/superharness/commands/inbox_watch.py`:
  - Added `run_hooks("on_watcher_tick", ...)` call in `_run_scripts()` after heartbeat write
  - Runs on every watcher poll cycle (launchd or foreground mode)
  - Wrapped in try/except to prevent module failures from blocking watcher

- **Already exists in runner** — `on_watcher_tick` was already in `LIFECYCLE_EVENTS` list

## Files Changed

### Created
- `tests/unit/test_module_auto_schedule.py` — 5 test cases (222 lines)
- `src/superharness/modules/actions/auto_schedule.py` — Action implementation (145 lines)
- `src/superharness/module_templates/auto-schedule.yaml` — Module template (10 lines)

### Modified
- `src/superharness/modules/__init__.py` — Registered `check_scheduled_tasks` action
- `src/superharness/commands/inbox_watch.py` — Added `on_watcher_tick` hook call
- `.superharness/contract.yaml` — Marked `mod.4-autoschedule` as `status: done`, added `test_types: [unit]`
- `.superharness/ledger.md` — Appended completion entry

## Test Evidence

```bash
$ pytest tests/unit/test_module_auto_schedule.py -v
============================= test session starts ==============================
tests/unit/test_module_auto_schedule.py::TestAutoScheduleModule::test_scheduled_task_auto_enqueued PASSED [ 20%]
tests/unit/test_module_auto_schedule.py::TestAutoScheduleModule::test_future_task_not_enqueued PASSED [ 40%]
tests/unit/test_module_auto_schedule.py::TestAutoScheduleModule::test_blocked_dependency_not_enqueued PASSED [ 60%]
tests/unit/test_module_auto_schedule.py::TestAutoScheduleModule::test_already_enqueued_task_skipped PASSED [ 80%]
tests/unit/test_module_auto_schedule.py::TestAutoScheduleModule::test_done_task_not_enqueued PASSED [100%]
============================== 5 passed in 0.07s ==============================
```

All module tests still passing (33/33):
```bash
$ pytest tests/unit/test_module*.py -v
============================== 33 passed in 0.11s ==============================
```

## Usage

To enable auto-scheduling for a project:

```bash
# Enable the module
shux enhance enable auto-schedule

# Add scheduled_after to tasks in contract.yaml
tasks:
- id: task.future
  title: Future work
  status: todo
  scheduled_after: 2026-04-01
  project_path: /path/to/project
```

When watcher ticks and `2026-04-01` arrives, task will be auto-enqueued to inbox.

## Next Steps

None. Task complete. Ready for next module in queue.

---

**Handoff complete.**
