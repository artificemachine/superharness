"""Python port of inbox-enqueue.sh.

Enqueue an inbox item, with optional contract validation.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

from superharness.engine.next_action import (
    TERMINAL_STATUSES,
    allowed_statuses_for_workflow,
    infer_workflow,
    plan_only_allowed_statuses,
)

TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")
VALID_TARGETS = {"claude-code", "codex-cli", "gemini-cli"}


_JSON_MODE = False
_JSON_CTX: dict = {}


def _ensure_task_in_sqlite(conn, task_id: str, project_dir: str, now: str) -> None:
    """Upsert a minimal task row if it is not yet in SQLite. Never raises."""
    try:
        from superharness.engine import tasks_dao
        import yaml as _yaml
        if tasks_dao.get(conn, task_id) is not None:
            return
        contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
        if not os.path.exists(contract_file):
            return
        with open(contract_file, encoding="utf-8") as _f:
            doc = _yaml.safe_load(_f) or {}
        td = next(
            (t for t in (doc.get("tasks") or []) if isinstance(t, dict) and t.get("id") == task_id),
            None,
        )
        if td is None:
            return
        row = tasks_dao.TaskRow(
            id=task_id,
            title=str(td.get("title", task_id)),
            owner=td.get("owner"),
            status=str(td.get("status", "todo")),
            effort=td.get("effort"),
            project_path=td.get("project_path"),
            development_method=td.get("development_method"),
            acceptance_criteria=td.get("acceptance_criteria") or [],
            test_types=td.get("test_types") or [],
            out_of_scope=td.get("out_of_scope") or [],
            definition_of_done=td.get("definition_of_done") or [],
            context=td.get("context"),
            tdd=td.get("tdd"),
            version=1,
            created_at=td.get("created_at") or now,
            blocked_by=td.get("blocked_by") or [],
        )
        tasks_dao.upsert(conn, row)
    except Exception:
        pass


def _sqlite_mirror_enqueue(
    *,
    project_dir: str,
    item_id: str,
    task_id: str,
    target: str,
    priority: int,
    plan_only: bool,
    created_at: str,
) -> None:
    """Mirror a YAML enqueue to SQLite. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import inbox_dao, ledger_dao, yaml_sync
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            item = {
                "id": item_id,
                "task": task_id,
                "to": target,
                "status": "pending",
                "priority": priority,
                "retry_count": 0,
                "max_retries": 3,
                "created_at": created_at,
                "project": project_dir,
                "plan_only": plan_only,
            }
            with transaction(conn):
                _ensure_task_in_sqlite(conn, task_id, project_dir, created_at)
                inbox_dao.enqueue(
                    conn,
                    id=item_id,
                    task_id=task_id,
                    target_agent=target,
                    priority=priority,
                    max_retries=3,
                    project_path=project_dir,
                    plan_only=plan_only,
                    now=created_at,
                )
                yaml_sync.enqueue_op(
                    conn, op_type="enqueue_inbox", payload=item, now=created_at
                )
                ledger_dao.record(
                    conn, agent="inbox_enqueue", action="enqueued",
                    task_id=task_id, now=created_at,
                )
        finally:
            conn.close()
    except Exception:
        pass


def _abort(msg: str, code: int = 1) -> None:
    if _JSON_MODE:
        from superharness.utils.json_output import emit_error
        emit_error(msg, exit_code=code, **_JSON_CTX)
    print(msg, file=sys.stderr)
    sys.exit(code)


def _validate_token(name: str, value: str) -> None:
    if not value:
        _abort(f"{name} must not be empty", 2)
    if "\n" in value or "\r" in value or "\t" in value:
        _abort(f"Invalid {name}: contains control characters", 2)
    if not TOKEN_RE.match(value):
        _abort(f"{name} must match ^[A-Za-z0-9._-]+$", 2)


