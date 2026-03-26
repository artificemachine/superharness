"""Python port of inbox-enqueue.sh.

Enqueue an inbox item, with optional contract validation.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from datetime import datetime, timezone

TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")
VALID_TARGETS = {"claude-code", "codex-cli"}


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _validate_token(name: str, value: str) -> None:
    if not value:
        _abort(f"{name} must not be empty", 2)
    if "\n" in value or "\r" in value or "\t" in value:
        _abort(f"Invalid {name}: contains control characters", 2)
    if not TOKEN_RE.match(value):
        _abort(f"{name} must match ^[A-Za-z0-9._-]+$", 2)


def _validate_contract(contract_file: str, task_id: str, project_dir: str) -> None:
    """Validate task project_path against the running project_dir."""
    from superharness.engine.yaml_helpers import safe_load

    doc = safe_load(contract_file, dict)
    tasks = doc.get("tasks") or []

    task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
    if task is None:
        print(
            f"Warning: task '{task_id}' not found in contract. Enqueuing anyway.",
            file=sys.stderr,
        )
        return

    task_path = str(task.get("project_path", "") or "")
    if not task_path:
        _abort(
            f"Task '{task_id}' is missing project_path in {contract_file}\n"
            f'Add: project_path: "{project_dir}"'
        )

    if "$" in task_path:
        _abort(
            f"Task '{task_id}' project_path must be an absolute path, not an environment variable expression.\n"
            f"  contract: {task_path}\n"
            f"  expected: {project_dir}"
        )

    if not os.path.isdir(task_path):
        _abort(
            f"Task '{task_id}' project_path does not exist on disk.\n"
            f"  contract: {task_path}\n"
            f"  expected: {project_dir}"
        )

    canonical = os.path.realpath(task_path)
    if canonical != project_dir:
        _abort(
            f"Task '{task_id}' project_path mismatch.\n"
            f"  contract: {canonical}\n"
            f"  expected: {project_dir}"
        )


def enqueue_cmd(
    project_dir: str,
    target: str,
    task_id: str,
    item_id: str | None,
    priority: int,
) -> int:
    if not os.path.isdir(project_dir):
        _abort(f"Project directory does not exist: {project_dir}")

    project_dir = os.path.realpath(project_dir)

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        _abort(f"Missing .superharness directory: {harness_dir}")

    inbox_file = os.path.join(harness_dir, "inbox.yaml")
    contract_file = os.path.join(harness_dir, "contract.yaml")

    if target not in VALID_TARGETS:
        _abort("--to must be claude-code or codex-cli", 2)

    if priority not in (1, 2, 3):
        _abort("--priority must be 1, 2, or 3", 2)

    _validate_token("task id", task_id)

    # Generate item id if not supplied
    if not item_id:
        now_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rand_part = secrets.token_hex(3)
        item_id = f"{now_ts}-{task_id}-{os.getpid()}-{rand_part}"

    _validate_token("inbox id", item_id)

    # Validate against contract if it exists
    if os.path.exists(contract_file):
        _validate_contract(contract_file, task_id, project_dir)

    # Ensure inbox file exists with header
    from superharness.engine.inbox import HEADER, _inbox_lock, enqueue

    if not os.path.exists(inbox_file):
        with open(inbox_file, "w") as f:
            f.write(HEADER)

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with _inbox_lock(inbox_file):
        rc = enqueue(
            file=inbox_file,
            id=item_id,
            to=target,
            task=task_id,
            project=project_dir,
            priority=priority,
            created_at=created_at,
        )

    if rc == 2:
        _abort(f"Inbox item id already exists: {item_id}")

    if rc != 0:
        _abort(f"Failed to enqueue inbox item: {inbox_file}")

    print("Enqueued inbox item:")
    print(f"  id: {item_id}")
    print(f"  to: {target}")
    print(f"  task: {task_id}")
    print(f"  priority: {priority}")
    print(f"  file: {inbox_file}")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="inbox_enqueue",
        description="Enqueue a task to the superharness inbox",
    )
    parser.add_argument("--project", "-p", required=True, help="Project directory containing .superharness/")
    parser.add_argument("--to", required=True, dest="target", help="claude-code or codex-cli")
    parser.add_argument("--task", "-t", required=True, dest="task_id", help="Task id from contract/handoff")
    parser.add_argument("--priority", type=int, default=2, help="Priority 1-3 (1 highest, default: 2)")
    parser.add_argument("--id", default=None, dest="item_id", help="Optional inbox item id")

    opts = parser.parse_args(argv)

    rc = enqueue_cmd(
        project_dir=opts.project,
        target=opts.target,
        task_id=opts.task_id,
        item_id=opts.item_id,
        priority=opts.priority,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
