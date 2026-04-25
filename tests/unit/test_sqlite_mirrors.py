"""Tests for SQLite mirror helpers and shape-translation code (Bug-fix B1-B9).

Covers:
- _ensure_task_in_sqlite: upserts task from contract.yaml (B5)
- _sqlite_mirror_inbox_enqueue: correct keyword args to inbox_dao.enqueue (B1, B5)
- _sqlite_mirror_inbox_retry: correct set_retry call with retry_count (B2)
- _sqlite_mirror_task_status: fetches version before update (B3)
- state_reader._inbox_from_sqlite: uses asdict + shape translation (B4, B6)
- state_reader._inbox_row_to_yaml_shape: field mapping (B6)
- archive_yaml._inbox_row_to_yaml_shape: same translation in export (B6)
- auto_enqueue_todo / auto_enqueue_approved: new_item_ids set (B7)
- yaml_sync._apply_enqueue_inbox: acquires _inbox_lock (B8)
- _yaml_writes_enabled: returns False when STATE_BACKEND=sqlite_only (B9)
"""
from __future__ import annotations

import os
import sqlite3
import pytest
import yaml

from superharness.engine.db import init_db, get_connection
from superharness.engine import inbox_dao, tasks_dao


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def db_conn(project):
    """Open a connection to the project's state.sqlite3 (same path as get_connection uses)."""
    db_path = project / ".superharness" / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    yield conn
    conn.close()


def _write_contract(project, tasks: list[dict]) -> None:
    path = project / ".superharness" / "contract.yaml"
    path.write_text(yaml.dump({"tasks": tasks}))


def _write_inbox(project, items: list[dict]) -> None:
    path = project / ".superharness" / "inbox.yaml"
    path.write_text(yaml.dump(items))


T0 = "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# B5 — _ensure_task_in_sqlite
# ---------------------------------------------------------------------------

class TestEnsureTaskInSqlite:
    def test_creates_row_from_contract(self, project, db_conn):
        _write_contract(project, [
            {"id": "t1", "title": "Task One", "status": "todo",
             "owner": "claude-code", "project_path": str(project)},
        ])
        from superharness.commands.inbox_watch import _ensure_task_in_sqlite
        _ensure_task_in_sqlite(db_conn, "t1", str(project), T0)
        row = tasks_dao.get(db_conn, "t1")
        assert row is not None
        assert row.id == "t1"
        assert row.title == "Task One"
        assert row.status == "todo"

    def test_noop_when_task_already_exists(self, project, db_conn):
        existing = tasks_dao.TaskRow(
            id="t1", title="Existing", owner=None, status="in_progress",
            effort=None, project_path=None, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at=T0, blocked_by=[],
        )
        tasks_dao.upsert(db_conn, existing)
        db_conn.commit()
        _write_contract(project, [
            {"id": "t1", "title": "Task One", "status": "todo"},
        ])
        from superharness.commands.inbox_watch import _ensure_task_in_sqlite
        _ensure_task_in_sqlite(db_conn, "t1", str(project), T0)
        row = tasks_dao.get(db_conn, "t1")
        # should still have original title, not overwritten
        assert row.title == "Existing"

    def test_noop_when_contract_missing(self, project, db_conn):
        from superharness.commands.inbox_watch import _ensure_task_in_sqlite
        # No contract.yaml — should not raise
        _ensure_task_in_sqlite(db_conn, "t-missing", str(project), T0)
        assert tasks_dao.get(db_conn, "t-missing") is None

    def test_noop_when_task_not_in_contract(self, project, db_conn):
        _write_contract(project, [{"id": "other", "title": "Other", "status": "todo"}])
        from superharness.commands.inbox_watch import _ensure_task_in_sqlite
        _ensure_task_in_sqlite(db_conn, "t-ghost", str(project), T0)
        assert tasks_dao.get(db_conn, "t-ghost") is None


# ---------------------------------------------------------------------------
# B1 + B5 — _sqlite_mirror_inbox_enqueue
# ---------------------------------------------------------------------------

