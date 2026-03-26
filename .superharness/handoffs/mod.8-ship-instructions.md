Task: Ship module (auto-commit on close) (mod.8-ship)

## Plan (from docs/)
## Iteration 5: Ship Module

### RED

```python
# tests/unit/test_module_ship.py

class TestShipModule:
    def test_on_close_runs_ship(self, tmp_path):
        """Close fires → git add, commit, push."""

    def test_on_close_no_changes_skips(self, tmp_path):
        """No uncommitted changes → ship skipped."""

    def test_on_close_ship_failure_warns(self, tmp_path):
        """Ship fails → warning, close still succeeds."""
```

### GREEN

```python
# src/superharness/module_templates/ship.yaml
name: ship
description: "Auto-commit and push on task close"
enabled: false
detect:
  bin: git
hooks:
  on_close:
    action: git_ship
settings:
  auto_push: false    # default: commit only, ask before push
```

## Acceptance Criteria
- 3 tests pass in test_module_ship.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done