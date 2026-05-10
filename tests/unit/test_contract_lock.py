"""Unit tests for Iter 1: pre-code validation contract lock."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from superharness.engine import db, tasks_dao
from superharness.engine.state_errors import ContractLockError


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = db.get_connection(str(tmp_path))
    db.init_db(conn)
    return conn


def _insert_task(conn: sqlite3.Connection, task_id: str = "t1") -> tasks_dao.TaskRow:
    from superharness.engine.tasks_dao import TaskRow
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = TaskRow(
        id=task_id,
        title="Test task",
        owner="claude-code",
        status="plan_proposed",
        effort=None,
        project_path=None,
        development_method=None,
        acceptance_criteria=["must do X", "must do Y"],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd={"red": "write tests", "green": "implement", "refactor": "clean up"},
        version=1,
        created_at=now,
    )
    return tasks_dao.upsert(conn, row)


class TestContractLockSchema:
    def test_columns_exist_after_migration(self, tmp_path):
        conn = _make_conn(tmp_path)
        cursor = conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "locked_contract" in cols
        assert "contract_locked_at" in cols

    def test_new_task_has_no_lock(self, tmp_path):
        conn = _make_conn(tmp_path)
        task = _insert_task(conn)
        assert task.locked_contract is None
        assert task.contract_locked_at is None


class TestContractLockWrite:
    def test_update_locked_fields_raises_when_locked(self, tmp_path):
        conn = _make_conn(tmp_path)
        task = _insert_task(conn)
        # Manually set contract_locked_at to simulate plan_approved snapshot
        conn.execute(
            "UPDATE tasks SET locked_contract = ?, contract_locked_at = ? WHERE id = ?",
            (json.dumps({"acceptance_criteria": ["original"], "tdd": {}}), "2026-01-01T00:00:00Z", task.id),
        )
        conn.commit()
        refreshed = tasks_dao.get(conn, task.id)
        assert refreshed is not None
        with pytest.raises(ContractLockError):
            tasks_dao.update(conn, task.id, version=refreshed.version,
                             changes={"acceptance_criteria": ["modified"]})

    def test_update_locked_tdd_raises_when_locked(self, tmp_path):
        conn = _make_conn(tmp_path)
        task = _insert_task(conn)
        conn.execute(
            "UPDATE tasks SET contract_locked_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00Z", task.id),
        )
        conn.commit()
        refreshed = tasks_dao.get(conn, task.id)
        assert refreshed is not None
        with pytest.raises(ContractLockError):
            tasks_dao.update(conn, task.id, version=refreshed.version,
                             changes={"tdd": {"red": "changed"}})

    def test_update_non_locked_field_succeeds_when_locked(self, tmp_path):
        conn = _make_conn(tmp_path)
        task = _insert_task(conn)
        conn.execute(
            "UPDATE tasks SET contract_locked_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00Z", task.id),
        )
        conn.commit()
        refreshed = tasks_dao.get(conn, task.id)
        assert refreshed is not None
        updated = tasks_dao.update(conn, task.id, version=refreshed.version,
                                   changes={"status": "in_progress"})
        assert updated.status == "in_progress"

    def test_update_without_lock_allows_ac_changes(self, tmp_path):
        conn = _make_conn(tmp_path)
        task = _insert_task(conn)
        updated = tasks_dao.update(conn, task.id, version=task.version,
                                   changes={"acceptance_criteria": ["new criterion"]})
        assert updated.acceptance_criteria == ["new criterion"]


class TestContractLockSnapshot:
    def test_locked_contract_stored_as_json_snapshot(self, tmp_path):
        conn = _make_conn(tmp_path)
        task = _insert_task(conn)
        snapshot = {"acceptance_criteria": task.acceptance_criteria, "tdd": task.tdd}
        conn.execute(
            "UPDATE tasks SET locked_contract = ?, contract_locked_at = ? WHERE id = ?",
            (json.dumps(snapshot), "2026-01-01T00:00:00Z", task.id),
        )
        conn.commit()
        refreshed = tasks_dao.get(conn, task.id)
        assert refreshed is not None
        assert refreshed.locked_contract is not None
        parsed = json.loads(refreshed.locked_contract)
        assert parsed["acceptance_criteria"] == ["must do X", "must do Y"]
        assert parsed["tdd"]["red"] == "write tests"
