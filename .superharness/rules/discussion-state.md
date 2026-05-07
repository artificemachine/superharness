---
id: discussion-state
title: Discussion state is SQLite-only
status: active
since: v1.52.12
---

Discussion state lives in the `discussions` and `discussion_rounds` SQLite tables.
No `.superharness/discussions/*/state.yaml` files are created.

The discussion engine (`engine/discussion.py`) reads/writes only SQLite.
All discussion YAML references were removed in v1.52.12.

Use `discussions_dao` for discussion state:
  - get(conn, id) → DiscussionRow
  - get_all(conn, status="active") → list
  - get_rounds(conn, disc_id) → list of DiscussionRoundRow

Dashboard, GC, and dispatch all read from SQLite.
