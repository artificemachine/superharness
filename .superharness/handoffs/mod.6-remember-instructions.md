Task: Remember module (context refresh) (mod.6-remember)

## Plan (from docs/)
## Iteration 6: Remember Module

### RED

```python
# tests/unit/test_module_remember.py

class TestRememberModule:
    def test_on_continue_refreshes_context(self, tmp_path):
        """Continue fires → reads CLAUDE.md, last handoff, contract."""

    def test_on_continue_no_handoff_still_works(self, tmp_path):
        """No previous handoff → just reads CLAUDE.md."""
```

### GREEN

```python
# src/superharness/module_templates/remember.yaml
name: remember
description: "Auto-refresh context from CLAUDE.md and last handoff on continue"
enabled: false
hooks:
  on_continue:
    action: refresh_context
```

## Acceptance Criteria
- 2 tests pass in test_module_remember.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done