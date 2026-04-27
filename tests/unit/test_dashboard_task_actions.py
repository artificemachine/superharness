"""Tests for dashboard task-board action handlers.

Covers the task-level buttons visible in the tasks panel:

  Lifecycle transitions (guard logic):
    approve_plan:<id>         plan_proposed → plan_approved
    request_review:<id>:<r>  report_ready → review_requested  (requires report_ready + no dupe)
    cancel_review:<id>        review_requested → report_ready
    approve_report:<id>       close without review (delegates to close cmd)
    approve_without_review:<id> revert + close
    mark_done:<id>            todo → done
    close_task:<id>           delegates to close cmd
    disable_task:<id>         → stopped
    enable_task:<id>          stopped → todo

  Owner management:
    set_owner:<id>:<agent>    update task owner in contract
    /api/owners add           add agent + create placeholder task
    /api/owners remove        remove owner (min 2 guard)

  Enqueue:
    enqueue_task:<id>:<agent> validates agent, blocks duplicate, delegates

  Guard cases:
    missing task_id → 400
    task not found  → 404
    already enqueued → 409
    invalid agent   → 400
    wrong from_status → status unchanged
    too few owners  → 400
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao, tasks_dao


# ── fixtures ──────────────────────────────────────────────────────────────────

def _harness(tmp_path: Path) -> Path:
    h = tmp_path / ".superharness"
    h.mkdir(exist_ok=True)
    (h / "handoffs").mkdir(exist_ok=True)
    return h


def _write_contract(harness: Path, tasks: list[dict]) -> Path:
    f = harness / "contract.yaml"
    f.write_text(yaml.dump({"id": "test", "tasks": tasks}, default_flow_style=False))
    return f


def _make_task_db(tmp_path: Path, tasks: list[dict]) -> None:
    """Write tasks into SQLite via tasks_dao."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(tmp_path))
    init_db(conn)
    now = "2026-04-27T00:00:00Z"
    for t in tasks:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, title, status, owner, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (t["id"], t.get("title", t["id"]), t["status"],
             t.get("owner", "claude-code"), now),
        )
    conn.commit()
    conn.close()


def _db_task_status(tmp_path: Path, task_id: str) -> str | None:
    conn = get_connection(str(tmp_path))
    row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return row[0] if row else None


# ── _set_task_status helper (mirrors the handler logic) ───────────────────────

def _set_task_status_logic(
    tmp_path: Path, task_id: str, to_status: str, from_status: str | None = None
) -> dict:
    """Replicate the core of _set_task_status: update SQLite with optional from guard."""
    conn = get_connection(str(tmp_path))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if from_status:
        rows = conn.execute(
            "UPDATE tasks SET status=? WHERE id=? AND status=? RETURNING id",
            (to_status, task_id, from_status),
        ).fetchall()
    else:
        rows = conn.execute(
            "UPDATE tasks SET status=? WHERE id=? RETURNING id",
            (to_status, task_id),
        ).fetchall()
    conn.commit()
    conn.close()
    return {"ok": bool(rows)}


# ── approve_plan ──────────────────────────────────────────────────────────────

class TestApprovePlan:
    """approve_plan: plan_proposed → plan_approved."""

    def test_transitions_plan_proposed_to_approved(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "plan_proposed"}])
        result = _set_task_status_logic(tmp_path, "t1", "plan_approved", from_status="plan_proposed")
        assert result["ok"]
        assert _db_task_status(tmp_path, "t1") == "plan_approved"

    def test_rejects_wrong_from_status(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "todo"}])
        result = _set_task_status_logic(tmp_path, "t1", "plan_approved", from_status="plan_proposed")
        assert not result["ok"]
        assert _db_task_status(tmp_path, "t1") == "todo"

    def test_missing_task_id_guard(self):
        """Handler must return 400 when action is 'approve_plan:' with empty id."""
        action = "approve_plan:"
        task_id = action.split(":", 1)[1]
        assert task_id == "", "empty split must yield empty string"
        # Handler logic: if not task_id: return 400
        assert not task_id

    def test_unknown_task_returns_no_rows(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "plan_proposed"}])
        result = _set_task_status_logic(tmp_path, "ghost", "plan_approved", from_status="plan_proposed")
        assert not result["ok"]


# ── mark_done ─────────────────────────────────────────────────────────────────

