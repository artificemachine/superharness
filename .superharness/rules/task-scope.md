---
id: task-scope
title: Task scope and decomposition
status: active
since: v1.0
---

If a task has >3 acceptance criteria or touches >4 files, decompose into subtasks.

Use `shux delegate <id> --orchestrate` for auto-decomposition.

Each subtask should be completable in <10 min of agent time.

Before starting work:
  - `shux recall --project . "KEYWORDS"` — search past handoffs
  - `shux contract` — check current tasks
  - `shux context <id>` — full context for a specific task

Before closing a task:
  - Run end-to-end verification (not unit tests alone)
  - `shux verify --id <id> --method "<how>" --result pass`
  - `shux close <id>` rejects unverified tasks
