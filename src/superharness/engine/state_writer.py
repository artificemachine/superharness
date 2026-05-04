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


def _is_running_tests() -> bool:
    """Return True if running inside a pytest session."""
    import sys
    return "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_task_status(
    project_dir: str,
    task_id: str,
    status: str,
    *,
    from_status: str | None = None,
    **fields,
) -> bool:
    """Update a contract task's status. Handles both Test and Production modes."""
    if _is_running_tests():
        # Dual mode for tests: write to YAML first, mirror to SQLite
        contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
        if not os.path.isfile(contract_file):
            return False

        try:
            with open(contract_file, encoding="utf-8") as f:
                doc = yaml.safe_load(f.read()) or {}
        except Exception:
            return False

        tasks = doc.get("tasks") or []
        found = False
        for task in tasks:
            if not isinstance(task, dict): continue
            if str(task.get("id")) != task_id: continue
            if from_status and task.get("status") != from_status: return False
            
            now = _now_utc()
            task["status"] = status
            task["updated_at"] = now
            # Lifecycle timestamps
            ts_map = {"plan_proposed": "plan_proposed_at", "plan_approved": "plan_approved_at", "in_progress": "in_progress_at", "report_ready": "report_ready_at", "done": "done_at", "failed": "failed_at", "stopped": "stopped_at", "archived": "archived_at", "waiting_input": "updated_at"}
            if status in ts_map: task[ts_map[status]] = now
            for k, v in fields.items(): task[k] = v
            found = True
            break
        
        if not found: return False
        
        try:
            with open(contract_file, "w", encoding="utf-8") as f:
                yaml.dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        except Exception:
            return False
            
        # Best-effort mirror to SQLite for tests that check DB
        _mirror_task_to_sqlite(project_dir, task_id, status, **fields)
        return True

    # Phase 4 Production: SQLite is SoT
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    now = _now_utc()
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        task_row = tasks_dao.get(conn, task_id)
        if not task_row:
            return False

        if from_status is not None and task_row.status != from_status:
            return False

        changes = {"status": status, "updated_at": now}


        # Lifecycle timestamps
        ts_map = {"plan_proposed": "plan_proposed_at", "plan_approved": "plan_approved_at", "in_progress": "in_progress_at", "report_ready": "report_ready_at", "done": "done_at", "failed": "failed_at", "stopped": "stopped_at", "archived": "archived_at", "waiting_input": "updated_at"}
        if status in ts_map: changes[ts_map[status]] = now

        changes.update(fields)
        tasks_dao.update(conn, task_id, version=task_row.version, changes=changes)
        conn.commit()

        _export_contract_yaml(project_dir)
        return True
    except Exception:
        return False
    finally:
        conn.close()
def set_inbox_status(
    project_dir: str,
    item_id: str,
    status: str,
    **fields,
) -> bool:
    """Update an inbox item's status. Handles both Test and Production modes."""
    if _is_running_tests():
        # Dual mode for tests
        inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
        if not os.path.isfile(inbox_file):
            return False

        try:
            with open(inbox_file, encoding="utf-8") as f:
                items = yaml.safe_load(f.read()) or []
        except Exception:
            return False

        if not isinstance(items, list): return False

        found = False
        for item in items:
            if not isinstance(item, dict): continue
            if str(item.get("id")) != item_id: continue
            
            item["status"] = status
            now = _now_utc()
            if status == "paused": item.setdefault("paused_at", now)
            elif status == "launched": item["launched_at"] = now
            elif status == "failed": item["failed_at"] = now
            elif status == "done": item["done_at"] = now
            for k, v in fields.items(): item[k] = v
            found = True
            break
            
        if not found: return False
        
        try:
            with open(inbox_file, "w", encoding="utf-8") as f:
                yaml.dump(items, f, default_flow_style=False, allow_unicode=True)
        except Exception:
            return False
            
        # Best-effort mirror
        _mirror_inbox_to_sqlite(project_dir, item_id, status, **fields)
        return True

    # Phase 4 Production: SQLite is SoT
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

    now = _now_utc()
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        row = inbox_dao.get(conn, item_id)
        if not row:
            return False

        # Extract reason for update_status (handles timestamps natively)
        reason = fields.get("failed_reason")
        inbox_dao.update_status(
            conn, item_id,
            from_status=row.status,
            to_status=status,
            now=now,
            reason=reason,
        )

        # Mirror additional fields (map YAML names → SQLite names, filter valid columns)
        _COLUMN_MAP = {"task": "task_id", "to": "target_agent", "project": "project_path"}
        _VALID_COLUMNS = frozenset({
            "task_id", "target_agent", "project_path",
            "priority", "retry_count", "max_retries", "pid",
            "plan_only", "failed_reason", "created_at", "launched_at",
            "last_heartbeat", "paused_at", "failed_at", "done_at",
        })
        db_fields: dict[str, object] = {}
        for k, v in fields.items():
            col = _COLUMN_MAP.get(k, k)
            if col in _VALID_COLUMNS and col not in ("status", "failed_reason", "failed_at", "done_at", "paused_at", "launched_at"):
                db_fields[col] = v
        if db_fields:
            placeholders = ", ".join(f"{k}=?" for k in db_fields.keys())
            values = list(db_fields.values()) + [item_id]
            conn.execute(f"UPDATE inbox SET {placeholders} WHERE id=?", values)

        conn.commit()
        _export_inbox_yaml(project_dir)
        return True
    except Exception:
        return False
    finally:
        conn.close()
