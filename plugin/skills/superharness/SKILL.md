---
name: superharness
description: >
  Multi-agent task coordination via the shux CLI. Use when the user asks about task
  status, wants to see the task contract, wants to delegate/dispatch work to an agent,
  wants to check tool health, or wants to close a completed task. Routes to
  /shux-contract (show tasks + next-task suggestion), /shux-status (health dashboard),
  /shux-delegate (create + enqueue a task), /shux-doctor (prerequisite check), and
  /shux-close (close a report_ready/review_passed task). For anything else, /shux
  <args> runs the CLI directly.
---

## When to use which command

| User intent | Command |
|---|---|
| "what tasks are open", "show contract" | `/shux-contract` |
| "is the watcher running", "health check", "any issues" | `/shux-status` |
| "dispatch this task", "delegate <id>" | `/shux-delegate <id>` |
| "check prerequisites", "is superharness set up right" | `/shux-doctor` |
| "close task <id>", "mark done" | `/shux-close <id>` (only if status is report_ready or review_passed) |
| anything else shux-related | `/shux <subcommand> [args]` |

## Rules

- After `/shux-contract`, ask which task to enqueue — never enqueue without being asked.
- Before `/shux-close`, confirm the task's status is `report_ready` or `review_passed`.
- When a problem surfaces (task stuck, discussion stalled), state what you observe, check whether auto-mode (watcher/reconciler) would resolve it, and only then propose a `/shux-*` action.
