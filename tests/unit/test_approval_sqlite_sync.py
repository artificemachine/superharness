"""Guard: discuss._do_approve must write approval_gate back to SQLite.

Doctrine: SQLite is source of truth. After cmd_approve runs, the handoffs
table must reflect the updated approval_gate — not just the YAML file.
This test fails if approval state lives in YAML only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine.db import now_iso


@pytest.fixture
def project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()
    return tmp_path


def _seed_handoff_yaml(project: Path, task_id: str, phase: str = "report") -> Path:
    """Write a handoff YAML file as upsert_handoff would, with pending approval gate."""
    import yaml
    handoff_id = f"{task_id}-{phase}"
    content = {
        "task": task_id,
        "phase": phase,
        "status": "pending_user_approval",
        "from": "claude-code",
        "to": "owner",
        "date": now_iso(),
        "approval_gate": {
            "required": True,
            "approved_by_user": False,
        },
    }
    path = project / ".superharness" / "handoffs" / f"{handoff_id}.yaml"
    path.write_text(yaml.dump(content, default_flow_style=False, allow_unicode=True))
    return path


def _seed_handoff_sqlite(project: Path, task_id: str, phase: str = "report") -> None:
    """Write the same handoff into SQLite via handoffs_dao."""
    from superharness.engine import handoffs_dao
    from superharness.engine.db import managed_connection
    import yaml

    content_dict = {
        "task": task_id,
        "phase": phase,
        "status": "pending_user_approval",
        "from": "claude-code",
        "to": "owner",
        "date": now_iso(),
        "approval_gate": {"required": True, "approved_by_user": False},
    }
    body = yaml.dump(content_dict, default_flow_style=False, allow_unicode=True)
    with managed_connection(str(project)) as conn:
        handoffs_dao.append(
            conn,
            task_id=task_id,
            phase=phase,
            status="pending_user_approval",
            from_agent="claude-code",
            to_agent="owner",
            content=body,
            metadata=content_dict,
            now=now_iso(),
        )


def _seed_task_sqlite(project: Path, task_id: str) -> None:
    from superharness.engine.db import managed_connection
    with managed_connection(str(project)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, status, project_path, created_at, version)"
            " VALUES (?, ?, 'in_progress', ?, ?, 1)",
            (task_id, f"Task {task_id}", str(project), now_iso()),
        )


def _get_handoff_approval_gate(project: Path, task_id: str, phase: str = "report") -> dict | None:
    """Read latest handoff from SQLite and return the approval_gate metadata."""
    from superharness.engine import handoffs_dao
    from superharness.engine.db import managed_connection
    with managed_connection(str(project)) as conn:
        row = handoffs_dao.get_latest(conn, task_id, phase)
    if row is None:
        return None
    meta = row.metadata or {}
    return meta.get("approval_gate")


def test_approve_writes_approval_gate_to_sqlite(project: Path) -> None:
    """After cmd_approve, SQLite handoff metadata must show approved_by_user=True."""
    task_id = "t-approve-guard"
    _seed_task_sqlite(project, task_id)
    _seed_handoff_yaml(project, task_id)
    _seed_handoff_sqlite(project, task_id)

    # Confirm pre-condition: not yet approved in SQLite
    gate_before = _get_handoff_approval_gate(project, task_id)
    assert gate_before is not None, "Handoff not found in SQLite before approve"
    assert gate_before.get("approved_by_user") is False, "Should be unapproved before"

    handoff_dir = str(project / ".superharness" / "handoffs")

    from superharness.engine import discuss
    discuss.cmd_approve(
        handoff_dir=handoff_dir,
        task_id=task_id,
        actor="owner",
        note="",
        project_dir=str(project),
    )

    # Core assertion: approval_gate must be reflected in SQLite
    gate_after = _get_handoff_approval_gate(project, task_id)
    assert gate_after is not None, "Handoff not found in SQLite after approve"
    assert gate_after.get("approved_by_user") is True, (
        "discuss._do_approve wrote approval_gate to YAML only — SQLite is stale. "
        "Fix: call write_handoff_to_db() after updating the handoff dict."
    )


def test_cmd_status_reads_pending_from_sqlite(project: Path) -> None:
    """cmd_status must reflect pending approval from SQLite, not only from YAML files."""
    task_id = "t-status-guard"
    _seed_task_sqlite(project, task_id)
    _seed_handoff_sqlite(project, task_id)
    # No YAML file on disk — if status reads SQLite, it finds the pending item.
    # If it only globs YAML files, it finds nothing.

    handoff_dir = str(project / ".superharness" / "handoffs")

    from superharness.engine import discuss
    rows = discuss.cmd_status(handoff_dir=handoff_dir)

    task_ids = [r.get("task") or r.get("task_id") for r in rows]
    assert task_id in task_ids, (
        "cmd_status found no pending approvals even though SQLite has a "
        "pending_user_approval handoff. Fix: replace YAML glob with state_reader.get_handoffs()."
    )
