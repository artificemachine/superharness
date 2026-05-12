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

Every task follows this mandatory phase sequence:

```
todo → plan_proposed → plan_approved → in_progress → report_ready
                                                          │
                                              ┌───────────┴──────────┐
                                         (optional)              (skip review)
                                       review_requested               │
                                              │                       │
                                    ┌─────────┴─────────┐            │
                               review_failed        review_passed     │
                                    │                    └────────────┘
                                    │                         ↓
                              (loop back)                    done
                           plan_proposed
```

### Phase Definitions

Contract task statuses:
- `todo` — task created, not yet started
- `plan_proposed` — agent has written a plan handoff; **awaits operator approval before any implementation**
- `plan_approved` — operator approved the plan; agent may proceed to implement
- `in_progress` — implementation underway
- `report_ready` — implementation complete; agent has written a report handoff; **awaits operator review**
- `review_requested` — operator has asked for an Opus quality review before closing
- `review_passed` — Opus review passed; task is ready to close
- `review_failed` — Opus review identified issues; task loops back to `plan_proposed`
- `done` — task closed (after `shux close`)
- `failed` — task ran but did not complete (error, deadline exceeded); always accompanied by `stopped_reason` and `stopped_at`
- `stopped` — operator manually halted the task; always accompanied by `stopped_reason` and `stopped_at`

### Agent Rules

1. **Plan first (TDD required).** Before any implementation, write a plan handoff that includes a `tdd` block (red/green/refactor). Set status to `plan_proposed`. Stop and wait.
2. **Never implement without approval.** Only proceed when status is `plan_approved`.
3. **Report always.** After implementation, write a report handoff and set status to `report_ready`. Stop and wait.
4. **Loop on review failure.** If `review_failed`, treat it as a new `plan_proposed` cycle — read the review findings, revise the plan, set status back to `plan_proposed`.
5. **Never self-close.** Only the operator runs `shux close` to move a task to `done`.

### Handoff Schema for Each Phase

```yaml
# plan handoff
task: <task-id>
phase: plan
status: plan_proposed
from: claude-code
to: owner
date: <ISO timestamp>
plan: |
  <what will be done, scope, approach>
tdd:
  red: |
    <tests to write first — what failing tests define "done" for this task>
  green: |
    <minimal implementation to make those tests pass>
  refactor: |
    <cleanup and quality improvements after green — no new behaviour>
risks: |
  <known risks or open questions>

# report handoff
task: <task-id>
phase: report
status: report_ready
from: claude-code
to: owner
date: <ISO timestamp>
outcome: |
  <what was done, results>
context: |
  <what the next session needs to know to continue or verify this work>
  Include: key constraints discovered, why decisions were made, what to watch for.
outcomes:
  - <bullet 1>
  - <bullet 2>
tests_passed: true   # or false
```

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
- After summarising the task list, do **not** offer to run tests or start implementation.
- Ask to enqueue the next task: `"Want me to enqueue <task_id>? (shux delegate <task_id>)"`
- If a task owner is the other agent, ask for delegation:
  - `I detected owner is codex-cli. Do you want to delegate <task_id> now?`
  - `I detected owner is claude-code. Do you want to delegate <task_id> now?`
- Wait for operator confirmation before dispatching or executing any task.

## Path Guard

Each contract task should include:
- `project_path: "/absolute/path/to/project"`

Queueing should validate the current project path against task `project_path`.

## Profile Keys

`.superharness/profile.yaml` configures per-project agent behavior. All keys are optional; defaults are shown.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_model` | string | `""` | Override model tier for delegate (e.g. `"mini"`, `"standard"`) |
| `default_effort` | string | `""` | Override effort level for delegate |
| `autonomy` | string | `"approval-gated"` | Autonomy mode: `approval-gated`, `auto`, etc. |
| `auto_dispatch` | bool | `true` | Enable/disable auto-dispatch for this project |
| `round_tasks_skip_plan_approval` | bool | `true` | Whether `round-*` discussion task IDs bypass the plan-only gate in auto-dispatch |

### `round_tasks_skip_plan_approval`

Discussion round tasks (IDs matching `*round-*`) are generated by `shux discuss` and represent a single pass in a multi-agent dialogue. They have no implementation phase and no planning phase — dispatching them with `plan_only=True` would advance their status to `plan_approved`, which is outside the discussion workflow's allowed dispatch set. This causes a permanent lifecycle gate block on every subsequent dispatch attempt.

By default (`true`), auto-dispatch always sets `plan_only=False` for round-* tasks, allowing them to execute immediately. Set to `false` if you want operator approval before each discussion round fires — useful for high-sensitivity projects or audited pipelines.

```yaml
# .superharness/profile.yaml
round_tasks_skip_plan_approval: false  # require operator approval before each discussion round
```
