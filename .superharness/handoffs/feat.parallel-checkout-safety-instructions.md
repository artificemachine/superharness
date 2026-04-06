Task: Parallel checkout safety (atomic per-task claims for multi-agent work) (feat.parallel-checkout-safety)

## Acceptance Criteria
- Independent tasks can be claimed in parallel without double-dispatch or silent overlap
- Task checkout is atomic and covered by concurrency-focused regression tests
- Dependency-aware scheduling prevents blocked tasks from being claimed early
- Stale lock recovery is explicit and does not leave tasks stranded
- Existing single-agent flows remain correct and unchanged for non-parallel users

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done