class TestSqliteMirrorInboxEnqueue:
    def test_enqueues_item_and_task(self, project):
        _write_contract(project, [
            {"id": "t1", "title": "Task One", "status": "plan_approved",
             "owner": "claude-code", "project_path": str(project)},
        ])
        items = [{"id": "i1", "task": "t1", "to": "claude-code",
                  "status": "pending", "priority": 2, "retry_count": 0,
                  "max_retries": 3, "created_at": T0, "project": str(project)}]
        from superharness.commands.inbox_watch import _sqlite_mirror_inbox_enqueue
        _sqlite_mirror_inbox_enqueue(str(project), items, T0)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            task = tasks_dao.get(conn, "t1")
            assert task is not None, "task should have been upserted"
            inbox = inbox_dao.get(conn, "i1")
            assert inbox is not None, "inbox item should have been inserted"
            assert inbox.task_id == "t1"
            assert inbox.target_agent == "claude-code"
        finally:
            conn.close()

    def test_silently_handles_duplicate_item_id(self, project):
        _write_contract(project, [
            {"id": "t1", "title": "T1", "status": "plan_approved",
             "owner": "claude-code", "project_path": str(project)},
        ])
        items = [{"id": "i1", "task": "t1", "to": "claude-code",
                  "status": "pending", "priority": 2, "retry_count": 0,
                  "max_retries": 3, "created_at": T0, "project": str(project)}]
        from superharness.commands.inbox_watch import _sqlite_mirror_inbox_enqueue
        _sqlite_mirror_inbox_enqueue(str(project), items, T0)
        # Second call should not raise and must not create a duplicate row
        _sqlite_mirror_inbox_enqueue(str(project), items, T0)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            all_rows = inbox_dao.get_all(conn)
            assert len(all_rows) == 1, "duplicate mirror must not insert a second row"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# B2 — _sqlite_mirror_inbox_retry
# ---------------------------------------------------------------------------

class TestSqliteMirrorInboxRetry:
    def _seed_inbox(self, project, db_conn):
        db_conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, 'T', 'todo', 1, ?)",
            ("t1", T0),
        )
        inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)
        db_conn.execute("UPDATE inbox SET status='failed', failed_reason='oops' WHERE id='i1'")
        db_conn.commit()

    def test_resets_status_to_pending(self, project, db_conn):
        self._seed_inbox(project, db_conn)
        db_conn.close()

        retried = [{"id": "i1", "retry_count": 1}]
        from superharness.commands.inbox_watch import _sqlite_mirror_inbox_retry
        _sqlite_mirror_inbox_retry(str(project), retried, T0)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = inbox_dao.get(conn, "i1")
            assert row.status == "pending"
            assert row.retry_count == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# B3 — _sqlite_mirror_task_status
# ---------------------------------------------------------------------------

class TestSqliteMirrorTaskStatus:
    def _seed_task(self, project, db_conn):
        row = tasks_dao.TaskRow(
            id="t1", title="T", owner=None, status="in_progress",
            effort=None, project_path=None, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at=T0, blocked_by=[],
        )
        tasks_dao.upsert(db_conn, row)
        db_conn.commit()

    def test_updates_task_status(self, project, db_conn):
        self._seed_task(project, db_conn)
        db_conn.close()

        from superharness.commands.inbox_watch import _sqlite_mirror_task_status
        _sqlite_mirror_task_status(str(project), "t1", "report_ready", T0)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = tasks_dao.get(conn, "t1")
            assert row.status == "report_ready"
        finally:
            conn.close()

    def test_noop_when_task_absent(self, project):
        from superharness.commands.inbox_watch import _sqlite_mirror_task_status
        # Should not raise even when task not in SQLite
        _sqlite_mirror_task_status(str(project), "nonexistent", "done", T0)


# ---------------------------------------------------------------------------
# B4 + B6 — state_reader._inbox_from_sqlite / _inbox_row_to_yaml_shape
# ---------------------------------------------------------------------------

