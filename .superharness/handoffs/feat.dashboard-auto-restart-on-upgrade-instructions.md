Task: Dashboard auto-restart when installed version changes (feat.dashboard-auto-restart-on-upgrade)

## Acceptance Criteria
- Daemon/monitor detects version mismatch between running process and installed package at each heartbeat
- Auto-restarts the dashboard process when mismatch detected
- Logs the restart with old and new version to ledger

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done