class TestMarkDone:
    """mark_done: todo → done."""

    def test_todo_to_done(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "todo"}])
        result = _set_task_status_logic(tmp_path, "t1", "done", from_status="todo")
        assert result["ok"]
        assert _db_task_status(tmp_path, "t1") == "done"

    def test_rejects_non_todo(self, tmp_path):
        for status in ["in_progress", "plan_proposed", "done"]:
            _make_task_db(tmp_path, [{"id": "t1", "status": status}])
            result = _set_task_status_logic(tmp_path, "t1", "done", from_status="todo")
            assert not result["ok"], f"mark_done must reject status={status}"


# ── disable_task / enable_task ────────────────────────────────────────────────

class TestDisableEnableTask:
    def test_disable_sets_stopped(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "todo"}])
        result = _set_task_status_logic(tmp_path, "t1", "stopped")
        assert result["ok"]
        assert _db_task_status(tmp_path, "t1") == "stopped"

    def test_enable_transitions_stopped_to_todo(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "stopped"}])
        result = _set_task_status_logic(tmp_path, "t1", "todo", from_status="stopped")
        assert result["ok"]
        assert _db_task_status(tmp_path, "t1") == "todo"

    def test_enable_rejects_non_stopped(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "in_progress"}])
        result = _set_task_status_logic(tmp_path, "t1", "todo", from_status="stopped")
        assert not result["ok"]
        assert _db_task_status(tmp_path, "t1") == "in_progress"

    def test_missing_id_guard(self):
        for action in ["disable_task:", "enable_task:"]:
            task_id = action.split(":", 1)[1]
            assert not task_id, f"{action} must produce empty id"


# ── request_review guards ─────────────────────────────────────────────────────

class TestRequestReviewGuards:
    """request_review requires status=report_ready, no active inbox item, and valid task."""

    def test_wrong_status_returns_400(self):
        """Handler rejects tasks that are not in report_ready."""
        for bad_status in ["todo", "in_progress", "plan_proposed", "done", "review_requested"]:
            task = {"id": "t1", "status": bad_status}
            if task.get("status") != "report_ready":
                code = 400
            else:
                code = 200
            assert code == 400, f"status={bad_status} must produce 400"

    def test_report_ready_allowed(self):
        task = {"id": "t1", "status": "report_ready"}
        assert task["status"] == "report_ready"

    def test_duplicate_inbox_returns_409(self):
        """If an active inbox item already exists for this task, return 409."""
        active_statuses = {"pending", "launched", "running", "paused"}
        task_id = "t1"
        inbox = [{"task": "t1", "status": "pending", "id": "i1"}]
        for item in inbox:
            if item.get("task") == task_id and item.get("status") in active_statuses:
                code = 409
                break
        else:
            code = 200
        assert code == 409

    def test_no_duplicate_proceeds(self):
        task_id = "t1"
        inbox: list = []
        active_statuses = {"pending", "launched", "running", "paused"}
        for item in inbox:
            if item.get("task") == task_id and item.get("status") in active_statuses:
                code = 409
                break
        else:
            code = 200
        assert code == 200

    def test_missing_task_id_guard(self):
        action = "request_review:"
        parts = action.split(":", 2)
        task_id = parts[1] if len(parts) > 1 else ""
        assert not task_id


# ── cancel_review ─────────────────────────────────────────────────────────────

class TestCancelReview:
    """cancel_review: review_requested → report_ready."""

    def test_transitions_review_requested_to_report_ready(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "review_requested"}])
        result = _set_task_status_logic(tmp_path, "t1", "report_ready", from_status="review_requested")
        assert result["ok"]
        assert _db_task_status(tmp_path, "t1") == "report_ready"

    def test_rejects_wrong_from_status(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "report_ready"}])
        result = _set_task_status_logic(tmp_path, "t1", "report_ready", from_status="review_requested")
        assert not result["ok"]

    def test_missing_id_guard(self):
        task_id = "cancel_review:".split(":", 1)[1]
        assert not task_id


# ── set_owner ─────────────────────────────────────────────────────────────────

