Task: Ship step in task lifecycle — auto-commit after task approval (BLOCKED: review pipeline bypass risk) (feat.task-lifecycle-ship)

## Plan (from docs/)
## Iteration 1: Module Runner (Lifecycle Hooks)

### RED

```python
# tests/unit/test_module_runner.py

class TestModuleRunner:
    def test_on_close_fires_for_enabled_module(self, tmp_path):
        """Module with on_close hook → action called when close runs."""

    def test_on_close_skips_disabled_module(self, tmp_path):
        """Disabled module → on_close not called."""

    def test_on_verify_fires(self, tmp_path):
        """Module with on_verify hook → action called when verify runs."""

    def test_on_continue_fires(self, tmp_path):
        """Module with on_continue hook → action called when continue runs."""

    def test_module_failure_does_not_block_close(self, tmp_path):
        """If module action fails → warning logged, close still succeeds."""

    def test_multiple_modules_all_fire(self, tmp_path):
        """Two enabled modules with on_close → both fire."""

    def test_hook_receives_context(self, tmp_path):
        """Hook action receives task_id, summary, project_dir, actor."""
```

### GREEN

```python
# src/superharness/modules/runner.py

LIFECYCLE_EVENTS = ["on_close", "on_verify", "on_continue", "on_delegate", "on_watcher_tick"]

def run_hooks(event: str, context: dict, project_dir: Path) -> list[dict]:
    """Load modules, fire all hooks for the given lifecycle event."""
```

### REFACTOR

- Wire into `close.py`: after close logic, call `run_hooks("on_close", ...)`
- Wire into `verify.py`: after verify logic, call `run_hooks("on_verify", ...)`
- Wire into `continue` command: call `run_hooks("on_continue", ...)`

## Acceptance Criteria
- Design doc addressing: review pipeline bypass, mixed commits, concurrent agent conflicts, hook failures
- Requires feat.dispatch-auto-stash shipped first as interim solution
- Must not bypass security scan, tests, or doc sync

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done