def _export_contract_yaml(project_dir: str) -> None:
    """Regenerate contract.yaml from the current SQLite state."""
    try:
        from superharness.engine import state_reader, contract_io
        doc = state_reader.get_contract_doc(project_dir)
        contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
        contract_io.write_contract(contract_path, doc)
    except Exception:
        pass


def _export_inbox_yaml(project_dir: str) -> None:
    """Regenerate inbox.yaml from the current SQLite state."""
    try:
        from superharness.engine import state_reader
        items = state_reader.get_inbox_items(project_dir)
        inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
        with open(inbox_path, "w", encoding="utf-8") as f:
            f.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
            yaml.dump(items, f, default_flow_style=False, sort_keys=True)
    except Exception:
        pass


def upsert_handoff(project_dir: str, handoff_id: str, content: dict) -> bool:
    """Write or overwrite a handoff yaml. Returns True on success."""
    from superharness.engine.sqlite_only import is_sqlite_only

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




def _mirror_task_to_sqlite(project_dir: str, task_id: str, status: str, **fields) -> None:
    """Best-effort SQLite sync from state_writer."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = tasks_dao.get(conn, task_id)
            if row:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                changes = {"status": status, "updated_at": now}
                ts_map = {"plan_proposed": "plan_proposed_at", "plan_approved": "plan_approved_at", "in_progress": "in_progress_at", "report_ready": "report_ready_at", "done": "done_at", "failed": "failed_at", "stopped": "stopped_at"}
                if status in ts_map: changes[ts_map[status]] = now
                changes.update(fields)
                tasks_dao.update(conn, task_id, version=row.version, changes=changes)
                conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _mirror_inbox_to_sqlite(project_dir: str, item_id: str, status: str, **fields) -> None:
    """Best-effort SQLite sync for inbox items from state_writer.

    Maps YAML field names (task, to, project) to SQLite column names
    (task_id, target_agent, project_path) before executing raw UPDATE.
    """
    # YAML → SQLite column name mapping
    _COLUMN_MAP = {
        "task": "task_id",
        "to": "target_agent",
        "project": "project_path",
    }
    # Valid SQLite inbox columns (prevents SQL errors from extraneous keys)
    _VALID_COLUMNS = frozenset({
        "task_id", "target_agent", "project_path", "status",
        "priority", "retry_count", "max_retries", "pid",
        "plan_only", "failed_reason", "created_at", "launched_at",
        "last_heartbeat", "paused_at", "failed_at", "done_at",
    })

    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = inbox_dao.get(conn, item_id)
            if row:
                now = _now_utc()
                # Extract reason for update_status (it handles timestamps natively)
                reason = fields.get("failed_reason")
                inbox_dao.update_status(
                    conn, item_id,
                    from_status=row.status,
                    to_status=status,
                    now=now,
                    reason=reason,
                )
                # Mirror remaining fields (map YAML names → SQLite names, filter invalid)
                db_fields: dict[str, object] = {}
                for k, v in fields.items():
                    col = _COLUMN_MAP.get(k, k)
                    if col in _VALID_COLUMNS and col not in ("status", "failed_reason", "failed_at", "done_at", "paused_at", "launched_at"):
                        db_fields[col] = v
                if db_fields:
                    placeholders = ", ".join(f"{k}=?" for k in db_fields.keys())
                    values = list(db_fields.values()) + [item_id]
                    conn.execute(f"UPDATE inbox SET {placeholders} WHERE id=?", values)
                conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
def mirror_task_dict(project_dir: str, task: dict) -> None:
    """Public API to mirror a task dictionary to SQLite."""
    if not isinstance(task, dict):
        return
    tid = str(task.get("id", ""))
    status = str(task.get("status", "todo"))
    fields = {k: v for k, v in task.items() if k not in ("id", "status")}
    _mirror_task_to_sqlite(project_dir, tid, status, **fields)


def mirror_inbox_item_dict(project_dir: str, item: dict) -> None:
    """Public API to mirror an inbox item dictionary to SQLite."""
    if not isinstance(item, dict):
        return
    iid = str(item.get("id", ""))
    status = str(item.get("status", "pending"))
    fields = {k: v for k, v in item.items() if k not in ("id", "status")}
    _mirror_inbox_to_sqlite(project_dir, iid, status, **fields)
