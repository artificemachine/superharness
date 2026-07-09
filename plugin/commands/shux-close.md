---
description: Close a superharness task (report_ready or review_passed only)
argument-hint: "<task-id> [--force] [--cancel-remaining --cancel-reason \"...\"]"
---

Closing a task is terminal. Before running, confirm via `shux contract` that <task-id>'s status is `report_ready` or `review_passed` (skip this check only if the user already stated the status). Run `shux close $ARGUMENTS` via Bash and report the result verbatim.
