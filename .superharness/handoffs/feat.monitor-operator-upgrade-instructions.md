Task: Monitor operator upgrade: board view, health, budget, review queue (feat.monitor-operator-upgrade)

## Acceptance Criteria
- Monitor UI adds a clearer operator-focused board view grouped by workflow state
- Review queue, per-agent health, and budget/usage signals are visible from the existing lightweight monitor
- Task actions remain correct across todo, plan, review, verify, and close states
- Live log affordances improve without requiring a frontend stack rewrite
- New monitor affordances are covered by endpoint or render regression tests

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done