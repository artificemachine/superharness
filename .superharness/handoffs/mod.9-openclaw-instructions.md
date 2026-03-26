Task: OpenClaw module (NemoClaw delegation) (mod.9-openclaw)

## Plan (from docs/)
## Iteration 8: OpenClaw Module

### RED

```python
# tests/unit/test_module_openclaw.py

class TestOpenClawModule:
    def test_on_delegate_routes_to_openclaw(self, tmp_path):
        """Delegate with --to openclaw → sends task via MCP."""

    def test_openclaw_not_available_fails(self, tmp_path):
        """No NemoClaw MCP → clear error with setup instructions."""
```

### GREEN

```python
# src/superharness/module_templates/openclaw.yaml
name: openclaw
description: "Delegate tasks to NemoClaw sandboxed agents"
enabled: false
detect:
  optional_mcp: nemoclaw
hooks:
  on_delegate:
    action: openclaw_send_task
    condition: "target == 'openclaw'"
```

## Acceptance Criteria
- 2 tests pass in test_module_openclaw.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done