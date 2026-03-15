"""superharness close — mark a task done with verification gate.

Gates on verified: true. If not verified, prints an actionable error
telling the user to run `superharness verify` first.

On success: sets status=done, appends ledger, writes handoff YAML.
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


def close_task(
    contract_file: str,
    task_id: str,
    actor: str,
    summary: str,
    skip_verify: bool = False,
) -> int:
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

    owner = str(task.get("owner", ""))
    if owner and actor != owner:
        _abort(f"forbidden: actor '{actor}' cannot close task '{task_id}' owned by '{owner}'")

    # Verification gate
    if not skip_verify and not task.get("verified"):
        print(
            f"Cannot close task '{task_id}': not verified.\n"
            f"Run: superharness verify --id {task_id} --method '<how you verified>' --result pass",
            file=sys.stderr,
        )
        return 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    task["status"] = "done"
    if summary:
        task["summary"] = summary

    _write_contract(contract_file, doc)

    # Append ledger entry
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
    ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
    ledger_line = f"- {now} — {actor} — CLOSE: {task_id} — {summary}\n"
    try:
        with open(ledger_file, "a") as f:
            f.write(ledger_line)
    except OSError as e:
        print(f"Warning: could not append to ledger: {e}", file=sys.stderr)

    # Write handoff YAML
    handoff_dir = os.path.join(project_dir, ".superharness", "handoffs")
    os.makedirs(handoff_dir, exist_ok=True)
    handoff_file = os.path.join(handoff_dir, f"{task_id}-to-owner.yaml")
    handoff_data = {
        "task": task_id,
        "from": actor,
        "to": "owner",
        "status": "done",
        "summary": summary,
        "closed_at": now,
    }
    try:
        with open(handoff_file, "w") as f:
            yaml.dump(handoff_data, f, default_flow_style=False, allow_unicode=True)
    except OSError as e:
        print(f"Warning: could not write handoff: {e}", file=sys.stderr)

    # Sync inbox
    try:
        from superharness.commands.task import _sync_inbox_after_status
        _sync_inbox_after_status(project_dir, task_id, "done")
    except Exception:
        pass

    # Vault integration
    try:
        from superharness.commands.task import _vault_write_task_done
        _vault_write_task_done(contract_file, task_id, task, summary)
    except Exception:
        pass

    print(f"Closed task '{task_id}' (actor={actor})")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="close",
        description="Close a verified task: mark done, append ledger, write handoff",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--id", dest="task_id", required=True)
    parser.add_argument("--actor", default="claude-code")
    parser.add_argument("--summary", default="Task completed and verified")
    parser.add_argument(
        "--skip-verify", action="store_true", default=False,
        help="Bypass verification gate (not recommended)",
    )

    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.exists(contract_file):
        _abort(f"Missing contract file: {contract_file}")

    rc = close_task(
        contract_file, opts.task_id, opts.actor, opts.summary,
        skip_verify=opts.skip_verify,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
