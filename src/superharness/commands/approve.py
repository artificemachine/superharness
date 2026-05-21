"""shux approve <task_id> — approve a plan via CLI.

Writes an operator_command row (idempotent) and transitions the task to
plan_approved. A second call with the same task_id is a no-op (exits 0).

Usage:
    shux approve <task_id> [--project DIR]
    shux reject  <task_id> [--project DIR]   # via --command reject
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State machine mapping
# ---------------------------------------------------------------------------

_COMMAND_MAP: dict[str, tuple[str, str | None]] = {
    "approve": ("plan_approved", "plan_approved_at"),
    "reject":  ("stopped",       "stopped_at"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _idempotency_key(command: str, task_id: str) -> str:
    """Stable key for CLI-issued commands (no Telegram message_id involved)."""
    return f"cli-{command}-{task_id}"


# ---------------------------------------------------------------------------
# Core logic (importable for tests)
# ---------------------------------------------------------------------------

def run_approve(
    project_dir: Path,
    task_id: str,
    command: str = "approve",
) -> int:
    """Write an operator_command row and apply the status transition.

    Returns:
        0  on success (including idempotent duplicate call)
        1  on error (task not found, unknown command, DB failure)
    """
    if command not in _COMMAND_MAP:
        print(f"Error: unknown command {command!r}. Valid: {list(_COMMAND_MAP)}", file=sys.stderr)
        return 1

    target_status, ts_field = _COMMAND_MAP[command]
    idempotency_key = _idempotency_key(command, task_id)
    now = _now_utc()

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import operator_commands_dao, tasks_dao

    try:
        conn = get_connection(str(project_dir))
        init_db(conn)
    except Exception as exc:
        print(f"Error: could not open DB: {exc}", file=sys.stderr)
        return 1

    try:
        # ---- 1. Insert operator_command row (idempotent) ----
        row, is_new = operator_commands_dao.insert(
            conn,
            idempotency_key=idempotency_key,
            command=command,
            task_id=task_id,
            sender_id="cli",
            now=now,
        )

        if not is_new:
            # Already processed — idempotent success
            conn.close()
            print(f"[{command}] Already applied to {task_id} (idempotent — no change).")
            return 0

        # ---- 2. Resolve the task ----
        task = tasks_dao.get(conn, task_id)
        if task is None:
            operator_commands_dao.update_status(
                conn, row.id,
                status="failed",
                result={"message": f"Task {task_id!r} not found."},
                now=_now_utc(),
            )
            conn.commit()
            conn.close()
            print(f"Error: task {task_id!r} not found.", file=sys.stderr)
            return 1

        # ---- 3. Apply status transition ----
        changes: dict = {"status": target_status, "updated_at": _now_utc()}
        if ts_field:
            changes[ts_field] = _now_utc()
        tasks_dao.update(conn, task_id, task.version, changes)

        # ---- 4. Mark operator_command as executed ----
        operator_commands_dao.update_status(
            conn, row.id,
            status="executed",
            result={"message": f"Task {task_id} {command}d."},
            now=_now_utc(),
        )
        conn.commit()
        conn.close()

        print(f"[{command}] Task {task_id} → {target_status}.")
        return 0

    except Exception as exc:
        try:
            conn.close()
        except Exception as e:
            logger.warning("approve.py unexpected error: %s", e, exc_info=True)
            pass
        print(f"Error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(
        prog="approve",
        description=(
            "Approve (or reject) a task's pending plan. "
            "Writes an operator_command row; idempotent on duplicate call."
        ),
    )
    p.add_argument(
        "-p", "--project",
        default=os.getcwd(),
        help="Project directory (default: cwd)",
    )
    p.add_argument("task_id", help="Task ID to approve/reject")
    p.add_argument(
        "--command",
        default="approve",
        choices=list(_COMMAND_MAP),
        help="Command to execute (default: approve)",
    )
    opts = p.parse_args(argv)

    project_dir = Path(opts.project).resolve()
    sys.exit(run_approve(project_dir, opts.task_id, opts.command))


if __name__ == "__main__":
    main()
