"""superharness verify — record verification result for a contract task.

Sets verified/verified_at/verified_by on the task in contract.yaml
and appends a VERIFY entry to ledger.md.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

try:
    from ruamel.yaml import YAML as RuamelYAML
    _RT_AVAILABLE = True
except ImportError:
    _RT_AVAILABLE = False

import yaml


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _load_contract(path: str) -> dict:
    if not os.path.exists(path):
        _abort(f"Missing contract file: {path}")
    if _RT_AVAILABLE:
        rt = RuamelYAML()
        rt.preserve_quotes = True
        with open(path, "r") as f:
            doc = rt.load(f)
        return doc if doc else {}
    with open(path, "r") as f:
        doc = yaml.safe_load(f)
    return doc if doc else {}


def _write_contract(path: str, doc: object) -> None:
    import tempfile
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


def verify(
    contract_file: str,
    task_id: str,
    method: str,
    result: str,
    actor: str,
) -> int:
    if result not in ("pass", "fail"):
        _abort("--result must be 'pass' or 'fail'", 2)

    doc = _load_contract(contract_file)
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        _abort("contract tasks must be a sequence")

    task = next(
        (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id),
        None,
    )
    if task is None:
        _abort(f"task '{task_id}' not found")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if result == "pass":
        task["verified"] = True
        task["verified_at"] = now
        task["verified_by"] = actor
    else:
        task["verified"] = False
        task["verified_at"] = now
        task["verified_by"] = actor

    _write_contract(contract_file, doc)

    # Append VERIFY entry to ledger
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
    ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
    verdict = "PASS" if result == "pass" else "FAIL"
    ledger_line = f"- {now} — {actor} — VERIFY {verdict}: {task_id} — {method}\n"
    try:
        with open(ledger_file, "a") as f:
            f.write(ledger_line)
    except OSError as e:
        print(f"Warning: could not append to ledger: {e}", file=sys.stderr)

    print(f"Verified task '{task_id}': {verdict} (method: {method})")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="verify",
        description="Record verification result for a contract task",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--id", dest="task_id", required=True)
    parser.add_argument("--method", required=True, help="How the task was verified (free text)")
    parser.add_argument("--result", required=True, choices=["pass", "fail"])
    parser.add_argument("--actor", default="claude-code")

    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")

    rc = verify(contract_file, opts.task_id, opts.method, opts.result, opts.actor)
    sys.exit(rc)


if __name__ == "__main__":
    main()
