# Handoff: feat.dashboard-auto-restart-on-upgrade

**Task:** Dashboard auto-restart when installed version changes
**Status:** done
**Completed:** 2026-05-07T14:38:33Z
**Agent:** claude-code

## Acceptance Criteria (all met)

- [x] Daemon/monitor detects version mismatch between running process and installed package at each heartbeat
- [x] Auto-restarts the dashboard process when mismatch detected
- [x] Logs the restart with old and new version to ledger

## Implementation Summary

All three acceptance criteria are implemented in `src/superharness/scripts/dashboard-ui.py`:

- **`_get_installed_version()`** (line 3025): Returns `importlib.metadata.version("superharness")` or `"unknown"` on error.
- **`_append_ledger()`** (line 3034): Appends a line to `.superharness/ledger.md`, creating the file if absent. Never raises.
- **`autohealth_loop()`** (line 3055): Watchdog loop that:
  1. Captures `running_version` before the loop starts.
  2. On each tick calls `_get_installed_version()`.
  3. On mismatch: appends `"- <ts> — autohealth — auto-restart — version mismatch: <old> -> <new>"` to ledger, terminates and restarts the dashboard subprocess, updates `running_version`.
  4. Also restarts if the process exits or health check fails.

## Tests

File: `tests/unit/test_dashboard_autohealth_version.py`

- `test_get_installed_version_returns_string` — happy path
- `test_get_installed_version_unknown_on_missing_package` — error path returns "unknown"
- `test_append_ledger_writes_line` — appends to existing ledger
- `test_append_ledger_creates_ledger_if_missing` — creates ledger when absent
- `test_autohealth_restarts_on_version_mismatch` — subprocess terminated and restarted
- `test_autohealth_no_restart_when_version_unchanged` — no extra Popen calls
- `test_autohealth_version_mismatch_logged_to_ledger` — old+new versions appear in ledger
- `test_append_ledger_helper_format` — ledger line contains required fields

**Result: 8/8 passed**

## No Code Changes Required

The implementation was already complete on the branch. This session verified all tests pass and recorded the outcome in contract and ledger.
