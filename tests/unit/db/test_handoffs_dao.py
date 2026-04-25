from __future__ import annotations

from superharness.engine import handoffs_dao

T0 = "2026-01-01T00:00:00Z"
T1 = "2026-01-01T01:00:00Z"
T2 = "2026-01-01T02:00:00Z"


def _make_task(db_conn, task_id="t1"):
    db_conn.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, 'T', 'todo', 1, ?)",
        (task_id, T0),
    )
    db_conn.commit()


def test_append_and_get_history(db_conn):
    _make_task(db_conn)
    handoffs_dao.append(db_conn, task_id="t1", phase="plan", status="plan_proposed",
                        from_agent="claude-code", now=T0)
    handoffs_dao.append(db_conn, task_id="t1", phase="plan", status="plan_approved",
                        from_agent="owner", now=T1)

    history = handoffs_dao.get_history(db_conn, "t1")
    assert len(history) == 2
    assert history[0].status == "plan_proposed"
    assert history[1].status == "plan_approved"


def test_get_latest(db_conn):
    _make_task(db_conn)
    handoffs_dao.append(db_conn, task_id="t1", phase="plan", status="plan_proposed", now=T0)
    handoffs_dao.append(db_conn, task_id="t1", phase="plan", status="plan_approved", now=T1)
    handoffs_dao.append(db_conn, task_id="t1", phase="report", status="report_ready", now=T2)

    latest_plan = handoffs_dao.get_latest(db_conn, "t1", "plan")
    assert latest_plan is not None
    assert latest_plan.status == "plan_approved"

    latest_report = handoffs_dao.get_latest(db_conn, "t1", "report")
    assert latest_report is not None
    assert latest_report.status == "report_ready"


def test_get_latest_none(db_conn):
    _make_task(db_conn)
    result = handoffs_dao.get_latest(db_conn, "t1", "plan")
    assert result is None


def test_metadata_roundtrip(db_conn):
    _make_task(db_conn)
    row = handoffs_dao.append(
        db_conn,
        task_id="t1",
        phase="plan",
        status="plan_proposed",
        metadata={"reviewer": "opus", "score": 9},
        now=T0,
    )
    assert row.metadata == {"reviewer": "opus", "score": 9}


def test_history_empty(db_conn):
    _make_task(db_conn)
    assert handoffs_dao.get_history(db_conn, "t1") == []
