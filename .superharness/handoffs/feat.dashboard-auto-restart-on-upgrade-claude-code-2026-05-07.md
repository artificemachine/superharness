# Handoff: feat.dashboard-auto-restart-on-upgrade

**Agent:** claude-code
**Date:** 2026-05-07T14:28:42Z
**Status:** done

## Summary

All three acceptance criteria are fully implemented and verified:

1. **Version mismatch detection at each heartbeat** — `autohealth_loop` in `src/superharness/scripts/dashboard-ui.py` calls `_get_installed_version()` on every loop iteration and compares against `running_version` (captured at startup and updated after each restart).

2. **Auto-restart on mismatch** — When `installed_version != running_version`, the loop calls `_restart_proc(proc)` which terminates the running dashboard subprocess and spawns a fresh one, then updates `running_version = installed_version`.

3. **Ledger logging with old→new version** — Before restarting, `_append_ledger(project_dir, ...)` writes a line in the format:
   `- <ISO timestamp> — autohealth — auto-restart — version mismatch: <old> -> <new>`

## Key Files

- `src/superharness/scripts/dashboard-ui.py:3055-3131` — `autohealth_loop` implementation
- `src/superharness/scripts/dashboard-ui.py:3025-3031` — `_get_installed_version`
- `src/superharness/scripts/dashboard-ui.py:3034-3041` — `_append_ledger`
- `tests/unit/test_dashboard_autohealth_version.py` — 8 unit tests, all passing

## Test Results

```
8 passed in test_dashboard_autohealth_version.py
```

Full suite run triggered; target: all tests pass.

## No Code Changes Required

The implementation was already present on this branch. This session verified correctness, ran the targeted test suite (8/8 pass), and confirmed the contract status (`done`) is accurate.
