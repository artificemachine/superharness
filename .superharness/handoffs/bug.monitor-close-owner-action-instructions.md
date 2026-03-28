Task: Monitor close button executes close with the owner actor (bug.monitor-close-owner-action)

## Acceptance Criteria
- Closing a review_passed/done task from the monitor UI runs `shux close` with `--actor owner` so codex-cli-owned tasks are allowed to close.
- The close action still requires verification and respects the existing lifecycle gate.
- Monitor close button behavior remains idempotent for tasks already being closed or for tasks owned by other agents.

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done