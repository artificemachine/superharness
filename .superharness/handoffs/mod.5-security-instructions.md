Task: Security module (shipguard gate) (mod.5-security)

## Plan (from docs/)
## Iteration 4: Security Module

### RED

```python
# tests/unit/test_module_security.py

class TestSecurityModule:
    def test_detect_shipguard(self, tmp_path):
        """shipguard binary found → module available."""

    def test_on_verify_runs_shipguard(self, tmp_path):
        """Verify fires → shipguard scan runs, result included in verification."""

    def test_on_verify_critical_blocks(self, tmp_path):
        """Critical finding → verify returns fail."""

    def test_on_verify_no_shipguard_skips(self, tmp_path):
        """shipguard not found → skip silently."""
```

### GREEN

```python
# src/superharness/module_templates/security.yaml
name: security
description: "Auto-run shipguard SAST on verify — blocks on critical findings"
enabled: false
detect:
  any_bin: [shipguard, gitleaks]
hooks:
  on_verify:
    action: security_scan
    block_on: critical
settings:
  severity_threshold: high
```

## Acceptance Criteria
- 4 tests pass in test_module_security.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done