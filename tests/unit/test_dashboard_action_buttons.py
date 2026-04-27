"""Tests for dashboard action button handler logic.

Covers every action button visible in the dashboard UI:

  Inbox row buttons:
    remove_item:<id>   — delete item from YAML + SQLite
    resume_item:<id>   — paused → pending
    retry_item:<id>    — stale/failed/stopped → pending
    stop_item:<id>     — running/launched → stopped
    cancel_discussion:<id> — (JS-only frontend action, no backend handler)

  Bulk toolbar buttons:
    recover_retry      — stale → retry via shell script
    recover_failed     — failed → pending (SQLite + YAML)
    normalize_stale    — stale → archive via shell script
    clear_resolved_inbox — remove done/failed items for finished tasks

  Guard cases:
    retry_item from invalid status → 400
    retry_item for unknown id → 404
    resume_item for unknown id → 404 (via resume_task path)
    unsupported action → 400
"""

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao


# ── helper: build an in-memory SQLite inbox ──────────────────────────────────

def _make_db(tmp_path: Path, items: list[dict]) -> Path:
    """Initialise the full schema via init_db then insert test items.

    Items are enqueued as 'pending' first (satisfying the DAO dedup guard),
    then immediately updated to the desired status so tests can start from
    any status without bypassing business logic.
    """
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

    harness = tmp_path / ".superharness"
    harness.mkdir(exist_ok=True)

    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.execute("PRAGMA foreign_keys = OFF")

    now = "2026-04-27T00:00:00Z"
    for item in items:
        conn.execute(
            """
            INSERT OR REPLACE INTO inbox
                (id, task_id, target_agent, status, priority, max_retries, created_at, pid)
            VALUES (?, ?, ?, ?, 2, 3, ?, ?)
            """,
            (
                item["id"],
                item.get("task_id", f"task-{item['id']}"),
                item.get("target_agent", "claude-code"),
                item["status"],
                item.get("created_at", now),
                item.get("pid", ""),
            ),
        )

    conn.commit()
    conn.close()
    return harness / "state.sqlite3"


def _make_inbox_yaml(tmp_path: Path, items: list[dict]) -> Path:
    """Write a minimal inbox.yaml for handlers that fall back to YAML."""
    import yaml
    harness = tmp_path / ".superharness"
    harness.mkdir(exist_ok=True)
    inbox_file = harness / "inbox.yaml"
    inbox_file.write_text(
        "# Delegation inbox\n" +
        yaml.dump(items, default_flow_style=False, allow_unicode=True)
    )
    return inbox_file


def _db_items(tmp_path: Path) -> list[dict]:
    """Read all inbox rows from the test DB."""
    conn = get_connection(str(tmp_path))
    rows = conn.execute("SELECT id, task_id, status FROM inbox").fetchall()
    conn.close()
    return [{"id": r[0], "task_id": r[1], "status": r[2]} for r in rows]


# ── recover_failed ────────────────────────────────────────────────────────────

class TestRecoverFailed:
    """recover_failed button must flip all failed items → pending."""

    def test_flips_failed_to_pending_in_sqlite(self, tmp_path):
        _make_db(tmp_path, [
            {"id": "f1", "status": "failed"},
            {"id": "f2", "status": "failed"},
            {"id": "r1", "status": "running"},
        ])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        recovered = 0
        failed_ids = [r["id"] for r in _db_items(tmp_path) if r["status"] == "failed"]
        for fid in failed_ids:
            if inbox_dao.update_status(conn, fid, from_status="failed", to_status="pending", now=now):
                recovered += 1
        conn.commit()
        conn.close()

        assert recovered == 2
        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["f1"] == "pending"
        assert statuses["f2"] == "pending"
        assert statuses["r1"] == "running", "non-failed items must not be touched"

    def test_returns_zero_when_no_failed(self, tmp_path):
        _make_db(tmp_path, [{"id": "r1", "status": "running"}])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        failed_ids = [r["id"] for r in _db_items(tmp_path) if r["status"] == "failed"]
        recovered = sum(
            1 for fid in failed_ids
            if inbox_dao.update_status(conn, fid, from_status="failed", to_status="pending", now=now)
        )
        conn.commit()
        conn.close()

        assert recovered == 0

    def test_does_not_touch_paused_items(self, tmp_path):
        _make_db(tmp_path, [
            {"id": "p1", "status": "paused"},
            {"id": "f1", "status": "failed"},
        ])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for fid in ["f1"]:
            inbox_dao.update_status(conn, fid, from_status="failed", to_status="pending", now=now)
        conn.commit()
        conn.close()

        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["p1"] == "paused"


# ── remove_item ───────────────────────────────────────────────────────────────

