# superharness Roadmap

## Current State (2026-03-08)

superharness is currently **v0.6**.

What is already real and executable:
- Claude Code plugin + hooks (`session-start`, `scope-guard`, `branch-guard`, `ledger-append`)
- Cross-agent protocol files (`contract.yaml`, `handoffs/`, `ledger.md`, `failures.yaml`, `decisions.yaml`)
- Delegation inbox system (`enqueue`, `dispatch`, `watch`, `normalize`, launchd installer/ensurer)
- Shell entrypoint guard with allowlist drift detection in CI
- Project bootstrap (`init-project.sh`) generating `CLAUDE.md` + `AGENTS.md`

## v0.7 Goals — Reliability And Adoption

1. **Second project validation**
- Run one additional real project with the inbox + handoff lifecycle.
- Evidence required: committed contract, handoffs, and ledger entries.

2. **Protocol hygiene enforcement**
- Enforce done-task evidence (`handoff` + `ledger`) in routine checks.
- Enforce promotion discipline for reusable decisions/failures.

3. **Dispatch semantics clarity**
- Keep status transitions unambiguous (`pending -> launched -> running -> done|failed`).
- Keep docs, scripts, and tests aligned on meaning.

4. **Docs split by audience**
- README stays execution-first (install/init/use).
- Architecture and philosophy live in dedicated docs.

5. **CI parity for all entrypoints**
- Ensure new executable scripts automatically inherit validation and smoke coverage.

## v0.8 Goals — Operational Hardening

1. Add lightweight metrics for queue health (age, retries, failures).
2. Improve launchd operability docs and troubleshooting flows.
3. Add optional strict CI mode for protocol hygiene checks against fixture projects.
4. Expand failure-memory promotion workflow.

## v1.0 Definition — "It Works In Production"

superharness is 1.0 when all are true:
1. It is actively used across at least two real projects.
2. Cross-agent protocol is consistently followed (tasks, handoffs, ledger).
3. Failure/decision memory is populated and reused, not just scaffolded.
4. Dispatch + watcher workflows run without manual babysitting.
5. Maintenance remains bounded (reactive improvements, no architecture churn).
