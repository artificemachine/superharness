Task: Heartbeat contract v1 (runtime-agnostic agent status) (feat.heartbeat-contract-v1)

## Acceptance Criteria
- Define a stable file-based heartbeat schema for native and external agent runtimes
- Watcher and monitor consume heartbeat/status data without hardcoding runtime-specific assumptions
- Heartbeats can report active task, liveness, next wake time, and budget or usage metadata
- Stale-heartbeat detection and recovery paths behave consistently across runtimes
- Existing watcher health/status flows remain compatible with current native agents

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done