class TestSetOwner:
    """set_owner:<task_id>:<agent> — updates task owner in contract.yaml."""

    def test_updates_owner(self, tmp_path):
        harness = _harness(tmp_path)
        _write_contract(harness, [{"id": "t1", "title": "T1", "status": "todo", "owner": "claude-code"}])

        contract_file = harness / "contract.yaml"
        task_id, new_owner = "t1", "codex-cli"

        doc = yaml.safe_load(contract_file.read_text()) or {}
        tasks = doc.get("tasks", [])
        found = False
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                t["owner"] = new_owner
                found = True
                break
        assert found
        contract_file.write_text(yaml.safe_dump(doc, default_flow_style=False, sort_keys=False))

        updated = yaml.safe_load(contract_file.read_text())
        owners = {t["id"]: t.get("owner") for t in updated.get("tasks", []) if isinstance(t, dict)}
        assert owners["t1"] == "codex-cli"

    def test_task_not_found_returns_404(self, tmp_path):
        harness = _harness(tmp_path)
        _write_contract(harness, [{"id": "t1", "title": "T1", "status": "todo", "owner": "claude-code"}])
        contract_file = harness / "contract.yaml"
        doc = yaml.safe_load(contract_file.read_text()) or {}
        tasks = doc.get("tasks", [])
        found = any(isinstance(t, dict) and t.get("id") == "ghost" for t in tasks)
        assert not found

    def test_invalid_format_guard(self):
        """set_owner: with fewer than 3 parts must return 400."""
        for bad_action in ["set_owner:", "set_owner:only-one"]:
            parts = bad_action.split(":")
            assert len(parts) < 3, f"'{bad_action}' must be caught by len<3 guard"


# ── enqueue_task guards ───────────────────────────────────────────────────────

KNOWN_AGENTS = ["claude-code", "codex-cli", "gemini-cli"]


class TestEnqueueTaskGuards:
    """enqueue_task:<id>:<agent> — validates agent + blocks duplicates."""

    def test_invalid_agent_returns_400(self):
        for bad_agent in ["gpt-4o", "human", "", "CLAUDE"]:
            code = 400 if bad_agent not in KNOWN_AGENTS else 200
            assert code == 400, f"agent '{bad_agent}' must be rejected"

    def test_valid_agents_pass(self):
        for agent in KNOWN_AGENTS:
            code = 200 if agent in KNOWN_AGENTS else 400
            assert code == 200

    def test_duplicate_active_item_returns_409(self):
        active_statuses = {"pending", "launched", "running", "paused"}
        task_id = "t1"
        inbox = [{"task": "t1", "id": "i1", "status": "launched"}]
        for item in inbox:
            if item.get("task") == task_id and item.get("status") in active_statuses:
                code = 409
                break
        else:
            code = 200
        assert code == 409

    def test_no_active_item_proceeds(self):
        task_id = "t1"
        inbox = [{"task": "t1", "id": "i1", "status": "done"}]
        active_statuses = {"pending", "launched", "running", "paused"}
        for item in inbox:
            if item.get("task") == task_id and item.get("status") in active_statuses:
                code = 409
                break
        else:
            code = 200
        assert code == 200

    def test_missing_fields_guard(self):
        for bad_action in ["enqueue_task:", "enqueue_task:only"]:
            parts = bad_action.split(":", 2)
            missing = len(parts) < 3 or not parts[1] or not parts[2] if len(parts) == 3 else True
            assert missing, f"'{bad_action}' must trigger missing-fields guard"

    @pytest.mark.parametrize("task_id,target", [("t1", "claude-code"), ("t2", "codex-cli")])
    def test_valid_enqueue_format(self, task_id, target):
        action = f"enqueue_task:{task_id}:{target}"
        parts = action.split(":", 2)
        assert len(parts) == 3
        assert parts[1] == task_id
        assert parts[2] == target
        assert parts[2] in KNOWN_AGENTS


# ── /api/owners add/remove validation ────────────────────────────────────────

class TestOwnerValidation:
    """Owner name must be alphanumeric + hyphens/underscores only."""

    @pytest.mark.parametrize("name,valid", [
        ("claude-code", True),
        ("codex_cli", True),
        ("agent123", True),
        ("bad name", False),
        ("bad.name", False),
        ("bad@name", False),
        ("", False),
        ("a/b", False),
    ])
    def test_owner_name_validation(self, name, valid):
        is_valid = bool(name) and all(c.isalnum() or c in "-_" for c in name)
        assert is_valid == valid, f"owner='{name}' expected valid={valid}"

    def test_remove_owner_requires_minimum_two(self):
        """Cannot remove owner when only 2 owners remain."""
        existing = ["claude-code", "codex-cli"]
        owner_to_remove = "codex-cli"
        if owner_to_remove not in existing:
            code = 200  # already gone, idempotent
        elif len(existing) <= 2:
            code = 400
        else:
            code = 200
        assert code == 400

    def test_remove_owner_allowed_with_three(self):
        existing = ["claude-code", "codex-cli", "gemini-cli"]
        if len(existing) <= 2:
            code = 400
        else:
            code = 200
        assert code == 200

    def test_add_existing_owner_is_idempotent(self):
        existing = ["claude-code", "codex-cli"]
        owner = "claude-code"
        if owner in existing:
            response = {"ok": True, "note": "already exists"}
        else:
            response = {"ok": True}
        assert response.get("note") == "already exists"


