---
task_id: mod.7-ntfy
title: ntfy notification module
status: done
from: claude-code
to: owner
date: 2026-03-20T16:20:58Z
---

# Task: mod.7-ntfy — ntfy notification module

## Status: ✅ DONE

All acceptance criteria met:
- ✅ 3 tests pass in test_module_ntfy.py

## What Was Done

### TDD Approach (RED → GREEN → REFACTOR)

**RED Phase — Failing Tests:**
Created `tests/unit/test_module_ntfy.py` with 3 test cases:
1. `test_on_close_sends_notification` — validates ntfy push on task close
2. `test_on_verify_fail_sends_alert` — validates high-priority alert on verification failure
3. `test_ntfy_unavailable_skips` — validates graceful skip when server unreachable

**GREEN Phase — Minimal Implementation:**
Created `src/superharness/modules/actions/ntfy.py`:
- `ntfy_send(context, settings)` — sends notifications via HTTP POST to ntfy server
- Handles environment variable configuration via `NTFY_TOPIC`
- Supports configurable priority (default, high)
- Gracefully handles missing requests library
- Gracefully handles connection errors (server unreachable)
- Returns structured result dict with success/failure status

Created `src/superharness/module_templates/ntfy.yaml`:
- Module template with `on_close` and `on_verify` hooks
- Auto-detection via `NTFY_TOPIC` environment variable
- Configurable ntfy server URL (defaults to https://ntfy.sh)
- Priority configuration per hook

**REFACTOR Phase:**
- No refactoring needed — implementation is minimal and clean

## Test Results

```
pytest tests/unit/test_module_ntfy.py -v
```

**All tests pass:**
- test_on_close_sends_notification PASSED
- test_on_verify_fail_sends_alert PASSED
- test_ntfy_unavailable_skips PASSED

**Full module test suite:** 42 tests pass (including 3 new ntfy tests)

## Files Created/Modified

**Created:**
- `tests/unit/test_module_ntfy.py` — 3 test cases
- `src/superharness/modules/actions/ntfy.py` — ntfy action implementation
- `src/superharness/module_templates/ntfy.yaml` — module template

**Modified:**
- `.superharness/contract.yaml` — task status: todo → done, added test_types: [unit]
- `.superharness/ledger.md` — appended completion entry

## Usage

Users can enable the ntfy module with:

```bash
export NTFY_TOPIC=my-superharness-tasks
shux enhance enable ntfy
```

The module will then:
- Send a notification on task close (priority: default)
- Send a high-priority alert on verify failure (priority: high)

## Security Note

Implementation follows strict security rules:
- No hardcoded secrets, tokens, or URLs
- All sensitive configuration comes from environment variables
- Template uses placeholder values only (`NTFY_TOPIC` as env var name, not value)
- Graceful degradation when dependencies or config missing

## Next Steps

No follow-up needed. Task complete.

## Dependencies

- Optional: `requests` library (gracefully skips if not installed)
- Optional: `NTFY_TOPIC` environment variable (skips if not set)

---

**Handoff complete.** Task mod.7-ntfy delivered with all acceptance criteria met.