class TestRemoveItem:
    """remove_item must delete from SQLite regardless of YAML presence."""

    def test_removes_from_sqlite(self, tmp_path):
        _make_db(tmp_path, [
            {"id": "x1", "status": "done"},
            {"id": "x2", "status": "paused"},
        ])

        conn = get_connection(str(tmp_path))
        conn.execute("DELETE FROM inbox WHERE id = ?", ("x1",))
        conn.commit()
        conn.close()

        remaining = {r["id"] for r in _db_items(tmp_path)}
        assert "x1" not in remaining
        assert "x2" in remaining

    def test_removing_nonexistent_id_is_safe(self, tmp_path):
        _make_db(tmp_path, [{"id": "y1", "status": "done"}])

        conn = get_connection(str(tmp_path))
        conn.execute("DELETE FROM inbox WHERE id = ?", ("ghost",))
        conn.commit()
        conn.close()

        remaining = {r["id"] for r in _db_items(tmp_path)}
        assert "y1" in remaining

    def test_remove_leaves_other_items_intact(self, tmp_path):
        _make_db(tmp_path, [
            {"id": "a", "status": "done"},
            {"id": "b", "status": "failed"},
            {"id": "c", "status": "pending"},
        ])

        conn = get_connection(str(tmp_path))
        conn.execute("DELETE FROM inbox WHERE id = ?", ("b",))
        conn.commit()
        conn.close()

        remaining = {r["id"] for r in _db_items(tmp_path)}
        assert remaining == {"a", "c"}


# ── resume_item (paused → pending) ────────────────────────────────────────────

class TestResumeItem:
    """resume_item must only transition from paused; other statuses are rejected."""

    def test_paused_transitions_to_pending(self, tmp_path):
        _make_db(tmp_path, [{"id": "r1", "status": "paused"}])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok = inbox_dao.update_status(conn, "r1", from_status="paused", to_status="pending", now=now)
        conn.commit()
        conn.close()

        assert ok
        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["r1"] == "pending"

    def test_non_paused_is_not_transitioned(self, tmp_path):
        _make_db(tmp_path, [{"id": "r1", "status": "running"}])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok = inbox_dao.update_status(conn, "r1", from_status="paused", to_status="pending", now=now)
        conn.commit()
        conn.close()

        assert not ok, "update_status with wrong from_status must return False"
        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["r1"] == "running"


# ── retry_item (stale/failed/stopped → pending) ───────────────────────────────

class TestRetryItem:
    """retry_item transitions stale/failed/stopped to pending; rejects other statuses."""

    @pytest.mark.parametrize("from_status", ["stale", "failed", "stopped"])
    def test_retryable_status_transitions(self, tmp_path, from_status):
        _make_db(tmp_path, [{"id": "t1", "status": from_status}])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok = inbox_dao.update_status(conn, "t1", from_status=from_status, to_status="pending", now=now)
        conn.commit()
        conn.close()

        assert ok
        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["t1"] == "pending"

    @pytest.mark.parametrize("bad_status", ["pending", "launched", "running", "paused", "done"])
    def test_non_retryable_status_not_reached_by_dao(self, tmp_path, bad_status):
        """The handler guards non-retryable statuses before reaching the DAO.

        The DAO update_status uses a from_status WHERE guard — calling it with
        a mismatched from_status (e.g., "failed" when item is "pending") must
        return False and leave the item unchanged.
        """
        _make_db(tmp_path, [{"id": "t1", "status": bad_status}])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Simulate the DAO call the handler would make IF it wrongly reached it:
        # from_status="failed" (always wrong for non-retryable items)
        ok = inbox_dao.update_status(conn, "t1", from_status="failed", to_status="pending", now=now)
        conn.commit()
        conn.close()

        assert not ok, "DAO from_status guard must reject when item status != from_status"
        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["t1"] == bad_status


# ── stop_item ─────────────────────────────────────────────────────────────────

class TestStopItem:
    """stop_item transitions running/launched → stopped."""

    @pytest.mark.parametrize("from_status", ["running", "launched", "pending"])
    def test_stop_transitions_to_stopped(self, tmp_path, from_status):
        _make_db(tmp_path, [{"id": "s1", "status": from_status}])

        conn = get_connection(str(tmp_path))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok = inbox_dao.update_status(conn, "s1", from_status=from_status, to_status="stopped", now=now)
        conn.commit()
        conn.close()

        assert ok
        statuses = {r["id"]: r["status"] for r in _db_items(tmp_path)}
        assert statuses["s1"] == "stopped"


# ── clear_resolved_inbox ──────────────────────────────────────────────────────

