from __future__ import annotations

from superharness.engine import usage_dao

T0 = "2026-01-01T00:00:00Z"
T1 = "2026-01-01T01:00:00Z"


def _make_task(db_conn, task_id="t1"):
    db_conn.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, 'T', 'todo', 1, ?)",
        (task_id, T0),
    )
    db_conn.commit()


def test_record_returns_row_id(db_conn):
    _make_task(db_conn)
    row_id = usage_dao.record(
        db_conn,
        task_id="t1",
        agent="claude-code",
        source="sdk",
        model="claude-sonnet-5",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
    )
    assert isinstance(row_id, int)


def test_record_and_list_for_task_roundtrip(db_conn):
    _make_task(db_conn)
    usage_dao.record(db_conn, task_id="t1", agent="claude-code", input_tokens=100, output_tokens=50, cost_usd=0.01, now=T0)
    usage_dao.record(db_conn, task_id="t1", agent="claude-code", input_tokens=200, output_tokens=80, cost_usd=0.02, now=T1)

    rows = usage_dao.list_for_task(db_conn, "t1")
    assert len(rows) == 2
    assert rows[0].recorded_at == T0
    assert rows[1].recorded_at == T1


def test_list_for_task_empty_when_no_usage(db_conn):
    _make_task(db_conn)
    assert usage_dao.list_for_task(db_conn, "t1") == []


def test_record_defaults_source_to_manual(db_conn):
    _make_task(db_conn)
    usage_dao.record(db_conn, task_id="t1", agent="claude-code")
    rows = usage_dao.list_for_task(db_conn, "t1")
    assert rows[0].source == "manual"


def test_totals_by_agent_aggregates_correctly(db_conn):
    _make_task(db_conn, "t1")
    _make_task(db_conn, "t2")
    usage_dao.record(db_conn, task_id="t1", agent="claude-code", input_tokens=100, output_tokens=50, cost_usd=0.01)
    usage_dao.record(db_conn, task_id="t1", agent="claude-code", input_tokens=100, output_tokens=50, cost_usd=0.01)
    usage_dao.record(db_conn, task_id="t2", agent="codex-cli", input_tokens=400, output_tokens=150, cost_usd=0.03)

    totals = usage_dao.totals_by_agent(db_conn)

    assert totals["claude-code"]["input_tokens"] == 200
    assert totals["claude-code"]["output_tokens"] == 100
    assert totals["claude-code"]["cost_usd"] == 0.02
    assert totals["claude-code"]["task_count"] == 1

    assert totals["codex-cli"]["input_tokens"] == 400
    assert totals["codex-cli"]["output_tokens"] == 150
    assert totals["codex-cli"]["cost_usd"] == 0.03
    assert totals["codex-cli"]["task_count"] == 1
