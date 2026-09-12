from __future__ import annotations
import pytest

import yaml
from unittest.mock import patch, MagicMock

from superharness.engine import parity, tasks_dao
from superharness.engine.tasks_dao import TaskRow

T0 = "2026-01-01T00:00:00Z"


def _task(id, status="todo", title="T", owner=None):
    return TaskRow(
        id=id,
        title=title,
        owner=owner,
        status=status,
        effort=None,
        project_path=None,
        development_method=None,
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd=None,
        version=1,
        created_at=T0,
        blocked_by=[],
    )


def _setup_sh(tmp_path):
    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    return sh_dir










# B1: parity covers handoffs, failures, decisions






# B2: subtasks nested under parent in YAML are visible to parity




# B3: heal_parity is idempotent — calling twice does not duplicate ops
def test_heal_parity_is_idempotent(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    tasks_dao.upsert(db_conn, _task("t2"))
    # Use explicit title/status matching the DB row to avoid triggering mismatched drift
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1", "title": "T", "status": "todo"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    parity.heal_parity(db_conn, project_dir, report)
    second = parity.heal_parity(db_conn, project_dir, report)

    # yaml_sync_queue table removed in migration v24 — no queue to check
    assert second == 0


# B4: heal_parity closes only_in_yaml gap by upserting YAML tasks to SQLite


# F6: mismatched field detection


# F7: foreign key check included in report
def test_parity_foreign_key_clean(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": []}))

    report = parity.check_parity(db_conn, project_dir)
    assert report.foreign_key_violations == 0


# Integration: full orchestrator cycle leaves parity clean (no mismatched drift)


# _heal_handoffs_db_to_yaml: DB→YAML direction for handoff drift


def _insert_handoff(
    conn,
    task_id,
    phase="report",
    status="report_ready",
    from_agent="claude-code",
    to_agent="owner",
    created_at=T0,
):
    conn.execute(
        "INSERT INTO handoffs (task_id, phase, status, from_agent, to_agent, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (task_id, phase, status, from_agent, to_agent, created_at),
    )
    conn.commit()


def _contract(sh_dir, tasks):
    """Write contract.yaml with tasks matched exactly to _task() defaults (title=T, status=todo)."""
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": t, "title": "T", "status": "todo"} for t in tasks]})
    )






def test_heal_handoffs_db_to_yaml_skips_orphaned_task(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    # Insert handoff for a task that does NOT exist in tasks table
    db_conn.execute("PRAGMA foreign_keys = OFF")
    _insert_handoff(db_conn, "ghost-task", created_at=T0)
    db_conn.execute("PRAGMA foreign_keys = ON")
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": []}))

    report = parity.check_parity(db_conn, project_dir)
    parity.heal_parity(db_conn, project_dir, report)

    # Orphaned handoff must not produce a YAML file
    assert len(list(handoffs_dir.glob("*.yaml"))) == 0








# F9: _sqlite_tick calls heal_parity after drain when drift is present
