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
- `failed` — task ran but did not complete (error, deadline exceeded); always accompanied by `stopped_reason` and `stopped_at`
- `stopped` — operator manually halted the task mid-execution; always accompanied by `stopped_reason` and `stopped_at`

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

## Failure-Memory Promotion

Use per-contract failures for local execution context, then promote reusable learnings:
1. Add temporary, task-scoped failures to `contract.yaml` `failures`.
2. Promote cross-task reusable failures into `failures.yaml` `failures`.
3. In strict hygiene mode, non-empty contract failures require non-empty `failures.yaml`.

## Task Deadlines and Auto-Reassignment

Tasks in `contract.yaml` may define an optional `deadline_minutes` field:

```yaml
tasks:
  - id: my-task
    title: "..."
    status: todo
    owner: claude-code
    deadline_minutes: 30       # optional — omit for no deadline
    project_path: "/path/to/project"
```

On each watcher cycle, `inbox-deadline-check.sh` checks all `launched` items. If a task has `deadline_minutes` set and the elapsed time since `launched_at` exceeds it:

1. The inbox item is marked `failed` with `failed_reason: deadline_exceeded_after_Nm`.
2. A handoff is written to `handoffs/YYYY-MM-DD-deadline-<task>.yaml` documenting the elapsed time and the original owner.
3. The task is re-enqueued for the **other owner** (`claude-code` ↔ `codex-cli`).
4. A ledger entry is appended recording the deadline breach and reassignment.

The new owner's dispatch prompt will reference the deadline handoff and is expected to document why the previous attempt did not finish in time.

## Owner-Aware Delegation

When showing contract status (`contract today` behavior):
- if a remaining task owner is the other agent, ask for delegation:
  - `I detected owner is codex-cli. Do you want to delegate <task_id> now?`
  - `I detected owner is claude-code. Do you want to delegate <task_id> now?`

## Path Guard

Each contract task should include:
- `project_path: "/absolute/path/to/project"`

Queueing should validate the current project path against task `project_path`.
