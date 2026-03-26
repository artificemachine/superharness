Task: ntfy notification module (mod.7-ntfy)

## Plan (from docs/)
## Iteration 7: Notification Module (ntfy)

### RED

```python
# tests/unit/test_module_ntfy.py

class TestNtfyModule:
    def test_on_close_sends_notification(self, tmp_path):
        """Close fires → ntfy push with task summary."""

    def test_on_verify_fail_sends_alert(self, tmp_path):
        """Verify fail → high-priority ntfy alert."""

    def test_ntfy_unavailable_skips(self, tmp_path):
        """ntfy server unreachable → skip, no crash."""
```

### GREEN

```python
# src/superharness/module_templates/ntfy.yaml
name: ntfy
description: "Push notifications on task events via ntfy"
enabled: false
detect:
  env: NTFY_TOPIC
hooks:
  on_close:
    action: ntfy_send
    priority: default
  on_verify:
    action: ntfy_send
    priority: high
    only_on: fail
settings:
  url: "https://ntfy.sh"
  topic_env: NTFY_TOPIC
```

## Acceptance Criteria
- 3 tests pass in test_module_ntfy.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done