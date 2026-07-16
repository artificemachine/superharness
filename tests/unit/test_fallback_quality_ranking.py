"""RED tests for iteration 4 of PLAN-superharness-L5.md: quality-ranked fallback routing.

review_dao.rank_owners has 1,393 live outcome rows in production and zero
callers — a fully dormant learning signal (docs/brain-scan-2026-07-12.md,
"Dormant intelligence"). _rank_fallback_agents wires it into
_auto_recover_exhausted_failures_sqlite's fallback selection: recorded
outcomes now change which agent gets retried next.
"""
from __future__ import annotations

import sqlite3

import pytest


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    return conn


def _seed_review_rows(conn, owner: str, count: int, fail_rate: float, duration_s: float = 10.0):
    from superharness.engine import review_dao
    now = "2026-07-12T00:00:00Z"
    n_fail = round(count * fail_rate)
    for i in range(count):
        review_dao.record(
            conn, owner=owner, task_type="fix", duration_s=duration_s,
            score=1.0, failed=(i < n_fail), now=now,
        )
    conn.commit()


def test_low_fail_rate_agent_ranked_first():
    from superharness.commands.inbox_watch import _rank_fallback_agents

    conn = _make_conn()
    _seed_review_rows(conn, "gemini-cli", 5, fail_rate=0.0)
    _seed_review_rows(conn, "codex-cli", 5, fail_rate=0.8)

    ranked = _rank_fallback_agents(conn, ["codex-cli", "gemini-cli"])
    assert ranked == ["gemini-cli", "codex-cli"]


def test_unranked_agents_keep_static_order_after_ranked():
    from superharness.commands.inbox_watch import _rank_fallback_agents

    conn = _make_conn()
    _seed_review_rows(conn, "gemini-cli", 5, fail_rate=0.0)

    ranked = _rank_fallback_agents(conn, ["claude-code", "codex-cli", "gemini-cli"])
    assert ranked == ["gemini-cli", "claude-code", "codex-cli"]


def test_empty_review_store_preserves_input_order():
    from superharness.commands.inbox_watch import _rank_fallback_agents

    conn = _make_conn()
    candidates = ["claude-code", "codex-cli", "gemini-cli"]
    assert _rank_fallback_agents(conn, candidates) == candidates


def test_ranking_error_falls_back_to_input_order():
    from superharness.commands.inbox_watch import _rank_fallback_agents

    class _RaisingConn:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("db locked")

    candidates = ["claude-code", "codex-cli"]
    assert _rank_fallback_agents(_RaisingConn(), candidates) == candidates


def test_recover_path_uses_ranked_order(tmp_path, monkeypatch):
    from superharness.commands import inbox_watch
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao, review_dao, tasks_dao

    project_dir = tmp_path
    (project_dir / ".superharness").mkdir()

    conn = get_connection(str(project_dir))
    init_db(conn)

    tasks_dao.upsert(conn, tasks_dao.TaskRow(
        id="fix.thing", title="fix thing", owner="claude-code", status="in_progress",
        effort="medium", project_path=str(project_dir), development_method="tdd",
        acceptance_criteria=["works"], test_types=["unit"], out_of_scope=[],
        definition_of_done=[], context="ctx", tdd=None, version=1,
        created_at="2026-07-12T00:00:00Z", blocked_by=[], parent_id=None,
    ))
    conn.commit()

    now = "2026-07-12T00:00:00Z"
    inbox_dao.enqueue(
        conn, id="item-1", task_id="fix.thing", target_agent="claude-code",
        priority=2, max_retries=3, project_path=str(project_dir), now=now,
    )
    conn.execute(
        "UPDATE inbox SET status='failed', failed_reason=?, retry_count=?, max_retries=? WHERE id=?",
        ("transient timeout", 3, 3, "item-1"),
    )
    conn.commit()

    _seed_review_rows(conn, "gemini-cli", 5, fail_rate=0.0)
    _seed_review_rows(conn, "codex-cli", 5, fail_rate=1.0)
    _seed_review_rows(conn, "opencode", 5, fail_rate=1.0)
    conn.close()

    monkeypatch.setattr(inbox_watch, "_agent_cli_reachable", lambda agent: True)
    monkeypatch.setattr(
        "superharness.engine.model_router.is_agent_quota_limited",
        lambda project, agent: False,
    )

    inbox_watch._auto_recover_exhausted_failures_sqlite(str(project_dir))

    conn2 = get_connection(str(project_dir))
    row = conn2.execute("SELECT target_agent, status FROM inbox WHERE task_id='fix.thing' ORDER BY created_at DESC").fetchone()
    conn2.close()
    assert row is not None
    assert row["target_agent"] == "gemini-cli", (
        f"expected the quality-ranked winner (gemini-cli, 0% fail rate), got {row['target_agent']!r}"
    )
