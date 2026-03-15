"""test-type — set mandatory test types on a contract task.

Usage:
  superharness test-type --id <task-id> --set unit --set e2e   # replace list
  superharness test-type --id <task-id> --add smoke             # append
  superharness test-type --id <task-id> --remove e2e            # remove one
  superharness test-type --id <task-id> --show                  # print current types
  superharness test-type --all --set unit --set e2e             # apply to all tasks
  superharness test-type --all --show                           # show types for all tasks
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

try:
    from ruamel.yaml import YAML as RuamelYAML
    _RT_AVAILABLE = True
except ImportError:
    _RT_AVAILABLE = False

import yaml

HELP_TEXT = """\
Usage:
  test-type --id <task-id> [--set TYPE]... [--add TYPE]... [--remove TYPE]... [--show]
  test-type --all [--set TYPE]... [--add TYPE]... [--remove TYPE]... [--show]

Set mandatory test type requirements on a contract task (or all tasks).
When called without --set/--add/--remove, prompts interactively.

Options:
  -p, --project DIR   Project directory containing .superharness/ (default: cwd)
  --id TASK_ID        Task id to modify (mutually exclusive with --all)
  --all               Apply to every task in the contract
  --set TYPE          Replace entire test_types list (repeatable)
  --add TYPE          Append a test type without replacing (repeatable)
  --remove TYPE       Remove a specific test type (repeatable)
  --show              Print current test types and exit
  -h, --help          Show this message and exit

