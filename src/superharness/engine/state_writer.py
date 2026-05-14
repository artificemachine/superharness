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


_ACTIVE_WORK_STATES = frozenset({"in_progress", "launched", "running", "waiting_input", "pending_user_approval"})


def _ensure_active_inbox(project_dir: str, task_id: str, owner: str, now: str) -> None:
    """Ensure an active inbox item exists for a task entering an active work state.

    Called by set_task_status when transitioning to in_progress, waiting_input, etc.
    Silently skipped if an active inbox item already exists for this task.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            existing = conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE task_id=? AND status IN ('pending','launched','running','paused')",
                (task_id,),
            ).fetchone()
            if not existing or existing[0] == 0:
                import uuid
                iid = f"auto-{uuid.uuid4().hex[:6]}"
                inbox_dao.enqueue(conn, id=iid, task_id=task_id,
                    target_agent=owner, priority=2, max_retries=3,
                    project_path=project_dir, plan_only=False, now=now)
                conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def set_task_status(
    project_dir: str,
    task_id: str,
    status: str,
    *,
    from_status: str | None = None,
    force: bool = False,
    **fields,
) -> bool:
    """Update a contract task's status via SQLite (post-YAML removal).

    SQLite is the only backend (is_sqlite_only is permanently true);
    no YAML write path exists. force=True bypasses the user-facing
    transition graph. The lifecycle reconciler uses it for system-driven
    moves (timeout → archived/failed) that are intentionally outside the
    normal interactive flow.
    """
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    now = _now_utc()
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        task_row = tasks_dao.get(conn, task_id)
        if not task_row:
            # Auto-ingest YAML fixtures the same way state_reader does, so
            # tests that seed contract.yaml then call set_task_status work.
            try:
                from superharness.engine.state_reader import _ensure_ingested
                _ensure_ingested(project_dir)
                task_row = tasks_dao.get(conn, task_id)
            except Exception:
                pass
        if not task_row:
            return False

        if from_status is not None and task_row.status != from_status:
            return False

        # Idempotent: setting the same status twice is a no-op success,
        # not a transition. Skip validation and the change set.
        if task_row.status == status:
            return True

        # Validate transition against legal status graph (skipped under force=True)
        if not force:
            try:
                from superharness.engine.next_action import validate_status_transition
                validate_status_transition(task_row.status, status)
            except ValueError as e:
                print(f"status transition rejected: {task_id}: {e}", file=sys.stderr)
                return False

        changes = {"status": status, "updated_at": now}

        # Lifecycle timestamps
        ts_map = {"plan_proposed": "plan_proposed_at", "plan_approved": "plan_approved_at", "in_progress": "in_progress_at", "report_ready": "report_ready_at", "done": "done_at", "failed": "failed_at", "stopped": "stopped_at", "archived": "archived_at", "waiting_input": "updated_at"}
        if status in ts_map: changes[ts_map[status]] = now

        # Contract lock: freeze acceptance_criteria + tdd at plan_approved time
        if status == "plan_approved" and not task_row.contract_locked_at:
            import json as _json
            snapshot = {
                "acceptance_criteria": task_row.acceptance_criteria,
                "tdd": task_row.tdd,
            }
            changes["locked_contract"] = _json.dumps(snapshot)
            changes["contract_locked_at"] = now

        changes.update(fields)
        tasks_dao.update(conn, task_id, version=task_row.version, changes=changes)
        conn.commit()

        # Write event stream
        try:
            from superharness.engine.event_stream import write_event
            write_event(project_dir, "status_change", task_id=task_id,
                        from_status=task_row.status, to_status=status)
        except Exception:
            pass

        # Auto-capture observation snapshot on report_ready transition.
        # Defensive: capture_observation never raises, but the import
        # could fail in unusual environments. project_dir is threaded
        # through so the rate limiter can use the cross-process
        # SQLite-backed bucket.
        if status == "report_ready":
            try:
                from superharness.engine.observation_capture import capture_observation
                capture_observation(conn, task_id, "report_ready", project_dir=project_dir)
            except Exception:
                pass

        # Guard: active states must have matching inbox item
        _ACTIVE_WORK = frozenset({"in_progress", "launched", "running", "waiting_input", "pending_user_approval"})
        if status in _ACTIVE_WORK:
            _ensure_active_inbox(project_dir, task_id, task_row.owner or "claude-code", now)

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
    """Update an inbox item's status via SQLite (post-YAML removal)."""
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
        from superharness.engine.sqlite_only import is_sqlite_only
        if not is_sqlite_only():
            _export_inbox_yaml(project_dir)
        return True
    except Exception:
        return False
    finally:
        conn.close()
