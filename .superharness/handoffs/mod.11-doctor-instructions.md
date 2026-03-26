Task: Doctor module health section (mod.11-doctor)

## Plan (from docs/)
## Iteration 11: `shux doctor` Module Health

### RED

```python
# tests/unit/test_doctor_modules.py

class TestDoctorModules:
    def test_doctor_shows_enabled_modules(self, tmp_path):
        """Doctor lists enabled modules with status."""

    def test_doctor_shows_missing_dependencies(self, tmp_path):
        """Module enabled but dependency missing → WARN."""

    def test_doctor_suggests_enhance(self, tmp_path):
        """No modules enabled → INFO with 'shux enhance' suggestion."""
```

### GREEN

Add module health section to existing `doctor.py`:

```
PASS modules: 3 enabled (obsidian, security, ntfy)
WARN module:telegram — TELEGRAM_BOT_TOKEN not set
INFO modules: 10 more available — run 'shux enhance' to browse
```

## Acceptance Criteria
- 3 tests pass in test_doctor_modules.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done