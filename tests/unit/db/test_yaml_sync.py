from __future__ import annotations

import json
import os

from superharness.engine import yaml_sync

T0 = "2026-01-01T00:00:00Z"


def test_enqueue_op_inserts(db_conn):
    row_id = yaml_sync.enqueue_op(db_conn, op_type="upsert_task", payload={"id": "t1"}, now=T0)
    db_conn.commit()
    assert isinstance(row_id, int)
    row = db_conn.execute("SELECT * FROM yaml_sync_queue WHERE id=?", (row_id,)).fetchone()
    assert row["op_type"] == "upsert_task"
    assert json.loads(row["payload"]) == {"id": "t1"}
    assert row["status"] == "pending"


def test_drain_upsert_task(db_conn, tmp_path):
    project_dir = str(tmp_path)
    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir(exist_ok=True)

    yaml_sync.enqueue_op(db_conn, op_type="upsert_task",
                         payload={"id": "t1", "title": "Task One", "status": "todo"}, now=T0)
    db_conn.commit()

    report = yaml_sync.drain(db_conn, project_dir)
    assert report.applied >= 1
    assert report.failed == 0

    contract_path = sh_dir / "contract.yaml"
    assert contract_path.exists()
    import yaml
    doc = yaml.safe_load(contract_path.read_text())
    tasks = doc.get("tasks", [])
    assert any(t.get("id") == "t1" for t in tasks)


def test_drain_update_inbox(db_conn, tmp_path):
    project_dir = str(tmp_path)
    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir(exist_ok=True)

    # Seed an existing inbox.yaml
    import yaml
    (sh_dir / "inbox.yaml").write_text(
        yaml.dump([{"id": "i1", "status": "pending", "task_id": "t1", "target_agent": "a"}])
    )

    yaml_sync.enqueue_op(db_conn, op_type="update_inbox",
                         payload={"id": "i1", "status": "launched"}, now=T0)
    db_conn.commit()

    report = yaml_sync.drain(db_conn, project_dir)
    assert report.applied >= 1

    updated = yaml.safe_load((sh_dir / "inbox.yaml").read_text())
    assert updated[0]["status"] == "launched"


def test_drain_idempotent_applied(db_conn, tmp_path):
    project_dir = str(tmp_path)
    (tmp_path / ".superharness").mkdir(exist_ok=True)

    yaml_sync.enqueue_op(db_conn, op_type="upsert_task", payload={"id": "t1"}, now=T0)
    db_conn.commit()

    r1 = yaml_sync.drain(db_conn, project_dir)
    r2 = yaml_sync.drain(db_conn, project_dir)
    assert r1.applied == 1
    assert r2.applied == 0  # already applied


def test_drain_unknown_op_skipped(db_conn, tmp_path):
    project_dir = str(tmp_path)
    (tmp_path / ".superharness").mkdir(exist_ok=True)

    yaml_sync.enqueue_op(db_conn, op_type="bogus_op", payload={}, now=T0)
    db_conn.commit()

    report = yaml_sync.drain(db_conn, project_dir)
    # unknown op type is skipped (applied), not failed
    assert report.failed == 0
