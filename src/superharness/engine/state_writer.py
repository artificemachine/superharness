"""state_writer — unified write API for tasks, inbox, handoffs (iter 3a skeleton).

This is the FOUNDATION for iter 3 of auto-mode-gap-plan: SQLite as the
single source of truth. Today (3a), this module provides a public API that
performs YAML writes (and best-effort SQLite mirror) so callers can migrate
to it. In 3b..3d, individual writers across the codebase migrate to call
these functions instead of editing YAML directly. In 3e, the default backend
switches to sqlite_only and YAML becomes export-only.

Why a skeleton now: it defines the contract and gives migration targets, so
later iterations are mechanical refactors rather than design work.

API:
  set_task_status(project_dir, task_id, status, *, from_status=None) -> bool
  set_inbox_status(project_dir, item_id, status, **fields) -> bool
  upsert_handoff(project_dir, handoff_id, content) -> bool

All functions return True on success, False on no-op (e.g. unknown id).
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
        # Best-effort SQLite mirror (skipped silently if unavailable in 3a)
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
        # Stamp common timestamp keys based on status
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


def _mirror_task_to_sqlite(project_dir: str, task_id: str, status: str) -> None:
    """Best-effort SQLite mirror. Silent on failure (skeleton stage)."""
    try:
        from superharness.engine import db, tasks_dao
        conn = db.connect(project_dir)
        try:
            with db.transaction(conn):
                tasks_dao.update_status(conn, task_id, status, now=_now_utc())
        finally:
            conn.close()
    except Exception:
        pass


def _mirror_inbox_to_sqlite(project_dir: str, item_id: str, status: str) -> None:
    """Best-effort SQLite mirror. Silent on failure (skeleton stage)."""
    try:
        from superharness.engine import db, inbox_dao
        conn = db.connect(project_dir)
        try:
            with db.transaction(conn):
                inbox_dao.update_status(
                    conn, item_id,
                    from_status=None,  # type: ignore[arg-type]
                    to_status=status,
                    now=_now_utc(),
                )
        finally:
            conn.close()
    except Exception:
        pass
