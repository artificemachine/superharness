# Handoff: feat.dashboard-auto-restart-on-upgrade

**Date:** 2026-05-07T14:30:00Z
**Agent:** claude-code
**Task:** feat.dashboard-auto-restart-on-upgrade
**Status:** done

## Summary

All 3 acceptance criteria were implemented and verified:

1. **Version detection at each heartbeat** — `_get_installed_version()` calls `importlib.metadata.version("superharness")` and is called on every `autohealth_loop` iteration (after each `time.sleep(interval)`).

2. **Auto-restart on mismatch** — `autohealth_loop` in `dashboard-ui.py` (lines 3106-3125) compares `installed_version != running_version` at each tick; on mismatch it calls `_restart_proc(proc)`, updates `running_version`, and continues the loop.

3. **Ledger logging** — `_append_ledger(project_dir, ...)` writes a line with timestamp, "auto-restart", "version mismatch", old version, and new version to `.superharness/ledger.md` before triggering the restart.

## Files Changed

- `src/superharness/scripts/dashboard-ui.py` — `_get_installed_version`, `_append_ledger`, `autohealth_loop` with version-mismatch detection block (lines 3025–3131)
- `tests/unit/test_dashboard_autohealth_version.py` — 8 unit tests covering all helpers and the loop behavior

## Test Results

```
8/8 passed — tests/unit/test_dashboard_autohealth_version.py
```

## Notes

The implementation was already present in the worktree. This session verified correctness, ran tests, and confirmed all acceptance criteria pass.
