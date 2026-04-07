Task: Watcher auto-gc — periodic inbox reconciliation in watcher loop (feat.watcher-auto-gc)

## Acceptance Criteria
- Watcher runs inbox gc reconcile every N heartbeat cycles (configurable)
- Auto-marks stale inbox items done when contract task is done
- Logs reconciled items to ledger
- Configurable via profile.yaml gc_interval_cycles

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done