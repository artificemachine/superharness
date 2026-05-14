"""Phase 1 YAML cleanup: _get_task_effort_timeout and _validate_contract
read from SQLite, not contract.yaml.

RED tests — these must fail against the current YAML-reading implementation
and pass only after the SQLite migration.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import tasks_dao
from superharness.engine.tasks_dao import TaskRow


T0 = "2026-01-01T00:00:00Z"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    (p / ".superharness").mkdir()
    conn = get_connection(str(p))
    init_db(conn)
    conn.close()
    return p


def _insert_task(project: Path, **kwargs) -> None:
    conn = get_connection(str(project))
    init_db(conn)
    defaults = dict(
        id="t1", title="Test task", owner="claude-code",
        status="todo", effort=None, project_path=str(project),
        development_method="tdd", acceptance_criteria=[], test_types=[],
        out_of_scope=[], definition_of_done=[], context=None, tdd=None,
        version=1, created_at=T0,
    )
    defaults.update(kwargs)
    tasks_dao.upsert(conn, TaskRow(**defaults))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _get_task_effort_timeout — now takes project_dir instead of contract_file
# ---------------------------------------------------------------------------

class TestGetTaskEffortTimeoutSQLite:
    def test_low_effort_from_sqlite(self, project: Path) -> None:
        _insert_task(project, id="t-low", effort="low")
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "t-low") == 900

    def test_medium_effort_from_sqlite(self, project: Path) -> None:
        _insert_task(project, id="t-med", effort="medium")
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "t-med") == 1800

    def test_high_effort_from_sqlite(self, project: Path) -> None:
        _insert_task(project, id="t-high", effort="high")
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "t-high") == 3600

    def test_estimated_minutes_from_sqlite(self, project: Path) -> None:
        _insert_task(project, id="t-mins", effort=None, estimated_minutes="45")
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "t-mins") == 2700

    def test_estimated_minutes_overrides_effort(self, project: Path) -> None:
        _insert_task(project, id="t-both", effort="low", estimated_minutes="90")
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "t-both") == 5400

    def test_no_estimate_returns_zero(self, project: Path) -> None:
        _insert_task(project, id="t-none", effort=None)
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "t-none") == 0

    def test_task_not_found_returns_zero(self, project: Path) -> None:
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(project), "no-such-task") == 0

    def test_no_sqlite_returns_zero(self, tmp_path: Path) -> None:
        """Graceful fallback when project has no SQLite db."""
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / ".superharness").mkdir()
        from superharness.commands.inbox_dispatch import _get_task_effort_timeout
        assert _get_task_effort_timeout(str(bare), "t1") == 0


# ---------------------------------------------------------------------------
# _validate_contract — now reads from SQLite instead of contract.yaml
# ---------------------------------------------------------------------------

class TestValidateContractSQLite:
    def test_valid_task_passes(self, project: Path) -> None:
        _insert_task(project, id="t1", status="plan_approved", owner="claude-code",
                     project_path=str(project))
        from superharness.commands.inbox_enqueue import _validate_contract_sqlite
        # Should not raise
        _validate_contract_sqlite(str(project), "t1", "claude-code", plan_only=False)

    def test_task_not_found_passes(self, project: Path) -> None:
        """Missing task in SQLite is not an error (task may be new)."""
        from superharness.commands.inbox_enqueue import _validate_contract_sqlite
        _validate_contract_sqlite(str(project), "new-task", "claude-code", plan_only=False)

    def test_wrong_project_path_aborts(self, project: Path, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _insert_task(project, id="t1", project_path=str(other))
        from superharness.commands.inbox_enqueue import _validate_contract_sqlite
        with pytest.raises(SystemExit):
            _validate_contract_sqlite(str(project), "t1", "claude-code", plan_only=False)

    def test_wrong_owner_aborts(self, project: Path) -> None:
        _insert_task(project, id="t1", owner="codex-cli")
        from superharness.commands.inbox_enqueue import _validate_contract_sqlite
        with pytest.raises(SystemExit):
            _validate_contract_sqlite(str(project), "t1", "claude-code", plan_only=False)