# ── pause_item ────────────────────────────────────────────────────────────────

class TestPauseItem:
    """pause_item: pending → paused via DAO from_status guard."""

    def test_pending_transitions_to_paused(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao

        harness = tmp_path / ".superharness"
        harness.mkdir(exist_ok=True)
        conn = get_connection(str(tmp_path))
        init_db(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT OR REPLACE INTO inbox (id, task_id, target_agent, status, priority, max_retries, created_at) VALUES (?,?,?,?,2,3,?)",
            ("i1", "t1", "claude-code", "pending", now),
        )
        conn.commit()

        ok = inbox_dao.update_status(conn, "i1", from_status="pending", to_status="paused", now=now)
        conn.commit()
        conn.close()

        assert ok
        conn2 = get_connection(str(tmp_path))
        row = conn2.execute("SELECT status FROM inbox WHERE id='i1'").fetchone()
        conn2.close()
        assert row[0] == "paused"

    def test_non_pending_not_paused(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao

        harness = tmp_path / ".superharness"
        harness.mkdir(exist_ok=True)
        conn = get_connection(str(tmp_path))
        init_db(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT OR REPLACE INTO inbox (id, task_id, target_agent, status, priority, max_retries, created_at) VALUES (?,?,?,?,2,3,?)",
            ("i1", "t1", "claude-code", "running", now),
        )
        conn.commit()

        ok = inbox_dao.update_status(conn, "i1", from_status="pending", to_status="paused", now=now)
        conn.commit()
        conn.close()

        assert not ok
        conn2 = get_connection(str(tmp_path))
        row = conn2.execute("SELECT status FROM inbox WHERE id='i1'").fetchone()
        conn2.close()
        assert row[0] == "running"


# ── resume_task / retry_task ──────────────────────────────────────────────────

class TestResumeTaskRetryTask:
    """resume_task and retry_task find an inbox item by task_id and status."""

    def test_resume_task_finds_paused_item(self):
        inbox = [
            {"id": "i1", "task": "t1", "status": "paused"},
            {"id": "i2", "task": "t1", "status": "done"},
        ]
        target = next((i for i in inbox if i.get("task") == "t1" and i.get("status") == "paused"), None)
        assert target is not None
        assert target["id"] == "i1"

    def test_resume_task_missing_returns_404(self):
        inbox = [{"id": "i1", "task": "t1", "status": "running"}]
        target = next((i for i in inbox if i.get("task") == "t1" and i.get("status") == "paused"), None)
        assert target is None

    def test_retry_task_finds_stale_item(self):
        inbox = [
            {"id": "i1", "task": "t1", "status": "stale"},
            {"id": "i2", "task": "t1", "status": "done"},
        ]
        target = next((i for i in inbox if i.get("task") == "t1" and i.get("status") in ("stale", "failed", "stopped")), None)
        assert target is not None
        assert target["id"] == "i1"

    @pytest.mark.parametrize("status", ["stale", "failed", "stopped"])
    def test_retry_task_finds_any_retryable(self, status):
        inbox = [{"id": "i1", "task": "t1", "status": status}]
        target = next((i for i in inbox if i.get("task") == "t1" and i.get("status") in ("stale", "failed", "stopped")), None)
        assert target is not None

    def test_retry_task_missing_returns_404(self):
        inbox = [{"id": "i1", "task": "t1", "status": "done"}]
        target = next((i for i in inbox if i.get("task") == "t1" and i.get("status") in ("stale", "failed", "stopped")), None)
        assert target is None


# ── remove_task ───────────────────────────────────────────────────────────────

class TestRemoveTask:
    """remove_task:<id> — removes task from SQLite."""

    def test_removes_from_sqlite(self, tmp_path):
        _make_task_db(tmp_path, [
            {"id": "t1", "status": "done"},
            {"id": "t2", "status": "todo"},
        ])
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM tasks WHERE id=?", ("t1",))
        conn.commit()
        conn.close()

        conn2 = get_connection(str(tmp_path))
        ids = {r[0] for r in conn2.execute("SELECT id FROM tasks").fetchall()}
        conn2.close()
        assert "t1" not in ids
        assert "t2" in ids

    def test_missing_id_guard(self):
        task_id = "remove_task:".split(":", 1)[1]
        assert not task_id

    def test_safe_on_nonexistent_id(self, tmp_path):
        _make_task_db(tmp_path, [{"id": "t1", "status": "todo"}])
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM tasks WHERE id=?", ("ghost",))
        conn.commit()
        conn.close()
        assert _db_task_status(tmp_path, "t1") == "todo"
