"""Python port of engine/discuss.rb — approval gate (status + approve commands)."""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from typing import Iterator

import yaml

from superharness.engine.yaml_helpers import safe_load

import logging
logger = logging.getLogger(__name__)


def _atomic_write(path: str, content: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@contextmanager
def _file_lock(path: str, timeout: float = 5.0) -> Iterator[None]:
    import time

    if sys.platform == "win32":
        # Windows: fcntl not available — yield without advisory lock
        yield
        return

    import fcntl

    lock_path = f"{path}.flock"
    with open(lock_path, "a+") as lock_file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    sys.exit(f"E_LOCK_TIMEOUT: could not acquire lock on {path} within {timeout}s")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _find_pending_handoff(handoff_dir: str, task_id: str) -> tuple[str, dict] | None:
    pattern = os.path.join(handoff_dir, "*.yaml")
    import glob
    candidates = sorted(glob.glob(pattern))
    for file in candidates:
        doc = safe_load(file, dict)
        if not doc:
            continue
        if str(doc.get("task", "")) != task_id:
            continue
        gate = doc.get("approval_gate")
        pending = (
            str(doc.get("status", "")) == "pending_user_approval"
            or (isinstance(gate, dict) and gate.get("required") and not gate.get("approved_by_user"))
        )
        if not pending:
            continue
        return file, doc
    return None


def cmd_status(handoff_dir: str, task_filter: str | None = None) -> int:
    import glob

    rows = []
    for file in sorted(glob.glob(os.path.join(handoff_dir, "*.yaml"))):
        doc = safe_load(file, dict)
        if not doc:
            continue
        status = str(doc.get("status", ""))
        gate = doc.get("approval_gate")
        pending = (
            status == "pending_user_approval"
            or (isinstance(gate, dict) and gate.get("required") and not gate.get("approved_by_user"))
        )
        if not pending:
            continue
        task = str(doc.get("task", ""))
        if task_filter and task != task_filter:
            continue
        rows.append(
            {
                "task": task,
                "status": status,
                "required": gate.get("required") if isinstance(gate, dict) else True,
                "approved_by_user": gate.get("approved_by_user") if isinstance(gate, dict) else False,
                "approved_at": gate.get("approved_at") if isinstance(gate, dict) else None,
                "markdown_report": str(doc.get("markdown_report", "") or ""),
                "file": file,
            }
        )

    if not rows:
        print("No pending user approvals.")
        return 0

    print("Pending user approvals:")
    for r in rows:
        print(
            f"- task={r['task']} status={r['status']} "
            f"approved={r['approved_by_user']} report={r['markdown_report']}"
        )
        print(
            f"  Approve: superharness discuss approve --task {r['task']}"
            f" --by owner --note \"Approved\""
        )
    return 0


def cmd_approve(
    handoff_dir: str,
    contract_file: str,
    inbox_file: str,
    task_id: str,
    project_dir: str,
    actor: str,
    note: str,
) -> int:
    from datetime import datetime, timezone
    import random

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resumed_count = 0
    enqueued_id = None
    task_owner = ""
    task_status_val = ""
    task_project = project_dir

    result = _find_pending_handoff(handoff_dir, task_id)
    if result is None:
        print(f"No pending approval handoff found for task: {task_id}", file=sys.stderr)
        return 1
    handoff_file, handoff_doc = result

    current_status = str(handoff_doc.get("status", ""))
    gate = handoff_doc.get("approval_gate")
    is_pending = current_status == "pending_user_approval" or (
        isinstance(gate, dict) and gate.get("required") and not gate.get("approved_by_user")
    )
    if not is_pending:
        print(
            f"Invalid state transition: handoff status '{current_status}' cannot be approved",
            file=sys.stderr,
        )
        return 1

    lock_files = [handoff_file]
    if os.path.exists(contract_file):
        lock_files.append(contract_file)
    lock_files.append(inbox_file)

    def _do_approve() -> None:
        nonlocal handoff_doc, task_owner, task_status_val, task_project, resumed_count, enqueued_id

        handoff_doc = safe_load(handoff_file, dict)
        if not handoff_doc or str(handoff_doc.get("task", "")) != task_id:
            print("Handoff file changed during lock acquisition", file=sys.stderr)
            sys.exit(1)

        handoff_doc.setdefault("approval_gate", {})
        handoff_doc["approval_gate"]["required"] = True
        handoff_doc["approval_gate"]["approved_by_user"] = True
        handoff_doc["approval_gate"]["approved_at"] = now
        handoff_doc["approval_gate"]["approved_by"] = str(actor)
        if note.strip():
            handoff_doc["approval_gate"]["note"] = str(note)
        handoff_doc["status"] = "approved"
        _atomic_write(handoff_file, yaml.dump(handoff_doc))

        if os.path.exists(contract_file):
            contract_doc = safe_load(contract_file, dict)
            if isinstance(contract_doc, dict) and isinstance(contract_doc.get("tasks"), list):
                for t in contract_doc["tasks"]:
                    if not isinstance(t, dict):
                        continue
                    if str(t.get("id", "")) != task_id:
                        continue
                    task_owner = str(t.get("owner", ""))
                    if str(t.get("status", "")) == "pending_user_approval":
                        t["status"] = "todo"
                    elif str(t.get("status", "")) in ("done", "failed", "closed"):
                        print(
                            f"Warning: task '{task_id}' has status '{t['status']}' "
                            "— approval recorded but status not changed",
                            file=sys.stderr,
                        )
                    task_status_val = str(t.get("status", ""))
                    tp = str(t.get("project_path", "") or "")
                    if tp:
                        task_project = tp
                    if note.strip():
                        t["summary"] = f"User approval granted at {now} by {actor}: {note}"
                    else:
                        t["summary"] = f"User approval granted at {now} by {actor}"
                from superharness.engine.contract_io import write_contract as _write_contract
                _write_contract(contract_file, contract_doc)

        inbox_doc: list = []
        changed = False

        # Check for paused items in SQLite inbox and resume them
        try:
            from superharness.engine.db import get_connection as _gci, init_db as _idbi
            from superharness.engine import inbox_dao as _idao
            _conn = _gci(project_dir)
            try:
                _idbi(_conn)
                paused_items = _idao.get_all(_conn, status="paused")
                for row in paused_items:
                    if str(row.task_id) != task_id:
                        continue
                    _idao.update_status(_conn, row.id, from_status="paused",
                                       to_status="pending", now=now)
                    resumed_count += 1
                    changed = True

                if resumed_count == 0 and task_owner and task_status_val in ("todo", "in_progress"):
                    active = any(
                        str(r.task_id) == task_id and r.status in ("pending", "paused", "launched", "running")
                        for r in _idao.get_all(_conn)
                    )
                    if not active:
                        enqueued_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{task_id}-{os.getpid()}-{random.randint(0, 999999999)}"
                        _idao.enqueue(_conn, id=enqueued_id, task_id=task_id,
                                     target_agent=str(task_owner), priority=1,
                                     max_retries=3, project_path=str(task_project),
                                     plan_only=False, now=now, model_override="")
                        changed = True

                if changed:
                    _conn.commit()
            finally:
                _conn.close()
        except Exception as e:
            logger.warning("discuss.py unexpected error: %s", e, exc_info=True)
            pass
        if not changed and task_owner and task_status_val in ("todo", "in_progress"):
            try:
                _conn2 = _gci(project_dir)
                try:
                    _idbi(_conn2)
                    enqueued_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{task_id}-{os.getpid()}-{random.randint(0, 999999999)}"
                    _idao.enqueue(_conn2, id=enqueued_id, task_id=task_id,
                                 target_agent=str(task_owner), priority=1,
                                 max_retries=3, project_path=str(task_project),
                                 plan_only=False, now=now, model_override="")
                    _conn2.commit()
                finally:
                    _conn2.close()
            except Exception as e:
                logger.warning("discuss.py unexpected error: %s", e, exc_info=True)
                pass
    # Acquire locks in order
    def _with_locks(paths: list[str], fn) -> None:  # type: ignore[type-arg]
        if not paths:
            fn()
            return
        with _file_lock(paths[0]):
            _with_locks(paths[1:], fn)

    _with_locks(lock_files, _do_approve)

    print(f"Approved consensus for task '{task_id}' by {actor}.")
    print(f"Updated handoff: {handoff_file}")
    if resumed_count > 0:
        print(f"Resumed {resumed_count} paused inbox item(s) awaiting approval.")
    elif enqueued_id:
        print(f"Auto-enqueued inbox item: {enqueued_id} (to={task_owner}, task={task_id}, priority=1)")
    else:
        print("No inbox action needed.")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print("Usage: discuss <status|approve> [options]", file=sys.stderr)
        sys.exit(1)

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "status":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--handoff-dir", dest="handoff_dir")
        parser.add_argument("--task")
        opts = parser.parse_args(rest)
        if not opts.handoff_dir:
            print("--handoff-dir is required", file=sys.stderr)
            sys.exit(1)
        sys.exit(cmd_status(opts.handoff_dir, task_filter=opts.task))

    elif cmd == "approve":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--handoff-dir", dest="handoff_dir")
        parser.add_argument("--contract-file", dest="contract_file")
        parser.add_argument("--inbox-file", dest="inbox_file")
        parser.add_argument("--task")
        parser.add_argument("--project-dir", dest="project_dir")
        parser.add_argument("--by", default="owner")
        parser.add_argument("--note", default="")
        opts = parser.parse_args(rest)
        missing = [k for k in ("handoff_dir", "contract_file", "inbox_file", "task", "project_dir") if not getattr(opts, k, None)]
        if missing:
            flags = ", ".join(f"--{k.replace('_', '-')}" for k in missing)
            print(f"Missing required flags: {flags}", file=sys.stderr)
            sys.exit(1)
        sys.exit(
            cmd_approve(
                opts.handoff_dir,
                opts.contract_file,
                opts.inbox_file,
                opts.task,
                opts.project_dir,
                opts.by,
                opts.note,
            )
        )

    else:
        print("Usage: discuss <status|approve> [options]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
