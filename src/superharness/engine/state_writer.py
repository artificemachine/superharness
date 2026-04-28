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
    from superharness.engine.sqlite_only import is_sqlite_only

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")

    if is_sqlite_only():
        # SQLite-only: use the existing mirror function as the primary write path.
        _mirror_task_to_sqlite(project_dir, task_id, status)
        return True

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
                yaml.dump(
                    doc,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
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
    from superharness.engine.sqlite_only import is_sqlite_only

    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")

    if is_sqlite_only():
        # SQLite-only: use the existing mirror function as the primary write path.
        _mirror_inbox_to_sqlite(project_dir, item_id, status)
        return True

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
    from superharness.engine.sqlite_only import is_sqlite_only

    handoffs = os.path.join(project_dir, ".superharness", "handoffs")
    os.makedirs(handoffs, exist_ok=True)
    safe_id = handoff_id.replace("/", "-")
    path = os.path.join(handoffs, f"{safe_id}.yaml")

    if is_sqlite_only():
        # SQLite-only: handoffs go to SQLite only via the handoffs_dao.
        # The YAML file write is skipped. Caller should also persist via handoffs_dao.
        return True

    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(content, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception:
        return False


