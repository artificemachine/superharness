# Handoff: feat.dashboard-auto-restart-on-upgrade

**Agent:** claude-code  
**Date:** 2026-05-07  
**Status:** DONE

## Outcomes

All 3 acceptance criteria met:

1. **Version mismatch detection at each heartbeat** — `autohealth_loop` in `dashboard-ui.py` calls `_get_installed_version()` on every loop iteration (each heartbeat interval). Compares `installed_version` against `running_version` captured at process start.

2. **Auto-restart on mismatch** — When `installed_version != running_version`, calls `_restart_proc(proc)` which terminates the old subprocess and spawns a fresh one. `running_version` is updated to `installed_version` after restart.

3. **Logs restart with old/new version to ledger** — Calls `_append_ledger(project_dir, f"- {now_ts} — autohealth — auto-restart — version mismatch: {old} -> {new}\n")` before restarting.

## Tests

File: `tests/unit/test_dashboard_autohealth_version.py`  
All 8 tests pass:
- `test_get_installed_version_returns_string`
- `test_get_installed_version_unknown_on_missing_package`
- `test_append_ledger_writes_line`
- `test_append_ledger_creates_ledger_if_missing`
- `test_autohealth_restarts_on_version_mismatch`
- `test_autohealth_no_restart_when_version_unchanged`
- `test_autohealth_version_mismatch_logged_to_ledger`
- `test_append_ledger_helper_format`

## No code changes needed

The implementation was already complete in `dashboard-ui.py:autohealth_loop` (lines ~3106–3125). This session verified the implementation is correct and all tests pass.
