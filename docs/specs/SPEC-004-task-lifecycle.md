# SPEC-004: Task lifecycle state machine and gates

Status: draft
Last reviewed: 2026-09-24
Affected paths: src/superharness/engine/next_action.py, src/superharness/engine/lifecycle_rules.py

The task lifecycle is the transition table in `engine/next_action.py` and the
time-based rules in `engine/lifecycle_rules.py`. Every writer (CLI, MCP, state
writer) validates against that one table; the dashboard reads its column
mapping from the same module.

## Requirements

- [REQ-401] A status change through the CLI or MCP is validated against the transition table, and an illegal transition such as `todo` to `done` is rejected on both surfaces.
- [REQ-402] The state database rejects any status value outside the canonical status set.
- [REQ-403] Deadline enforcement measures an in-progress task's age from when work started, not from when the task was created.

## Scoped Invariants

- [INV-401] For every status, the recommended next status is either none or a member of that status's legal transitions.
- [INV-402] `done` is terminal: it recommends nothing and accepts no transition.

## Known gaps

- The `validate_status_transition` docstring says terminal statuses accept no transitions, but `failed` and `stopped` have legal exits in the table. The code is the behaviour; the docstring is wrong. Owner decision pending.
- An unknown current status accepts any transition (fail open), by design as written in the code.

## Verification & Validation

- REQ-401 -> tests/state_machine/test_status_transitions.py::test_cli_and_mcp_both_reject_done_from_todo
- REQ-402 -> tests/unit/db/test_status_constraint.py::test_invalid_status_is_rejected
- REQ-403 -> tests/unit/test_deadline_in_progress_at.py::test_running_task_not_failed_when_recently_started
- INV-401 -> tests/unit/test_next_action.py::TestNextActionInvariants::test_recommended_is_member_of_legal_or_none
- INV-402 -> tests/unit/test_next_action.py::TestNextActionBasicMapping::test_done_is_terminal
