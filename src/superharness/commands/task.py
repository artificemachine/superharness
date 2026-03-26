"""Python port of task.sh — create/delete/status operations on contract tasks.

Output format is byte-for-byte identical to the Ruby version.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from typing import Optional

try:
    from ruamel.yaml import YAML as RuamelYAML
    _rt = RuamelYAML()
    _rt.preserve_quotes = True
    _rt.default_flow_style = False
    _RT_AVAILABLE = True
except ImportError:
    _RT_AVAILABLE = False

import yaml

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

VALID_OWNERS = {"claude-code", "codex-cli"}
VALID_CREATE_STATUSES = {"todo", "in_progress", "pending_user_approval", "done"}
VALID_ALL_STATUSES = {
    "todo", "plan_proposed", "plan_approved",
    "in_progress", "report_ready",
    "review_passed", "review_failed",
    "pending_user_approval",
    "done", "failed", "stopped",
}
TOKEN_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_token(name: str, value: str) -> None:
    if not value:
        _abort(f"{name} must not be empty", 2)
    if "\n" in value or "\r" in value or "\t" in value:
        _abort(f"{name} contains control characters", 2)
    if not TOKEN_RE.match(value):
        _abort(f"{name} must match ^[A-Za-z0-9._/-]+$", 2)


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# YAML read / write helpers
# ---------------------------------------------------------------------------

def _load_contract(path: str) -> object:
    """Load contract.yaml in round-trip mode (ruamel) or plain yaml."""
    if not os.path.exists(path):
        _abort(f"Missing contract file: {path}")
    if _RT_AVAILABLE:
        rt = RuamelYAML()
        rt.preserve_quotes = True
        with open(path, "r") as f:
            doc = rt.load(f)
        if doc is None:
            doc = {}
        return doc
    else:
        with open(path, "r") as f:
            doc = yaml.safe_load(f)
        if doc is None:
            doc = {}
        return doc


def _write_contract(path: str, doc: object) -> None:
    """Atomically write contract.yaml."""
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


def _get_tasks(doc: object, path: str) -> list:
    if not isinstance(doc, dict):
        _abort("contract.yaml must be a mapping")
    tasks = doc.get("tasks")  # type: ignore[union-attr]
    if tasks is None:
        return []
    if not isinstance(tasks, list):
        _abort("contract tasks must be a sequence")
    return tasks


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _parse_blocked_by(value: str | list | None) -> str | list:
    """Normalise blocked_by input to 'none', a single ID, or a list."""
    if value is None or value == "" or value == "none":
        return "none"
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip()
    if "," in s:
        return [v.strip() for v in s.split(",") if v.strip()]
    return s


def create(
    contract_file: str,
    task_id: str,
    title: str,
    owner: str,
    status: str,
    project_path: str,
    dependency: Optional[str] = None,
    criteria: Optional[list] = None,
    blocked_by: str | list | None = None,
    tdd_red: str = "",
    tdd_green: str = "",
    tdd_refactor: str = "",
) -> int:
    _validate_token("task id", task_id)
    if dependency:
        _validate_token("dependency id", dependency)

    if owner not in VALID_OWNERS:
        _abort("owner must be claude-code or codex-cli", 2)
    if status not in VALID_CREATE_STATUSES:
        _abort("status must be todo, in_progress, pending_user_approval, or done", 2)

    doc = _load_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    # Check duplicate
    if any(isinstance(t, dict) and str(t.get("id", "")) == task_id for t in tasks):
        _abort(f"task '{task_id}' already exists")

    # Check dependency (legacy single-ID field)
    if dependency:
        if dependency == task_id:
            _abort(f"task '{task_id}' cannot depend on itself")
        if not any(isinstance(t, dict) and str(t.get("id", "")) == dependency for t in tasks):
            _abort(f"dependency task '{dependency}' not found")

    # Validate blocked_by IDs
    blocked = _parse_blocked_by(blocked_by)
    if blocked != "none":
        ids_to_check = blocked if isinstance(blocked, list) else [blocked]
        existing_ids = {str(t.get("id", "")) for t in tasks if isinstance(t, dict)}
        for bid in ids_to_check:
            if bid == task_id:
                _abort(f"task '{task_id}' cannot be blocked by itself")
            if bid not in existing_ids:
                _abort(f"blocked_by task '{bid}' not found")

    if _RT_AVAILABLE:
        from ruamel.yaml.comments import CommentedMap
        task: dict = CommentedMap()
    else:
        task = {}

    task["id"] = task_id
    task["title"] = title
    task["owner"] = owner
    task["status"] = status
    task["project_path"] = project_path
    task["blocked_by"] = blocked
    if dependency:
        task["dependency"] = dependency
    if criteria:
        task["acceptance_criteria"] = list(criteria)
    if tdd_red or tdd_green or tdd_refactor:
        tdd: dict = {}
        if tdd_red:
            tdd["red"] = tdd_red
        if tdd_green:
            tdd["green"] = tdd_green
        if tdd_refactor:
            tdd["refactor"] = tdd_refactor
        task["tdd"] = tdd

    tasks.append(task)
    doc["tasks"] = tasks  # type: ignore[index]
    _write_contract(contract_file, doc)

    print(f"Created task '{task_id}' (owner={owner}, status={status}, blocked_by={blocked})")
    return 0


def delete(contract_file: str, task_id: str) -> int:
    _validate_token("task id", task_id)

    doc = _load_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    before = len(tasks)
    new_tasks = [t for t in tasks if not (isinstance(t, dict) and str(t.get("id", "")) == task_id)]
    if len(new_tasks) == before:
        _abort(f"task '{task_id}' not found")

    doc["tasks"] = new_tasks  # type: ignore[index]
    _write_contract(contract_file, doc)
    print(f"Deleted task '{task_id}'")
    return 0


def status_update(
    contract_file: str,
    task_id: str,
    status: str,
    actor: str,
    reason: str = "",
    summary: str = "",
) -> int:
    _validate_token("task id", task_id)

    if status not in VALID_ALL_STATUSES:
        _abort(f"status must be one of: {', '.join(sorted(VALID_ALL_STATUSES))}", 2)

    if status in ("failed", "stopped") and not reason:
        _abort(f"error: --reason is required when status={status}", 2)

    if status in ("todo", "in_progress", "pending_user_approval", "done") and not summary:
        _abort(f"error: --summary is required when status={status}", 2)

    doc = _load_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
    if task is None:
        _abort(f"task '{task_id}' not found")

    owner = str(task.get("owner", ""))
    if not owner:
        _abort(f"task '{task_id}' has no owner set")

    dependency = str(task.get("dependency", "") or "")

    if actor != owner:
        _abort(f"forbidden: actor '{actor}' cannot update task '{task_id}' owned by '{owner}'")  # shipguard:ignore PY-007

    if dependency and status in ("in_progress", "done"):
        dep_task = next(
            (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == dependency),
            None
        )
        if dep_task is None:
            _abort(f"task '{task_id}' dependency '{dependency}' not found")
        dep_status = str(dep_task.get("status", ""))
        if dep_status != "done":
            _abort(f"blocked: task '{task_id}' depends on '{dependency}' (status={dep_status})")

    task["status"] = status

    if status in ("failed", "stopped") and reason:
        task["stopped_reason"] = reason
        task["stopped_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        task.pop("stopped_reason", None)  # type: ignore[union-attr]
        task.pop("stopped_at", None)  # type: ignore[union-attr]

    if summary:
        task["summary"] = summary
    elif status not in ("failed", "stopped"):
        task.pop("summary", None)  # type: ignore[union-attr]

    _write_contract(contract_file, doc)

    # Warn about unverified acceptance criteria when marking done
    if status == "done":
        ac = task.get("acceptance_criteria")
        if ac and isinstance(ac, list) and ac:
            print(f"Warning: task '{task_id}' has acceptance criteria — verify before closing:", file=sys.stderr)
            for c in ac:
                print(f"  - {c}", file=sys.stderr)

    print(f"Updated task '{task_id}' status={status} by actor={actor}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="task",
        description="Manage contract tasks",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="subcmd")

    # create
    p_create = sub.add_parser("create", add_help=True)
    p_create.add_argument("--project", "-p", default=None)
    p_create.add_argument("--id", dest="task_id", required=True)
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--owner", default=None)
    p_create.add_argument("--status", default="todo")
    p_create.add_argument("--dependency", default="")
    p_create.add_argument("--blocked-by", dest="blocked_by", default=None,
                          help="Task ID(s) this task is blocked by (comma-separated, or 'none')")
    p_create.add_argument("--tdd-red", dest="tdd_red", default="",
                          help="TDD red phase: failing tests that define done")
    p_create.add_argument("--tdd-green", dest="tdd_green", default="",
                          help="TDD green phase: minimal code to make tests pass")
    p_create.add_argument("--tdd-refactor", dest="tdd_refactor", default="",
                          help="TDD refactor phase: cleanup after green, no new behaviour")
    p_create.add_argument("--criteria", action="append", default=[], metavar="CRITERION",
                          help="Acceptance criterion (repeat for multiple)")

    # delete
    p_delete = sub.add_parser("delete", add_help=True)
    p_delete.add_argument("--project", "-p", default=None)
    p_delete.add_argument("--id", dest="task_id", required=True)

    # status
    p_status = sub.add_parser("status", add_help=True)
    p_status.add_argument("--project", "-p", default=None)
    p_status.add_argument("--id", dest="task_id", required=True)
    _valid_status_hint = "{" + "|".join(sorted(VALID_ALL_STATUSES)) + "}"
    p_status.add_argument("--status", required=True, metavar=_valid_status_hint,
                          help=f"Lifecycle status. One of: {', '.join(sorted(VALID_ALL_STATUSES))}")
    p_status.add_argument("--actor", required=True)
    p_status.add_argument("--reason", default="")
    p_status.add_argument("--summary", default="")

    opts = parser.parse_args(argv)
    if not opts.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    project_dir = opts.project or os.getcwd()
    if not os.path.isabs(project_dir):
        project_dir = os.path.realpath(project_dir)
    else:
        project_dir = os.path.realpath(project_dir)

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.exists(contract_file):
        _abort(f"Missing contract file: {contract_file}")

    if opts.subcmd == "create":
        owner = opts.owner or ""
        if not owner:
            # Try profile.yaml primary_agent
            profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
            if os.path.exists(profile_file):
                try:
                    import yaml as _yaml
                    with open(profile_file) as _f:
                        _profile = _yaml.safe_load(_f) or {}
                    owner = str(_profile.get("primary_agent") or "")
                except Exception:
                    pass
        if not owner:
            # Prompt via stdin
            try:
                if sys.stdin.isatty():
                    sys.stderr.write("Task owner (claude-code|codex-cli): ")
                    sys.stderr.flush()
                owner = sys.stdin.readline().strip()
            except (EOFError, OSError):
                pass
        if not owner:
            _abort("--owner is required (or set in profile.yaml)", 2)
        rc = create(
            contract_file,
            task_id=opts.task_id,
            title=opts.title,
            owner=owner,
            status=opts.status,
            project_path=project_dir,
            dependency=opts.dependency or None,
            criteria=opts.criteria or None,
            blocked_by=opts.blocked_by,
            tdd_red=opts.tdd_red,
            tdd_green=opts.tdd_green,
            tdd_refactor=opts.tdd_refactor,
        )
        sys.exit(rc)

    elif opts.subcmd == "delete":
        rc = delete(contract_file, task_id=opts.task_id)
        sys.exit(rc)

    elif opts.subcmd == "status":
        # Pre-validate before calling status_update so shell exit codes match
        if opts.status in ("failed", "stopped") and not opts.reason:
            _abort(f"error: --reason is required when status={opts.status}", 2)
        if opts.status in ("todo", "in_progress", "pending_user_approval", "done") and not opts.summary:
            _abort(f"error: --summary is required when status={opts.status}", 2)

        rc = status_update(
            contract_file,
            task_id=opts.task_id,
            status=opts.status,
            actor=opts.actor,
            reason=opts.reason or "",
            summary=opts.summary or "",
        )
        # Sync inbox after status update
        _sync_inbox_after_status(project_dir, opts.task_id, opts.status)
        sys.exit(rc)


def _sync_inbox_after_status(project_dir: str, task_id: str, status: str) -> None:
    """Mirror inbox sync logic from task.sh: sync inbox when task reaches terminal state."""
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    if not os.path.exists(inbox_file):
        return
    if status not in ("done", "failed", "stopped"):
        return
    import subprocess
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "superharness.engine.inbox", "sync_task_status",
             "--file", inbox_file, "--task", task_id, "--to", status, "--now", now],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"Warning: failed to sync inbox task status for '{task_id}': {result.stdout.strip()} {result.stderr.strip()}",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"Warning: failed to sync inbox task status for '{task_id}': {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
