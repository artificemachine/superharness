from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass

import yaml

from superharness.engine.state_errors import StateError

logger = logging.getLogger(__name__)

_OP_HANDLERS: dict[str, str] = {
    "upsert_task": "_apply_upsert_task",
    "update_inbox": "_apply_update_inbox",
    "enqueue_inbox": "_apply_enqueue_inbox",
    "update_task_status": "_apply_update_task_status",
    "append_handoff": "_apply_append_handoff",
    "record_failure": "_apply_record_failure",
    "record_decision": "_apply_record_decision",
}


@dataclass(frozen=True)
class DrainReport:
    applied: int
    failed: int
    pending_remaining: int


def enqueue_op(
    conn: sqlite3.Connection,
    *,
    op_type: str,
    payload: dict,
    now: str,
) -> int | None:
    """Enqueue a YAML sync operation. Must be called inside the authoritative transaction.

    Returns the new queue row id, or None if a duplicate pending op was silently ignored
    (F8: INSERT OR IGNORE with UNIQUE partial index on (op_type, payload.id) WHERE pending).
    """
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO yaml_sync_queue (op_type, payload, status, attempts, created_at)
            VALUES (?, ?, 'pending', 0, ?)
            """,
            (op_type, json.dumps(payload), now),
        )
        return cursor.lastrowid if cursor.rowcount else None
    except sqlite3.Error as exc:
        raise StateError(f"enqueue_op failed: {exc}") from exc


def _yaml_writes_enabled(project_dir: str) -> bool:
    """Return False when STATE_BACKEND=sqlite_only — YAML writes are skipped entirely."""
    env = os.environ.get("STATE_BACKEND", "").strip().lower()
    if env == "sqlite_only":
        return False
    if env in ("yaml_only", "dual"):
        return True
    try:
        import yaml as _yaml
        profile = os.path.join(project_dir, ".superharness", "profile.yaml")
        if os.path.exists(profile):
            with open(profile, encoding="utf-8") as f:
                doc = _yaml.safe_load(f) or {}
            return str(doc.get("state_backend", "")).strip().lower() != "sqlite_only"
    except Exception:
        pass
    return True


def drain(
    conn: sqlite3.Connection,
    project_dir: str,
    *,
    max_ops: int = 100,
    max_attempts: int = 5,
) -> DrainReport:
    """Apply pending sync ops to YAML files. Never raises; aggregates errors into report.

    In sqlite_only mode, pending ops are marked applied without writing YAML so the
    queue stays drained and lag stays zero.
    """
    applied = 0
    failed = 0

    if not _yaml_writes_enabled(project_dir):
        try:
            count = conn.execute(
                "UPDATE yaml_sync_queue SET status='applied', applied_at=datetime('now') WHERE status='pending'"
            ).rowcount
            conn.commit()
            return DrainReport(applied=count, failed=0, pending_remaining=0)
        except sqlite3.Error:
            return DrainReport(applied=0, failed=0, pending_remaining=0)

    try:
        cursor = conn.execute(
            """
            SELECT id, op_type, payload, attempts
            FROM yaml_sync_queue
            WHERE status = 'pending' AND attempts < ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max_attempts, max_ops),
        )
        ops = cursor.fetchall()
    except sqlite3.Error as exc:
        logger.error("drain: failed to fetch pending ops: %s", exc)
        return DrainReport(applied=0, failed=0, pending_remaining=0)

    for op in ops:
        op_id = op["id"]
        op_type = op["op_type"]
        attempts = op["attempts"]
        try:
            payload = json.loads(op["payload"])
        except (json.JSONDecodeError, TypeError):
            payload = {}

        try:
            _dispatch(op_type, project_dir, payload)
            conn.execute(
                "UPDATE yaml_sync_queue SET status='applied', applied_at=datetime('now') WHERE id=?",
                (op_id,),
            )
            conn.commit()
            applied += 1
        except Exception as exc:
            logger.warning("drain: op %d (%s) failed (attempt %d): %s", op_id, op_type, attempts + 1, exc)
            conn.execute(
                """
                UPDATE yaml_sync_queue
                SET attempts=attempts+1, last_error=?,
                    status=CASE WHEN attempts+1 >= ? THEN 'exhausted' ELSE 'pending' END
                WHERE id=?
                """,
                (str(exc), max_attempts, op_id),
            )
            conn.commit()
            failed += 1

    try:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM yaml_sync_queue WHERE status='pending'"
        ).fetchone()[0]
    except sqlite3.Error:
        remaining = 0

    return DrainReport(applied=applied, failed=failed, pending_remaining=remaining)


