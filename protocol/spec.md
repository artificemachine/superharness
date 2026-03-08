# superharness Protocol Spec

This is the canonical contract for cross-agent execution in a project.

## Files

All runtime state lives in `PROJECT/.superharness/`:
- `contract.yaml`: active contract and task list
- `handoffs/*.yaml`: agent-to-agent handoff records
- `ledger.md`: append-only execution log
- `decisions.yaml`: promoted reusable decisions
- `failures.yaml`: promoted reusable failures
- `inbox.yaml`: delegation queue

## Task Lifecycle

Contract task statuses:
- `todo`
- `in_progress`
- `done`

Inbox item statuses:
- `pending`
- `launched`
- `running`
- `done`
- `failed`
- `stale`

Dispatch only claims `pending` items.

## Delegation Flow

1. Operator enqueues work with `inbox-enqueue.sh` (or `cli/enqueue.sh`).
2. Dispatcher claims by priority (`1` highest) and marks item `launched`.
3. Agent marks item `running` when execution starts.
4. Agent sets final status `done` or `failed`.
5. Cleaner may mark old launched items `stale` and archive rows.

## Required End-of-Task Updates

When an agent completes a task:
- update `contract.yaml` task status
- append one line to `ledger.md`
- create or update handoff in `handoffs/`

## Owner-Aware Delegation

When showing contract status (`contract today` behavior):
- if a remaining task owner is the other agent, ask for delegation:
  - `I detected owner is codex-cli. Do you want to delegate <task_id> now?`
  - `I detected owner is claude-code. Do you want to delegate <task_id> now?`

## Path Guard

Each contract task should include:
- `project_path: "/absolute/path/to/project"`

Queueing should validate the current project path against task `project_path`.