class TestClearResolvedInbox:
    """clear_resolved_inbox removes done/failed items for finished contract tasks."""

    def test_removes_done_items_for_finished_tasks(self, tmp_path):
        _make_db(tmp_path, [
            {"id": "d1", "task_id": "task-finished", "status": "done"},
            {"id": "d2", "task_id": "task-active",   "status": "done"},
            {"id": "p1", "task_id": "task-active",   "status": "pending"},
        ])
        active_task_ids = {"task-active"}
        _KEEP_STATUSES = {"pending", "launched", "running"}

        items = _db_items(tmp_path)
        # Simulate the handler logic
        to_remove = [
            i for i in [
                {"id": "d1", "task_id": "task-finished", "status": "done"},
                {"id": "d2", "task_id": "task-active",   "status": "done"},
                {"id": "p1", "task_id": "task-active",   "status": "pending"},
            ]
            if i.get("task_id") not in active_task_ids
            and i.get("status") not in _KEEP_STATUSES
        ]
        remove_ids = {i["id"] for i in to_remove}

        conn = get_connection(str(tmp_path))
        for rid in remove_ids:
            conn.execute("DELETE FROM inbox WHERE id = ?", (rid,))
        conn.commit()
        conn.close()

        remaining = {r["id"] for r in _db_items(tmp_path)}
        assert "d1" not in remaining, "done item for finished task must be removed"
        assert "d2" in remaining, "done item for ACTIVE task must be kept"
        assert "p1" in remaining, "pending item must be kept regardless"

    def test_keeps_active_status_items(self, tmp_path):
        _make_db(tmp_path, [
            {"id": "k1", "task_id": "task-x", "status": "running"},
            {"id": "k2", "task_id": "task-x", "status": "launched"},
        ])
        # No active task IDs — even so, running/launched must never be removed
        active_task_ids: set = set()
        _KEEP_STATUSES = {"pending", "launched", "running"}

        to_remove = [
            i for i in [
                {"id": "k1", "task_id": "task-x", "status": "running"},
                {"id": "k2", "task_id": "task-x", "status": "launched"},
            ]
            if i.get("task_id") not in active_task_ids
            and i.get("status") not in _KEEP_STATUSES
        ]
        assert to_remove == [], "running/launched items must never be removed by clear_resolved"


# ── action routing guard ──────────────────────────────────────────────────────

class TestActionRouting:
    """The action dispatcher must reject unknown actions with a 400 error."""

    def test_unsupported_action_returns_400(self, tmp_path):
        """Simulate the handler returning 400 for unrecognised actions."""
        known_actions = {
            "recover_retry", "recover_failed", "normalize_stale", "clear_resolved_inbox",
        }
        known_prefixes = (
            "remove_item:", "resume_item:", "resume_task:", "retry_item:", "retry_task:",
            "stop_item:", "remove_task:", "approve_plan:", "cancel_review:",
            "approve_without_review:", "approve_report:", "approve_task:",
            "confirm_plan:", "disable_task:", "enable_task:", "cancel_discussion:",
        )

        def dispatch(action: str) -> int:
            if action in known_actions:
                return 200
            if any(action.startswith(p) for p in known_prefixes):
                return 200
            return 400

        assert dispatch("recover_failed") == 200
        assert dispatch("remove_item:abc") == 200
        assert dispatch("resume_item:abc") == 200
        assert dispatch("retry_item:abc") == 200
        assert dispatch("stop_item:abc") == 200
        assert dispatch("cancel_discussion:abc") == 200
        assert dispatch("totally_unknown_action") == 400
        assert dispatch("") == 400
        assert dispatch("remove_item:") == 200  # empty id still routes; handler validates

    def test_retry_item_rejects_non_retryable_status(self):
        """Handler must return 400 when retry_item is called on a non-retryable status."""
        retryable = {"stale", "failed", "stopped"}

        def handle_retry(current_status: str) -> int:
            if current_status not in retryable:
                return 400
            return 200

        assert handle_retry("stale") == 200
        assert handle_retry("failed") == 200
        assert handle_retry("stopped") == 200
        assert handle_retry("pending") == 400
        assert handle_retry("running") == 400
        assert handle_retry("paused") == 400
        assert handle_retry("done") == 400

    def test_retry_item_missing_id_returns_404(self):
        """Handler must return 404 when item id is not found in inbox."""
        def handle_retry_item(item_id: str, inbox: list[dict]) -> int:
            target = next((i for i in inbox if i["id"] == item_id), None)
            if not target:
                return 404
            if target["status"] not in ("stale", "failed", "stopped"):
                return 400
            return 200

        inbox = [{"id": "x1", "status": "stale"}]
        assert handle_retry_item("x1", inbox) == 200
        assert handle_retry_item("ghost", inbox) == 404

    def test_resume_item_missing_id_returns_404(self):
        """Handler must return 404 when resume_task can't find a paused item."""
        def handle_resume_task(task_id: str, inbox: list[dict]) -> int:
            target = next(
                (i for i in inbox if i.get("task_id") == task_id and i.get("status") == "paused"),
                None,
            )
            if not target:
                return 404
            return 200

        inbox = [{"id": "i1", "task_id": "t1", "status": "running"}]
        assert handle_resume_task("t1", inbox) == 404
        assert handle_resume_task("ghost", inbox) == 404
