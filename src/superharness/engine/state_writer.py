"""state_writer — unified write API for tasks, inbox, handoffs.

Foundation for SQLite-as-SoT migration. Writes YAML (source of truth
during transition) and mirrors to SQLite so both stores stay in sync.

API:
  set_task_status(project_dir, task_id, status, *, from_status=None) -> bool
  set_inbox_status(project_dir, item_id, status, **fields) -> bool
  upsert_handoff(project_dir, handoff_id, content) -> bool
  mirror_task_dict(project_dir, task) -> None        # best-effort SQLite sync
  mirror_inbox_item_dict(project_dir, item) -> None  # best-effort SQLite sync
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import yaml


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_task_status(
    project_dir: str,
    task_id: str,
    status: str,
    *,
    from_status: str | None = None,
) -> bool:
    """Update a contract task's status. Returns True if the task was found and updated."""
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.isfile(contract_file):
        return False

    try:
        with open(contract_file, encoding="utf-8") as f:
            doc = yaml.safe_load(f.read()) or {}
    except Exception:
        return False

    tasks = doc.get("tasks") or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("id", "")) != task_id:
            continue
        if from_status is not None and str(task.get("status", "")) != from_status:
            return False
        task["status"] = status
        task["updated_at"] = _now_utc()
        try:
            with open(contract_file, "w", encoding="utf-8") as f:
                yaml.dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        except Exception:
            return False
        _mirror_task_to_sqlite(project_dir, task_id, status)
        return True
    return False


def set_inbox_status(
    project_dir: str,
    item_id: str,
    status: str,
    **fields,
) -> bool:
    """Update an inbox item's status. Returns True if the item was found."""
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    if not os.path.isfile(inbox_file):
        return False

    try:
        with open(inbox_file, encoding="utf-8") as f:
            items = yaml.safe_load(f.read()) or []
    except Exception:
        return False

    if not isinstance(items, list):
        return False

    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")) != item_id:
            continue
        item["status"] = status
        if status == "paused":
            item.setdefault("paused_at", _now_utc())
        elif status == "launched":
            item["launched_at"] = _now_utc()
        elif status == "failed":
            item["failed_at"] = _now_utc()
        elif status == "done":
            item["done_at"] = _now_utc()
        for k, v in fields.items():
            item[k] = v
        try:
            with open(inbox_file, "w", encoding="utf-8") as f:
                yaml.dump(items, f, default_flow_style=False, allow_unicode=True)
        except Exception:
            return False
        _mirror_inbox_to_sqlite(project_dir, item_id, status)
        return True
    return False


def upsert_handoff(project_dir: str, handoff_id: str, content: dict) -> bool:
    """Write or overwrite a handoff yaml. Returns True on success."""
    handoffs = os.path.join(project_dir, ".superharness", "handoffs")
    os.makedirs(handoffs, exist_ok=True)
    safe_id = handoff_id.replace("/", "-")
    path = os.path.join(handoffs, f"{safe_id}.yaml")
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(content, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception:
        return False


def mirror_task_dict(project_dir: str, task: dict) -> None:
    """Mirror a fully-populated task dict to SQLite. Best-effort, silent on failure."""
    task_id = str(task.get("id", ""))
    status = str(task.get("status", ""))
    if task_id and status:
        _mirror_task_to_sqlite(project_dir, task_id, status)


def mirror_inbox_item_dict(project_dir: str, item: dict) -> None:
    """Mirror a fully-populated inbox item dict to SQLite. Best-effort, silent on failure."""
    item_id = str(item.get("id", ""))
    status = str(item.get("status", ""))
    if item_id and status:
        _mirror_inbox_to_sqlite(project_dir, item_id, status)


def _mirror_task_to_sqlite(project_dir: str, task_id: str, status: str) -> None:
    """Best-effort SQLite mirror for a task status change."""
    try:
        from superharness.engine import db
        db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
        if not os.path.isfile(db_path):
            return
        conn = db.get_connection(project_dir)
        try:
            conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _mirror_inbox_to_sqlite(project_dir: str, item_id: str, status: str) -> None:
    """Best-effort SQLite mirror for an inbox item status change."""
    try:
        from superharness.engine import db
        db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
        if not os.path.isfile(db_path):
            return
        conn = db.get_connection(project_dir)
        try:
            now = _now_utc()
            extra = ""
            params: list = [status]
            if status == "failed":
                extra = ", failed_at = ?"
                params.append(now)
            elif status == "done":
                extra = ", done_at = ?"
                params.append(now)
            elif status == "paused":
                extra = ", paused_at = ?"
                params.append(now)
            params.append(item_id)
            conn.execute(f"UPDATE inbox SET status = ?{extra} WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