Common test types: unit, integration, e2e, manual, smoke
"""

SUGGESTED_TYPES = ["unit", "integration", "e2e", "manual", "smoke"]


def _prompt_test_types(current: list[str]) -> list[str]:
    """Interactive prompt — ask user to pick test types from a menu."""
    print()
    print("Select mandatory test types (space-separated numbers, or type custom names):")
    for i, t in enumerate(SUGGESTED_TYPES, 1):
        mark = "✓" if t in current else " "
        print(f"  [{mark}] {i}. {t}")
    print()
    if current:
        print(f"  Current: {', '.join(current)}")
    print("  Enter numbers (e.g. 1 3) or type names (e.g. unit e2e) or press Enter to keep current:")
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return current

    if not raw:
        return current

    selected: list[str] = []
    for token in raw.split():
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(SUGGESTED_TYPES):
                selected.append(SUGGESTED_TYPES[idx])
            else:
                print(f"  (skipping unknown number: {token})")
        else:
            selected.append(token)
    return selected


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _load_contract(path: str) -> object:
    if not os.path.exists(path):
        _abort(f"Missing contract file: {path}")
    if _RT_AVAILABLE:
        rt = RuamelYAML()
        rt.preserve_quotes = True
        with open(path, "r") as f:
            doc = rt.load(f)
        return doc if doc is not None else {}
    with open(path, "r") as f:
        doc = yaml.safe_load(f)
    return doc if doc is not None else {}


def _write_contract(path: str, doc: object) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            if _RT_AVAILABLE:
                rt = RuamelYAML()
                rt.preserve_quotes = True
                rt.default_flow_style = False
                rt.dump(doc, f)
            else:
                f.write(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _find_task(tasks: list, task_id: str) -> dict | None:
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            return t
    return None


def run(
    contract_file: str,
    task_id: str,
    set_types: list[str] | None = None,
    add_types: list[str] | None = None,
    remove_types: list[str] | None = None,
    show: bool = False,
    interactive: bool = False,
) -> int:
    doc = _load_contract(contract_file)
    if not isinstance(doc, dict):
        _abort("contract.yaml must be a mapping")

    tasks = doc.get("tasks")  # type: ignore[union-attr]
    if not isinstance(tasks, list):
        _abort("contract tasks must be a sequence")

    task = _find_task(tasks, task_id)
    if task is None:
        _abort(f"task '{task_id}' not found")
        return 1  # unreachable, satisfies type checker

    if show:
        current = task.get("test_types") or []
        if current:
            print(f"test_types for '{task_id}':")
            for t in current:
                print(f"  - {t}")
        else:
            print(f"No test_types set for '{task_id}'")
        return 0

    current: list = list(task.get("test_types") or [])

    if interactive:
        current = _prompt_test_types(current)
    elif set_types:
        current = list(set_types)
    else:
        if add_types:
            for t in add_types:
                if t not in current:
                    current.append(t)
        if remove_types:
            current = [t for t in current if t not in remove_types]

    if current:
        task["test_types"] = current
    elif "test_types" in task:
        del task["test_types"]

    _write_contract(contract_file, doc)
    if current:
        print(f"test_types for '{task_id}': {', '.join(current)}")
    else:
        print(f"test_types cleared for '{task_id}'")
    return 0


def run_all(
    contract_file: str,
    set_types: list[str] | None = None,
    add_types: list[str] | None = None,
    remove_types: list[str] | None = None,
    show: bool = False,
    interactive: bool = False,
) -> int:
    doc = _load_contract(contract_file)
    if not isinstance(doc, dict):
        _abort("contract.yaml must be a mapping")

    tasks = doc.get("tasks")  # type: ignore[union-attr]
    if not isinstance(tasks, list) or not tasks:
        print("No tasks found in contract.")
        return 0

    if show:
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", "?"))
            current = task.get("test_types") or []
            if current:
                print(f"test_types for '{task_id}': {', '.join(current)}")
            else:
                print(f"No test_types set for '{task_id}'")
        return 0

    errors = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id", "?"))
        current: list = list(task.get("test_types") or [])

        if interactive:
            print(f"\n--- {task_id} ---")
            current = _prompt_test_types(current)
        elif set_types:
            current = list(set_types)
        else:
            if add_types:
                for t in add_types:
                    if t not in current:
                        current.append(t)
            if remove_types:
                current = [t for t in current if t not in remove_types]

        if current:
            task["test_types"] = current
        elif "test_types" in task:
            del task["test_types"]

        if current:
            print(f"test_types for '{task_id}': {', '.join(current)}")
        else:
            print(f"test_types cleared for '{task_id}'")

    _write_contract(contract_file, doc)
    return errors


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--id", dest="task_id", default=None)
    parser.add_argument("--all", dest="all_tasks", action="store_true", default=False)
    parser.add_argument("--set", dest="set_types", action="append", default=None)
    parser.add_argument("--add", dest="add_types", action="append", default=None)
    parser.add_argument("--remove", dest="remove_types", action="append", default=None)
    parser.add_argument("--show", action="store_true", default=False)
    parser.add_argument("--help", "-h", action="store_true", default=False)
    opts = parser.parse_args(argv)

    if opts.help:
        print(HELP_TEXT, end="")
        sys.exit(0)

    if opts.task_id and opts.all_tasks:
        _abort("--id and --all are mutually exclusive", 2)

    if not opts.task_id and not opts.all_tasks:
        _abort("--id is required (or use --all to apply to every task)", 2)

    project = os.path.realpath(opts.project or os.getcwd())
    contract_file = os.path.join(project, ".superharness", "contract.yaml")

    no_type_flags = not opts.set_types and not opts.add_types and not opts.remove_types and not opts.show

    if opts.all_tasks:
        rc = run_all(
            contract_file=contract_file,
            set_types=opts.set_types,
            add_types=opts.add_types,
            remove_types=opts.remove_types,
            show=opts.show,
            interactive=no_type_flags,
        )
    else:
        rc = run(
            contract_file=contract_file,
            task_id=opts.task_id,
            set_types=opts.set_types,
            add_types=opts.add_types,
            remove_types=opts.remove_types,
            show=opts.show,
            interactive=no_type_flags,
        )
    sys.exit(rc)


if __name__ == "__main__":
    main()