def _validate_contract(
    contract_file: str,
    task_id: str,
    project_dir: str,
    target: str,
    *,
    plan_only: bool = False,
    force_reassign: bool = False,
) -> None:
    """Validate task project_path, owner, and lifecycle status.

    The enqueue gate now mirrors the dispatch gate (`delegate._allowed_statuses_for_workflow`)
    so tasks that dispatch would permanently reject never reach the inbox and
    waste retry cycles. See `engine.lifecycle` for the canonical rule set.
    """
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

    # project_path checks come first — they indicate a broken contract that
    # must be fixed before any dispatch can succeed. Status/workflow gate
    # comes after so test fixtures that omit status still surface path
    # mismatches first.
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

    # Workflow-aware status gate (parity with delegate.py gate 4).
    status = str(task.get("status", ""))
    workflow = infer_workflow(task_id, task)

    # `done` is never re-enqueueable — closed work stays closed. `failed` and
    # `stopped` are re-dispatchable (reconcile will pick them up after launch).
    if status == "done":
        _abort(
            f"blocked: task '{task_id}' status is 'done' — cannot enqueue.\n"
            f"  done: task is already closed."
        )

    if status:
        if plan_only:
            allowed = plan_only_allowed_statuses(workflow)
        else:
            allowed = allowed_statuses_for_workflow(workflow, for_review=True)
        passthrough = {"failed", "stopped"}
        if status not in allowed and status not in passthrough:
            hint = ""
            if workflow == "implementation" and status == "todo":
                hint = (
                    "\n  hint: implementation tasks need an approved plan before dispatch.\n"
                    f"  Either author a plan (`shux task status --id {task_id} --status plan_proposed` "
                    "with a plan handoff) and approve it,\n"
                    f"  OR re-enqueue with `--plan-only` so the agent proposes the plan first."
                )
            elif status == "plan_proposed":
                hint = (
                    f"\n  plan_proposed: approve the plan first "
                    f"(shux task status --id {task_id} --status plan_approved ...)"
                )
            _abort(
                f"blocked: task '{task_id}' status is '{status}' — cannot enqueue "
                f"for workflow '{workflow}'.\n"
                f"  allowed at enqueue: {', '.join(sorted(allowed))}" + hint
            )

    # Owner-mismatch guard. Contract `owner` is the default dispatch target;
    # when --to disagrees we block unless --force-reassign is set.
    owner = str(task.get("owner", "") or "").strip()
    if owner and owner != target:
        if not force_reassign:
            _abort(
                f"blocked: task '{task_id}' is owned by '{owner}', not '{target}'.\n"
                f"  To dispatch to a different agent, pass --force-reassign "
                f"or update contract.yaml (owner field)."
            )
        print(
            f"Warning: reassigning '{task_id}' from owner '{owner}' to '{target}' "
            f"(--force-reassign was set).",
            file=sys.stderr,
        )


def _check_watcher_health(project_dir: str) -> bool:
    """Check if the watcher launchd job is loaded for this project."""
    if platform.system() != "Darwin":
        return True  # Non-macOS — skip launchd check

    slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(project_dir))
    label = f"com.superharness.inbox.{slug}"
    try:
        r = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, check=False,
        )
        return label in r.stdout
    except (FileNotFoundError, OSError):
        return True  # Can't check — don't block


