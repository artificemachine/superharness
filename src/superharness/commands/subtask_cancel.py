"""shux subtask-cancel — mark a subtask cancelled with a mandatory reason.

Writes the status change into SQLite (extras_json) and appends a ledger line:
    - <ISO> — <actor> — SUBTASK_CANCEL: <sub_id> (parent=<task_id>) — <reason>

Refuses to cancel a subtask that is already `done` (completed work cannot
be retroactively cancelled). Allows cancellation from pending, in_progress,
or failed.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone


# Statuses that cannot be cancelled (terminal resolved).
_NO_CANCEL_STATUSES = {"done"}


def cancel_subtask(
    project_dir: str,
    task_id: str,
    sub_id: str,
    actor: str,
    reason: str,
) -> int:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        task_row = tasks_dao.get(conn, task_id)
        if task_row is None:
            print(f"task '{task_id}' not found", file=sys.stderr)
            return 1

        extras = json.loads(task_row.extras_json or "{}")
        subtasks = extras.get("subtasks")
        if not isinstance(subtasks, list):
            print(f"task '{task_id}' has no subtasks", file=sys.stderr)
            return 1

        subtask = next(
            (s for s in subtasks if isinstance(s, dict) and str(s.get("id", "")) == sub_id),
            None,
        )
        if subtask is None:
            print(f"subtask '{sub_id}' not found in task '{task_id}'", file=sys.stderr)
            return 1

        current = str(subtask.get("status", "pending"))
        if current in _NO_CANCEL_STATUSES:
            print(
                f"Cannot cancel subtask '{sub_id}': status is '{current}'. "
                f"Completed work cannot be retroactively cancelled.",
                file=sys.stderr,
            )
            return 1

        subtask["status"] = "cancelled"
        extras["subtasks"] = subtasks
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tasks_dao.update(conn, task_id, task_row.version, {
            "extras_json": json.dumps(extras),
            "updated_at": now,
        })
        conn.commit()
    finally:
        conn.close()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
    ledger_line = (
        f"- {now} — {actor} — SUBTASK_CANCEL: {sub_id} "
        f"(parent={task_id}) — {reason}\n"
    )
    try:
        with open(ledger_file, "a") as f:
            f.write(ledger_line)
    except OSError as e:
        print(f"Warning: could not append to ledger: {e}", file=sys.stderr)

    print(f"Cancelled subtask '{sub_id}' in task '{task_id}' (actor={actor})")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="subtask-cancel",
        description="Mark a subtask cancelled. Writes a ledger entry with the reason.",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--task", dest="task_id", required=True,
                        help="Parent task ID")
    parser.add_argument("--sub", dest="sub_id", required=True,
                        help="Subtask ID to cancel")
    parser.add_argument("--actor", default="claude-code")
    parser.add_argument("--reason", required=True,
                        help="Why this subtask is being cancelled (mandatory)")

    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())

    if not os.path.exists(os.path.join(project_dir, ".superharness", "state.sqlite3")):
        print(f"Missing project state: {project_dir}/.superharness/state.sqlite3", file=sys.stderr)
        sys.exit(1)

    rc = cancel_subtask(
        project_dir, opts.task_id, opts.sub_id, opts.actor, opts.reason
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
