# Handoff — feat.dashboard-auto-restart-on-upgrade

**Date:** 2026-05-07T00:00:00Z
**Agent:** claude-code
**Task:** feat.dashboard-auto-restart-on-upgrade

## Outcome: DONE

All three acceptance criteria are satisfied by the existing implementation in
`src/superharness/scripts/dashboard-ui.py`. The feature was already fully
implemented in `autohealth_loop`. This run verified correctness via tests.

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| Daemon/monitor detects version mismatch at each heartbeat | PASS |
| Auto-restarts the dashboard process when mismatch detected | PASS |
| Logs the restart with old and new version to ledger | PASS |

## Key Locations

- **Version check + restart logic:** `dashboard-ui.py:3106-3125` (`autohealth_loop`)
- **`_get_installed_version()`:** `dashboard-ui.py:3025-3031`
- **`_append_ledger()`:** `dashboard-ui.py:3034-3041`
- **Tests:** `tests/unit/test_dashboard_autohealth_version.py` — 8/8 passing

## How It Works

`autohealth_loop` runs as a watchdog under `--autohealth`. Each heartbeat
compares `_get_installed_version()` to the version captured at startup.
On mismatch: ledger entry written (timestamp + old->new version), subprocess
terminated and restarted, `running_version` updated.

## Next Steps

Branch ready for owner review and merge (per CLAUDE.md: no merge without explicit instruction).
