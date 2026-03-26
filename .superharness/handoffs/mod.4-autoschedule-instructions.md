Task: Auto-schedule module (watcher tick) (mod.4-autoschedule)

## Plan (from docs/)
## Iteration 10: Auto-Schedule Module

### RED

```python
# tests/unit/test_module_auto_schedule.py

class TestAutoScheduleModule:
    def test_scheduled_task_auto_enqueued(self, tmp_path):
        """Task with scheduled_after <= today → auto-enqueued to inbox."""

    def test_future_task_not_enqueued(self, tmp_path):
        """Task with scheduled_after in future → not enqueued."""

    def test_blocked_dependency_not_enqueued(self, tmp_path):
        """Task with unfinished depends_on → not enqueued."""

    def test_already_enqueued_task_skipped(self, tmp_path):
        """Task already in inbox → not enqueued again (idempotent)."""

    def test_done_task_not_enqueued(self, tmp_path):
        """Task with status=done → skipped."""
```

### GREEN

```python
# src/superharness/module_templates/auto-schedule.yaml
name: auto-schedule
description: "Auto-delegate tasks when scheduled_after date arrives and dependencies are met"
enabled: false
hooks:
  on_watcher_tick:
    action: check_scheduled_tasks
settings:
  check_depends_on: true
  auto_target: claude-code    # default delegation target
```

```python
# src/superharness/modules/actions/auto_schedule.py

def check_scheduled_tasks(context: dict, settings: dict) -> list[str]:
    """Scan contract for tasks ready to delegate. Returns list of enqueued task IDs."""
    # For each task where:
    #   - status == "todo"
    #   - scheduled_after <= today (or not set)
    #   - depends_on all done (or not set)
    #   - not already in inbox
    # → auto-enqueue to inbox
```

### REFACTOR

- Add `on_watcher_tick` to LIFECYCLE_EVENTS in runner.py
- Wire into inbox_watch.py: after each poll cycle, call `run_hooks("on_watcher_tick", ...)`

## Acceptance Criteria
- 5 tests pass in test_module_auto_schedule.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done