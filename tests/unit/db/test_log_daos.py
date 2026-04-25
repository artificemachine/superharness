from __future__ import annotations

from superharness.engine import failures_dao, decisions_dao, ledger_dao

T0 = "2026-01-01T00:00:00Z"
T1 = "2026-01-01T01:00:00Z"


def test_failures_record_and_get(db_conn):
    row = failures_dao.record(db_conn, task_id="t1", agent="claude-code",
                              pattern="timeout", error_snippet="Process timed out", now=T0)
    assert row.id is not None
    assert row.task_id == "t1"
    assert row.pattern == "timeout"

    recent = failures_dao.get_recent(db_conn, task_id="t1")
    assert len(recent) == 1
    assert recent[0].error_snippet == "Process timed out"


def test_failures_filter_by_agent(db_conn):
    failures_dao.record(db_conn, agent="a1", now=T0)
    failures_dao.record(db_conn, agent="a2", now=T0)
    result = failures_dao.get_recent(db_conn, agent="a1")
    assert all(r.agent == "a1" for r in result)


def test_decisions_record_and_get(db_conn):
    row = decisions_dao.record(
        db_conn,
        agent="claude-code",
        task_id="t1",
        decision="use SQLite instead of YAML",
        reason="ACID transactions",
        alternatives="keep YAML, use Postgres",
        now=T0,
    )
    assert row.decision == "use SQLite instead of YAML"
    assert row.reason == "ACID transactions"

    recent = decisions_dao.get_recent(db_conn, task_id="t1")
    assert len(recent) == 1


def test_ledger_record_and_get(db_conn):
    row = ledger_dao.record(
        db_conn,
        task_id="t1",
        agent="watcher",
        action="dispatched",
        details={"inbox_id": "i1", "owner": "claude-code"},
        now=T0,
    )
    assert row.action == "dispatched"
    assert row.details["inbox_id"] == "i1"

    recent = ledger_dao.get_recent(db_conn, task_id="t1")
    assert len(recent) == 1


def test_ledger_no_details(db_conn):
    row = ledger_dao.record(db_conn, action="heartbeat", now=T0)
    assert row.action == "heartbeat"


def test_failures_nulls(db_conn):
    row = failures_dao.record(db_conn, now=T0)
    assert row.task_id is None
    assert row.agent is None
