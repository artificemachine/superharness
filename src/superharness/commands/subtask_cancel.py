"""shux subtask-cancel — mark a subtask cancelled with a mandatory reason.

Writes the status change into contract.yaml and appends a ledger line:
    - <ISO> — <actor> — SUBTASK_CANCEL: <sub_id> (parent=<task_id>) — <reason>

Refuses to cancel a subtask that is already `done` (completed work cannot
be retroactively cancelled). Allows cancellation from pending, in_progress,
or failed.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from superharness.engine.contract_io import write_contract as _write_contract, read_contract as _read_contract



# Statuses that cannot be cancelled (terminal resolved).
_NO_CANCEL_STATUSES = {"done"}

# Statuses that can be cancelled.
_CANCELLABLE_STATUSES = {"pending", "in_progress", "failed"}


def cancel_subtask(
    contract_file: str,
    task_id: str,
    sub_id: str,
    actor: str,
    reason: str,
) -> int:
    doc, _ = _read_contract(contract_file)
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        print("contract tasks must be a sequence", file=sys.stderr)
        return 1

    parent = next(
        (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id),
        None,
    )
    if parent is None:
        print(f"task '{task_id}' not found", file=sys.stderr)
        return 1

    subtasks = parent.get("subtasks")
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

    _write_contract(contract_file, doc)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
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
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")

    if not os.path.exists(contract_file):
        print(f"Missing contract file: {contract_file}", file=sys.stderr)
        sys.exit(1)

    rc = cancel_subtask(
        contract_file, opts.task_id, opts.sub_id, opts.actor, opts.reason
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
