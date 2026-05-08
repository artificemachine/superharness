# Handoff — feat.dashboard-auto-restart-on-upgrade

**Date:** 2026-05-07  
**Agent:** claude-code  
**Task:** feat.dashboard-auto-restart-on-upgrade  
**Status:** DONE

## What was done

All three acceptance criteria are satisfied:

1. **Version-mismatch detection at each heartbeat** — `autohealth_loop` in `src/superharness/scripts/dashboard-ui.py` calls `_get_installed_version()` every `interval` seconds and compares against the version recorded at startup.

2. **Auto-restart on mismatch** — When versions differ, `_restart_proc()` terminates the current dashboard subprocess and spawns a fresh one. `running_version` is updated to the new installed version so subsequent heartbeats use the correct baseline.

3. **Ledger logging with old and new version** — `_append_ledger()` writes a timestamped line in the format:
   ```
   - <ISO8601> — autohealth — auto-restart — version mismatch: <old> -> <new>
   ```

Helper functions `_get_installed_version()` and `_append_ledger()` were already present and correctly wired.

## Tests

`tests/unit/test_dashboard_autohealth_version.py` — 8 tests, all passing:

- `test_get_installed_version_returns_string`
- `test_get_installed_version_unknown_on_missing_package`
- `test_append_ledger_writes_line`
- `test_append_ledger_creates_ledger_if_missing`
- `test_autohealth_restarts_on_version_mismatch`
- `test_autohealth_no_restart_when_version_unchanged`
- `test_autohealth_version_mismatch_logged_to_ledger`
- `test_append_ledger_helper_format`

## Files touched

- `src/superharness/scripts/dashboard-ui.py` (existing implementation verified, no edits needed)
- `tests/unit/test_dashboard_autohealth_version.py` (existing test file verified, all tests pass)
- `.superharness/ledger.md` (appended completion entry)
- `.superharness/state.sqlite3` (task status updated to `done`)

## Next steps

None — task is complete. The `--autohealth` flag activates the watchdog; use `superharness monitor --autohealth` or equivalent to run the dashboard with version-upgrade auto-restart enabled.
