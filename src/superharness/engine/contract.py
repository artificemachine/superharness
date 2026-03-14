"""Python port of engine/contract.rb.

Provides contract/task query functions and a CLI that mirrors the Ruby interface
byte-for-byte so that parity tests pass.
"""
from __future__ import annotations

import glob
import os
import sys

from superharness.engine.yaml_helpers import safe_load


# ---------------------------------------------------------------------------
# Library functions
# ---------------------------------------------------------------------------


def task_exists(file: str, task: str) -> int:
    doc = safe_load(file, dict)
    tasks = doc.get("tasks")
    if tasks is None:
        print("false")
        return 0
    if not isinstance(tasks, list):
        raise ValueError(f"contract tasks must be a sequence: {file}")
    found = any(isinstance(t, dict) and str(t.get("id", "")) == str(task) for t in tasks)
    print("true" if found else "false")
    return 0


def task_project_path(file: str, task: str) -> int:
    doc = safe_load(file, dict)
    tasks = doc.get("tasks")
    if tasks is None:
        return 0
    if not isinstance(tasks, list):
        raise ValueError(f"contract tasks must be a sequence: {file}")
    row = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == str(task)), None)
    if row is None:
        return 0
    val = row.get("project_path")
    if val is None:
        print(f"contract: task {task} has no project_path", file=sys.stderr)
    print(str(val) if val is not None else "")
    return 0


def task_owner(file: str, task: str) -> int:
    doc = safe_load(file, dict)
    tasks = doc.get("tasks")
    if tasks is None:
        return 0
    if not isinstance(tasks, list):
        raise ValueError(f"contract tasks must be a sequence: {file}")
    row = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == str(task)), None)
    if row is None:
        return 0
    val = row.get("owner")
    if val is None:
        print(f"contract: task {task} has no owner", file=sys.stderr)
    print(str(val) if val is not None else "")
    return 0


def task_status(file: str, task: str) -> int:
    doc = safe_load(file, dict)
    tasks = doc.get("tasks")
    if tasks is None:
        return 0
    if not isinstance(tasks, list):
        raise ValueError(f"contract tasks must be a sequence: {file}")
    row = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == str(task)), None)
    if row is None:
        return 0
    val = row.get("status")
    if val is None:
        print(f"contract: task {task} has no status", file=sys.stderr)
    print(str(val) if val is not None else "")
    return 0


def contract_id(file: str) -> int:
    doc = safe_load(file, dict)
    print(str(doc.get("id", "") or ""))
    return 0


def task_acceptance_criteria(file: str, task: str) -> int:
    doc = safe_load(file, dict)
    tasks = doc.get("tasks")
    if tasks is None:
        return 0
    if not isinstance(tasks, list):
        raise ValueError(f"contract tasks must be a sequence: {file}")
    row = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == str(task)), None)
    if row is None:
        return 0
    criteria = row.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        return 0
    for c in criteria:
        print(str(c))
    return 0


def task_deadline_minutes(file: str, task: str) -> int:
    doc = safe_load(file, dict)
    tasks = doc.get("tasks")
    if tasks is None:
        return 0
    if not isinstance(tasks, list):
        raise ValueError(f"contract tasks must be a sequence: {file}")
    row = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == str(task)), None)
    if row is None:
        return 0
    val = row.get("deadline_minutes")
    if val is not None:
        print(str(val))
    return 0


def latest_handoff_task(dir: str, to: str) -> int:
    pattern = os.path.join(dir, "*.yaml")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for file in files:
        try:
            data = safe_load(file, dict)
        except Exception as e:
            sys.exit(f"Failed to parse handoff {file}: {e}")
        if str(data.get("to", "")) != str(to):
            continue
        task_val = str(data.get("task", ""))
        if not task_val:
            continue
        print(f"{task_val}|{file}")
        return 0
    return 0


# ---------------------------------------------------------------------------
# CLI (mirrors contract.rb interface exactly)
# ---------------------------------------------------------------------------


def _make_parser() -> "argparse.ArgumentParser":  # noqa: F821
    import argparse

    p = argparse.ArgumentParser(
        prog="contract",
        description="Contract engine",
        add_help=False,
    )
    sub = p.add_subparsers(dest="cmd")

    for name in ("task_exists", "task_project_path", "task_owner", "task_status",
                 "task_deadline_minutes", "task_acceptance_criteria"):
        s = sub.add_parser(name, add_help=False)
        s.add_argument("--file")
        s.add_argument("--task")

    s = sub.add_parser("contract_id", add_help=False)
    s.add_argument("--file")

    s = sub.add_parser("latest_handoff_task", add_help=False)
    s.add_argument("--dir")
    s.add_argument("--to")

    return p


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(
            "Usage: contract <task_exists|task_project_path|task_owner|task_status"
            "|task_deadline_minutes|task_acceptance_criteria|contract_id|latest_handoff_task> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd_name = argv[0]
    rest = argv[1:]

    valid_cmds = {
        "task_exists",
        "task_project_path",
        "task_owner",
        "task_status",
        "task_deadline_minutes",
        "task_acceptance_criteria",
        "contract_id",
        "latest_handoff_task",
    }
    if cmd_name not in valid_cmds:
        print(
            "Usage: contract <task_exists|task_project_path|task_owner|task_status"
            "|task_deadline_minutes|task_acceptance_criteria|contract_id|latest_handoff_task> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse remaining args for this subcommand
    parser = argparse.ArgumentParser(add_help=False)

    if cmd_name in ("task_exists", "task_project_path", "task_owner", "task_status",
                    "task_deadline_minutes", "task_acceptance_criteria"):
        parser.add_argument("--file")
        parser.add_argument("--task")
        opts = parser.parse_args(rest)
        if not opts.file or not opts.task:
            print("--file and --task are required", file=sys.stderr)
            sys.exit(1)
        rc = globals()[cmd_name](opts.file, opts.task)
        sys.exit(rc)

    elif cmd_name == "contract_id":
        parser.add_argument("--file")
        opts = parser.parse_args(rest)
        if not opts.file:
            print("--file is required", file=sys.stderr)
            sys.exit(1)
        rc = contract_id(opts.file)
        sys.exit(rc)

    elif cmd_name == "latest_handoff_task":
        parser.add_argument("--dir")
        parser.add_argument("--to")
        opts = parser.parse_args(rest)
        if not opts.dir or not opts.to:
            print("--dir and --to are required", file=sys.stderr)
            sys.exit(1)
        rc = latest_handoff_task(opts.dir, opts.to)
        sys.exit(rc)


if __name__ == "__main__":
    main()
