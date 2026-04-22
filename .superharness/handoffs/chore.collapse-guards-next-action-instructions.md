Task: Collapse delegate/enqueue/task-status guard tables into engine/next_action.py (chore.collapse-guards-next-action)

## Acceptance Criteria
- Single source of truth: delegate + enqueue + task-status read legal transitions from the same module that adapter-payload next_action uses
- No behaviour change: all existing reject/accept cases still behave identically (tests stay green)
- Remove duplicate mapping tables from delegate._allowed_statuses_for_workflow and inbox_enqueue

## Prior Attempt (FAILED)
Status: failed
No detailed report from previous attempt.

Fix the issues above before proceeding.

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done