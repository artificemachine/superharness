Task: Discussion round 1: Architecture Review Hardening Plan: prioritize R1-R5 implementation order, validate ownership split (claude-code: R1+R4 schema/repair, codex-cli: R2+R3+R5 locks/models/docs), agree on pydantic v2 as new dependency, and confirm TDD approach for concurrency-sensitive R2 lock changes (discuss-20260327T143148Z-59289-46645019/round-1)

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done