def _export_contract_yaml(project_dir: str) -> None:
    """Regenerate contract.yaml from the current SQLite state (export only).

    In sqlite_only mode, skips the write entirely — YAML is generated
    only on explicit `shux export-yaml` command.
    """
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        if is_sqlite_only():
            return  # SQLite is SoT — YAML is not needed for runtime
        from superharness.engine import state_reader, contract_io
        doc = state_reader.get_contract_doc(project_dir)
        contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
        contract_io.write_contract(contract_path, doc)
    except Exception:
        pass


def _export_inbox_yaml(project_dir: str) -> None:
    """Regenerate inbox.yaml from the current SQLite state (export only).

    In sqlite_only mode, skips the write entirely — YAML is generated
    only on explicit `shux export-yaml` command.
    """
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        if is_sqlite_only():
            return  # SQLite is SoT — YAML is not needed for runtime
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




_KNOWN_TASK_COLS = frozenset({
    "title", "owner", "effort", "project_path",
    "development_method", "acceptance_criteria", "test_types",
    "out_of_scope", "definition_of_done", "context", "tdd",
    "created_at", "updated_at", "plan_proposed_at",
    "plan_approved_at", "in_progress_at", "report_ready_at",
    "review_requested_at", "done_at", "cancelled_at",
    "blocked_by_raw", "parent_id", "verified",
    "verified_at", "verified_by", "deadline_minutes",
    "failed_at", "stopped_at", "failed_reason", "archived_at",
    "archived_reason", "model_tier", "pause_reason", "worktree_path",
    "workflow", "autonomy", "require_tdd", "estimated_minutes",
    "locked_contract", "contract_locked_at",
})
# Fields to skip entirely — either handled elsewhere or not real task columns.
_SKIP_TASK_FIELDS = frozenset({"id", "status", "version", "blocked_by", "depends_on", "extras_json"})


def _mirror_task_to_sqlite(project_dir: str, task_id: str, status: str, **fields) -> None:
    """Best-effort SQLite sync from state_writer.

    Unknown fields (not real task columns) are merged into extras_json so
    they survive round-trips through SQLite without silently failing.
    """
    try:
        import json as _j
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = tasks_dao.get(conn, task_id)
            if row:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                changes: dict = {"status": status, "updated_at": now}
                ts_map = {"plan_proposed": "plan_proposed_at", "plan_approved": "plan_approved_at", "in_progress": "in_progress_at", "report_ready": "report_ready_at", "done": "done_at", "failed": "failed_at", "stopped": "stopped_at"}
                if status in ts_map:
                    changes[ts_map[status]] = now
                # Separate known columns from extras
                extras: dict = {}
                for k, v in fields.items():
                    if k in _SKIP_TASK_FIELDS:
                        continue
                    elif k in _KNOWN_TASK_COLS:
                        changes[k] = v
                    else:
                        extras[k] = v
                # Merge extras into existing extras_json blob
                if extras:
                    existing_extras: dict = {}
                    if row.extras_json:
                        try:
                            existing_extras = _j.loads(row.extras_json) or {}
                        except Exception:
                            pass
                    existing_extras.update(extras)
                    changes["extras_json"] = _j.dumps(existing_extras)
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