def enqueue_cmd(
    project_dir: str,
    target: str,
    task_id: str,
    item_id: str | None,
    priority: int,
    require_watcher: bool = False,
    plan_only: bool = False,
    force_reassign: bool = False,
    model_override: str = "",
    effort_override: str = "",
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
        _abort(f"--to must be one of: {', '.join(sorted(VALID_TARGETS))}", 2)


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
        _validate_contract(
            contract_file,
            task_id,
            project_dir,
            target,
            plan_only=plan_only,
            force_reassign=force_reassign,
        )

    # Watcher health check
    if not _check_watcher_health(project_dir):
        msg = (
            f"watcher not loaded — enqueued tasks won't dispatch automatically.\n"
            f"  Run: shux watcher-worker --project {project_dir}"
        )
        if require_watcher:
            _abort(msg)
        else:
            print(msg, file=sys.stderr)

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
            plan_only=plan_only,
            model_override=model_override,
            effort_override=effort_override,
        )

    if rc == 2:
        _abort(f"Duplicate rejected (id or pending task already exists): {item_id}")

    if rc != 0:
        _abort(f"Failed to enqueue inbox item: {inbox_file}")

    # Mirror to SQLite — never blocks the CLI on failure
    _sqlite_mirror_enqueue(
        project_dir=project_dir,
        item_id=item_id,
        task_id=task_id,
        target=target,
        priority=priority,
        plan_only=plan_only,
        created_at=created_at,
    )

    print("Enqueued inbox item:")
    print(f"  id: {item_id}")
    print(f"  to: {target}")
    print(f"  task: {task_id}")
    print(f"  priority: {priority}")
    if plan_only:
        print(f"  mode: plan-only (agent proposes plan, does not implement)")
    if model_override:
        print(f"  model override: {model_override}")
    if effort_override:
        print(f"  effort override: {effort_override}")
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
    parser.add_argument("--to", required=True, dest="target", help=f"Target agent ({'|'.join(sorted(VALID_TARGETS))})")
    parser.add_argument("--task", "-t", required=True, dest="task_id", help="Task id from contract/handoff")
    parser.add_argument("--priority", type=int, default=2, help="Priority 1-3 (1 highest, default: 2)")
    parser.add_argument("--id", default=None, dest="item_id", help="Optional inbox item id")
    parser.add_argument("--require-watcher", action="store_true", default=False,
                        help="Block enqueue if watcher is not loaded (default: warn only)")
    parser.add_argument("--plan-only", action="store_true", default=False, dest="plan_only",
                        help="Agent proposes a plan and stops; relaxes the enqueue gate for "
                             "todo+implementation tasks")
    parser.add_argument("--force-reassign", action="store_true", default=False, dest="force_reassign",
                        help="Allow --to to differ from the contract 'owner' field (one-shot override, "
                             "does not rewrite the contract)")
    parser.add_argument("--model", default="", help="Override model/tier for this dispatch")
    parser.add_argument("--effort", default="", help="Override effort for this dispatch")
    parser.add_argument("--json", action="store_true", default=False,
                        help="Emit machine-readable JSON on stdout instead of human text.")

    opts = parser.parse_args(argv)

    global _JSON_MODE, _JSON_CTX
    if opts.json:
        _JSON_MODE = True
        _JSON_CTX = {"task_id": opts.task_id, "to": opts.target}

    if _JSON_MODE:
        import io
        _orig_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = enqueue_cmd(
                project_dir=opts.project,
                target=opts.target,
                task_id=opts.task_id,
                item_id=opts.item_id,
                priority=opts.priority,
                require_watcher=opts.require_watcher,
                plan_only=opts.plan_only,
                force_reassign=opts.force_reassign,
                model_override=opts.model,
                effort_override=opts.effort,
            )
            captured = sys.stdout.getvalue()
        finally:
            sys.stdout = _orig_stdout
        # Parse "id: <value>" from captured output
        item_id_resolved = opts.item_id or ""
        for line in captured.splitlines():
            line = line.strip()
            if line.startswith("id:"):
                item_id_resolved = line.split(":", 1)[1].strip()
                break
        from superharness.utils.json_output import emit_json
        emit_json({
            "task_id": opts.task_id,
            "to": opts.target,
            "item_id": item_id_resolved,
            "priority": opts.priority,
            "plan_only": opts.plan_only,
            "model_override": opts.model,
            "effort_override": opts.effort,
        }, ok=(rc == 0), exit_code=rc)

    rc = enqueue_cmd(
        project_dir=opts.project,
        target=opts.target,
        task_id=opts.task_id,
        item_id=opts.item_id,
        priority=opts.priority,
        require_watcher=opts.require_watcher,
        plan_only=opts.plan_only,
        force_reassign=opts.force_reassign,
        model_override=opts.model,
        effort_override=opts.effort,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