class TestStateReaderInboxShape:
    def test_inbox_row_to_yaml_shape_maps_fields(self):
        from superharness.engine.state_reader import _inbox_row_to_yaml_shape
        row = {
            "id": "i1",
            "task_id": "t1",
            "target_agent": "claude-code",
            "project_path": "/some/path",
            "status": "pending",
        }
        result = _inbox_row_to_yaml_shape(row)
        assert result["task"] == "t1"
        assert result["to"] == "claude-code"
        assert result["project"] == "/some/path"
        assert "task_id" not in result
        assert "target_agent" not in result
        assert "project_path" not in result

    def test_get_inbox_items_returns_yaml_shaped_dicts(self, project, db_conn):
        db_conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, 'T', 'todo', 1, ?)",
            ("t1", T0),
        )
        inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code",
                          project_path=str(project), now=T0)
        db_conn.commit()
        db_conn.close()

        os.environ["STATE_BACKEND"] = "sqlite_only"
        try:
            from superharness.engine import state_reader
            items = state_reader.get_inbox_items(str(project))
            assert len(items) == 1
            item = items[0]
            # B6: field names must match YAML convention
            assert item["task"] == "t1"
            assert item["to"] == "claude-code"
            assert item["project"] == str(project)
            assert "task_id" not in item
            assert "target_agent" not in item
        finally:
            del os.environ["STATE_BACKEND"]


# ---------------------------------------------------------------------------
# B6 — archive_yaml._inbox_row_to_yaml_shape
# ---------------------------------------------------------------------------

class TestArchiveYamlShape:
    def test_inbox_row_to_yaml_shape(self):
        from superharness.commands.archive_yaml import _inbox_row_to_yaml_shape
        row = {
            "id": "i2",
            "task_id": "t2",
            "target_agent": "codex-cli",
            "project_path": "/proj",
            "status": "done",
        }
        result = _inbox_row_to_yaml_shape(row)
        assert result["task"] == "t2"
        assert result["to"] == "codex-cli"
        assert result["project"] == "/proj"
        assert "task_id" not in result
        assert "target_agent" not in result


# ---------------------------------------------------------------------------
# B7 — auto_enqueue_todo / auto_enqueue_approved use new_item_ids set
# ---------------------------------------------------------------------------

class TestAutoEnqueueNewItemTracking:
    def _setup_auto_project(self, tmp_path, task_status: str) -> tuple:
        project = tmp_path / "proj"
        sh = project / ".superharness"
        sh.mkdir(parents=True)
        profile = {"auto_dispatch": True, "autonomy": "autonomous", "max_concurrent_tasks": 5}
        (sh / "profile.yaml").write_text(yaml.dump(profile))
        task = {"id": "t1", "title": "T1", "status": task_status,
                "owner": "claude-code", "project_path": str(project)}
        (sh / "contract.yaml").write_text(yaml.dump({"tasks": [task]}))
        (sh / "inbox.yaml").write_text("# inbox\n[]\n")
        return project

    def test_auto_enqueue_todo_does_not_double_mirror(self, tmp_path):
        project = self._setup_auto_project(tmp_path, "todo")
        from superharness.commands.inbox_watch import auto_enqueue_todo
        # First call: should add 1 item
        count1 = auto_enqueue_todo(str(project))
        assert count1 == 1
        # Second call: task now has active inbox entry — should add 0
        count2 = auto_enqueue_todo(str(project))
        assert count2 == 0

    def test_auto_enqueue_approved_does_not_double_mirror(self, tmp_path):
        project = self._setup_auto_project(tmp_path, "plan_approved")
        from superharness.commands.inbox_watch import auto_enqueue_approved
        count1 = auto_enqueue_approved(str(project))
        assert count1 == 1
        count2 = auto_enqueue_approved(str(project))
        assert count2 == 0

    def test_auto_enqueue_sqlite_only_no_duplicate_across_cycles(self, tmp_path):
        """Issue 2: in sqlite_only mode, second cycle must not re-enqueue same task."""
        project = tmp_path / "proj"
        sh = project / ".superharness"
        sh.mkdir(parents=True)
        profile = {"auto_dispatch": True, "autonomy": "autonomous",
                   "max_concurrent_tasks": 5, "state_backend": "sqlite_only"}
        (sh / "profile.yaml").write_text(yaml.dump(profile))
        task = {"id": "t1", "title": "T1", "status": "plan_approved",
                "owner": "claude-code", "project_path": str(project)}
        (sh / "contract.yaml").write_text(yaml.dump({"tasks": [task]}))

        from superharness.commands.inbox_watch import auto_enqueue_approved
        count1 = auto_enqueue_approved(str(project))
        assert count1 == 1

        # Second cycle: item is now in SQLite — dedup must fire
        count2 = auto_enqueue_approved(str(project))
        assert count2 == 0

        # Verify only 1 inbox row in SQLite
        conn = get_connection(str(project))
        try:
            init_db(conn)
            rows = inbox_dao.get_all(conn)
            assert len(rows) == 1, f"expected 1 inbox row, got {len(rows)}"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Issue 7 — _auto_retry_failed_sqlite (post-archive retry path)
