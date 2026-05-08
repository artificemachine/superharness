# Handoff: feat.dashboard-auto-restart-on-upgrade
**Phase:** report  
**From:** claude-code  
**To:** owner  
**Date:** 2026-05-07  
**Status:** done  
**Tests:** 8/8 passed

## Outcome

All 3 acceptance criteria are met. The implementation was already present in `src/superharness/scripts/dashboard-ui.py`:

1. **Version mismatch detection at each heartbeat** — `autohealth_loop` calls `_get_installed_version()` on every iteration of its heartbeat sleep cycle.

2. **Auto-restart on mismatch** — When `installed_version != running_version`, `_restart_proc()` is called to terminate the old process and start a fresh dashboard subprocess.

3. **Ledger logging with old and new version** — `_append_ledger()` writes a timestamped line to `.superharness/ledger.md` in the format:  
   `- <ISO timestamp> — autohealth — auto-restart — version mismatch: <old> -> <new>`

## Key Files

- Implementation: `src/superharness/scripts/dashboard-ui.py` (functions: `autohealth_loop`, `_get_installed_version`, `_append_ledger`, `_restart_proc`)
- Tests: `tests/unit/test_dashboard_autohealth_version.py` (8 tests, all green)

## Test Results

```
8 passed in 5.27s
```

No regressions in the broader unit suite.
