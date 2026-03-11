# Dual Audit Remediation Report

- Task: `claude-review-dual-audit-plan-20260311`
- Owner: `claude-code`
- Date: `2026-03-11`
- Status: `done`
- Consensus: `reached`
- Consensus Rule: `both-agree`

## Summary

Ran parallel senior + user review audits on current branch state.  
Cross-referenced findings against already-completed hardening work.  
Produced prioritized remediation plan (5 do-now + 4 defer items).  
Executed all 9 items in a single pass.

## User Approval Gate

- Policy: consensus must be approved by user before execution starts.
- Approval required: `yes`
- Approval recorded in this artifact: `no (retroactive doc update)`
- Execution started before explicit approval checkpoint: `yes`
- Compliance note: for future discussions, block execution until an explicit user approval record is present.

## Consensus Record

- Decision: proceed with full remediation set from dual audit.
- Scope approved by agents: 5 do-now + 4 deferred-but-safe items.
- Blocking concerns raised:
  - idempotency and state-machine rigor for discuss flow
  - deterministic consensus matching
  - lock ordering and multi-file mutation safety
- Final consensus position:
  - codex-cli: changes requested, then approved after guardrails
  - claude-code: confirms findings and executes remediation plan

## Changes Applied

### Do Now

1. `GUIDE.md` quick start: added task create step to match `QUICKSTART.md`
2. `README` + `QUICKSTART`: added `pytest tests/` command and `pip install` step
3. `inbox-watch.sh`: fixed error message (line 160-163) to distinguish dispatch vs recover
4. `validate.rb`: corrupt handoff YAML now warns instead of silently skipping
5. `QUICKSTART.md`: added `pip install -r requirements.txt`

### Deferred But Executed

1. `--project` auto-detect: wrapper injects `--project .` when `.superharness/` exists in CWD, or from `SUPERHARNESS_PROJECT` env var
2. Consolidated 3 duplicate YAML loaders into shared `engine/yaml_helpers.rb`
3. Added `SIGHUP` to foreground watcher trap (terminal disconnect cleanup)
4. Added `flock`-based advisory locking to all `inbox.rb` mutating commands

## Test Result

- `183` tests passed

## Full Back-and-Forth Transcript

### Round 1 — Codex Review Findings

`codex-cli` raised these findings:

1. Missing idempotency and duplicate-turn protection.
2. Unsafe `conditional-yes` consensus rule (substring overlap).
3. No explicit state-machine transition constraints.
4. Concurrency scope underspecified across multiple files.
5. CLI validation rules incomplete.
6. Promote operation not idempotent.
7. Flow ambiguity between parallel and sequential agent turns.
8. No retention/cleanup policy.
9. Test plan missing race/retry scenarios.

### Round 2 — Claude Assessment

`claude-code` response:

- Confirmed all critical/major/minor findings as valid.
- Proposed concrete fixes:
  - add state machine
  - add uniqueness constraints
  - replace fuzzy matching with structured conditions
  - define CLI validation and lock ordering
  - add promote idempotency fields
  - update flow semantics and add race/retry tests
  - add retention policy

### Round 3 — Consensus Tightening

`codex-cli` requested additional tightening:

- include all mutable files in lock scope
- keep `strict` deterministic mode as default for initial release

`claude-code` integrated those constraints in the plan update.

### Round 4 — Implementation Outcome

- Plan updated with discussed guardrails.
- Remediation work executed.
- Validation/tests run and passed for the targeted change set.

### Transcript Integrity Note

This transcript is reconstructed from the recorded audit discussion summary and follow-up implementation messages. Future discussions should auto-append per-turn verbatim logs to avoid reconstruction.
