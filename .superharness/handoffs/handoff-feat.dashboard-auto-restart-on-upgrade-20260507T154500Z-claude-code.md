# Handoff: feat.dashboard-auto-restart-on-upgrade

**Date:** 2026-05-07T15:45:00Z
**Agent:** claude-code
**Task:** feat.dashboard-auto-restart-on-upgrade
**Status:** done

## Summary

Verified all 3 acceptance criteria — implementation was already complete in this worktree:

1. **Version detection at each heartbeat** — `_get_installed_version()` (dashboard-ui.py:3025) uses `importlib.metadata.version("superharness")` and is called at the top of every `autohealth_loop` iteration after `time.sleep(interval)`.

2. **Auto-restart on mismatch** — `autohealth_loop` (dashboard-ui.py:3109-3125) compares `installed_version != running_version`; on mismatch calls `_restart_proc(proc)`, updates `running_version`, and continues the loop.

3. **Ledger logging** — `_append_ledger()` (dashboard-ui.py:3034) writes a line with UTC timestamp, "auto-restart", "version mismatch", old version `->` new version before triggering restart.

## Files

- `src/superharness/scripts/dashboard-ui.py` — `_get_installed_version`, `_append_ledger`, `autohealth_loop` (lines 3025-3131)
- `tests/unit/test_dashboard_autohealth_version.py` — 8 unit tests covering all helpers and loop behavior

## Test Results

```
8/8 passed — tests/unit/test_dashboard_autohealth_version.py
```

## Notes

This session performed a verification run: read contract, read source, ran tests, confirmed all criteria green. No code changes were needed.