def _dispatch(op_type: str, project_dir: str, payload: dict) -> None:
    handlers = {
        "upsert_task": _apply_upsert_task,
        "update_inbox": _apply_update_inbox,
        "enqueue_inbox": _apply_enqueue_inbox,
        "update_task_status": _apply_update_task_status,
        "append_handoff": _apply_append_handoff,
        "record_failure": _apply_record_failure,
        "record_decision": _apply_record_decision,
    }
    handler = handlers.get(op_type)
    if handler is None:
        logger.debug("yaml_sync: unknown op_type '%s', skipping", op_type)
        return
    handler(project_dir, payload)


def _atomic_yaml_write(path: str, data: object) -> None:
    """Write to .tmp then os.replace for atomic update."""
    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def _load_yaml(path: str) -> object:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _apply_enqueue_inbox(project_dir: str, payload: dict) -> None:
    """Append a new inbox item to inbox.yaml (idempotent on id)."""
    from superharness.engine.inbox import _inbox_lock
    inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    with _inbox_lock(inbox_path):
        items = _load_yaml(inbox_path)
        if not isinstance(items, list):
            items = []
        existing_ids = {str(i.get("id", "")) for i in items if isinstance(i, dict)}
        if payload.get("id") not in existing_ids:
            items.append(payload)
        _atomic_yaml_write(inbox_path, items)


def _apply_update_task_status(project_dir: str, payload: dict) -> None:
    """Update a task's status (and optional timestamp fields) in contract.yaml."""
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    doc = _load_yaml(contract_path) or {}
    if not isinstance(doc, dict):
        doc = {}
    tasks = doc.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
    task_id = payload.get("id")
    for t in tasks:
        if isinstance(t, dict) and t.get("id") == task_id:
            for k, v in payload.items():
                t[k] = v
            break
    doc["tasks"] = tasks
    _atomic_yaml_write(contract_path, doc)


def _apply_upsert_task(project_dir: str, payload: dict) -> None:
    """Sync a task upsert to contract.yaml."""
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    doc = _load_yaml(contract_path) or {}
    if not isinstance(doc, dict):
        doc = {}
    tasks = doc.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []

    task_id = payload.get("id")
    updated = False
    for i, t in enumerate(tasks):
        if isinstance(t, dict) and t.get("id") == task_id:
            tasks[i] = {**t, **payload}
            updated = True
            break
    if not updated:
        tasks.append(payload)
    doc["tasks"] = tasks
    _atomic_yaml_write(contract_path, doc)


def _apply_update_inbox(project_dir: str, payload: dict) -> None:
    """Sync an inbox status update to inbox.yaml."""
    from superharness.engine.inbox import _inbox_lock
    inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    with _inbox_lock(inbox_path):
        items = _load_yaml(inbox_path)
        if not isinstance(items, list):
            items = []

        item_id = payload.get("id")
        for i, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == item_id:
                items[i] = {**item, **payload}
                break
        _atomic_yaml_write(inbox_path, items)


def _apply_append_handoff(project_dir: str, payload: dict) -> None:
    """Append a handoff row to handoffs.yaml."""
    task_id = payload.get("task_id", "unknown")
    handoffs_path = os.path.join(project_dir, ".superharness", "handoffs", f"{task_id}.yaml")
    os.makedirs(os.path.dirname(handoffs_path), exist_ok=True)

    items = _load_yaml(handoffs_path)
    if not isinstance(items, list):
        items = []
    items.append(payload)
    _atomic_yaml_write(handoffs_path, items)


def _apply_record_failure(project_dir: str, payload: dict) -> None:
    """Append a failure to failures.yaml."""
    failures_path = os.path.join(project_dir, ".superharness", "failures.yaml")
    items = _load_yaml(failures_path)
    if not isinstance(items, list):
        items = []
    items.append(payload)
    _atomic_yaml_write(failures_path, items)


def _apply_record_decision(project_dir: str, payload: dict) -> None:
    """Append a decision to decisions.yaml."""
    decisions_path = os.path.join(project_dir, ".superharness", "decisions.yaml")
    items = _load_yaml(decisions_path)
    if not isinstance(items, list):
        items = []
    items.append(payload)
    _atomic_yaml_write(decisions_path, items)