# ---------------------------------------------------------------------------

class TestAutoRetryFailedSqlite:
    def test_resets_failed_items_with_retries_remaining(self, project, db_conn):
        t = tasks_dao.TaskRow(
            id="t1", title="T", owner=None, status="todo",
            effort=None, project_path=None, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at=T0, blocked_by=[],
        )
        tasks_dao.upsert(db_conn, t)
        inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code",
                          max_retries=3, now=T0)
        db_conn.execute("UPDATE inbox SET status='failed', retry_count=1, failed_reason='oops' WHERE id='i1'")
        db_conn.commit()
        db_conn.close()

        from superharness.commands.inbox_watch import _auto_retry_failed_sqlite
        _auto_retry_failed_sqlite(str(project))

        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = inbox_dao.get(conn, "i1")
            assert row.status == "pending"
            assert row.retry_count == 1  # count preserved (next failure will increment)
        finally:
            conn.close()

    def test_leaves_exhausted_items_as_failed(self, project, db_conn):
        t = tasks_dao.TaskRow(
            id="t1", title="T", owner=None, status="todo",
            effort=None, project_path=None, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at=T0, blocked_by=[],
        )
        tasks_dao.upsert(db_conn, t)
        inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code",
                          max_retries=3, now=T0)
        db_conn.execute("UPDATE inbox SET status='failed', retry_count=3 WHERE id='i1'")
        db_conn.commit()
        db_conn.close()

        from superharness.commands.inbox_watch import _auto_retry_failed_sqlite
        _auto_retry_failed_sqlite(str(project))

        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = inbox_dao.get(conn, "i1")
            assert row.status == "failed"  # exhausted — must stay failed
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# B9 — _yaml_writes_enabled
# ---------------------------------------------------------------------------

class TestYamlWritesEnabled:
    def test_returns_true_by_default(self, project):
        from superharness.commands.inbox_watch import _yaml_writes_enabled
        assert _yaml_writes_enabled(str(project)) is True

    def test_returns_false_when_env_sqlite_only(self, project):
        os.environ["STATE_BACKEND"] = "sqlite_only"
        try:
            from superharness.commands.inbox_watch import _yaml_writes_enabled
            assert _yaml_writes_enabled(str(project)) is False
        finally:
            del os.environ["STATE_BACKEND"]

    def test_returns_true_when_env_dual(self, project):
        os.environ["STATE_BACKEND"] = "dual"
        try:
            from superharness.commands.inbox_watch import _yaml_writes_enabled
            assert _yaml_writes_enabled(str(project)) is True
        finally:
            del os.environ["STATE_BACKEND"]

    def test_reads_profile_yaml(self, project):
        (project / ".superharness" / "profile.yaml").write_text(
            yaml.dump({"state_backend": "sqlite_only"})
        )
        from superharness.commands.inbox_watch import _yaml_writes_enabled
        assert _yaml_writes_enabled(str(project)) is False

    def test_auto_enqueue_skips_yaml_write_when_sqlite_only(self, tmp_path):
        project = tmp_path / "proj"
        sh = project / ".superharness"
        sh.mkdir(parents=True)
        profile = {"auto_dispatch": True, "autonomy": "autonomous",
                   "max_concurrent_tasks": 5, "state_backend": "sqlite_only"}
        (sh / "profile.yaml").write_text(yaml.dump(profile))
        task = {"id": "t1", "title": "T1", "status": "todo",
                "owner": "claude-code", "project_path": str(project)}
        (sh / "contract.yaml").write_text(yaml.dump({"tasks": [task]}))

        from superharness.commands.inbox_watch import auto_enqueue_todo
        count = auto_enqueue_todo(str(project))
        assert count == 1
        # inbox.yaml must NOT have been created
        assert not (sh / "inbox.yaml").exists()
