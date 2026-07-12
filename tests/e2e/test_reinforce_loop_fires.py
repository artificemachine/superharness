"""E2E fault-injection harness for iteration 6 of PLAN-superharness-L5.md.

The reinforce loop's failure-analysis path (_reinforce_loop -> analyze_failure
-> _maybe_pause_agent) has never been observed firing in production — the
2026-07-12 brain scan's G5c blocker. These tests inject a real ≥2-failure
cluster through the actual inbox/failure path (real SQLite, real
_reinforce_loop code) with only the fleet call itself mocked, proving the
loop's mechanics end to end. The live, unmocked verification (real fleet
call, the actual G5c evidence) is scripts/verify-l5-loop.sh, run once by
the operator — not part of this CI-safe file.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from superharness.commands import inbox_watch
from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao, tasks_dao


def _sandbox(tmp_path: Path) -> Path:
    project = tmp_path / "sandbox-proj"
    (project / ".superharness").mkdir(parents=True)
    return project


def _now_iso() -> str:
    """Real current UTC time, not a fixed literal — _reinforce_loop's window
    query filters on failed_at >= (real now - _REINFORCE_WINDOW_MINUTES), so
    a hardcoded timestamp only passes when the test happens to run within
    that window of the literal; on a CI runner executing at a different
    wall-clock time it silently falls outside the window and the loop finds
    nothing to analyze (confirmed failure mode, not hypothetical)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_task(conn, task_id: str, owner: str, project_dir: str) -> None:
    tasks_dao.upsert(conn, tasks_dao.TaskRow(
        id=task_id, title="seeded task", owner=owner, status="in_progress",
        effort="medium", project_path=project_dir, development_method="tdd",
        acceptance_criteria=["works"], test_types=["unit"], out_of_scope=[],
        definition_of_done=[], context="ctx", tdd=None, version=1,
        created_at=_now_iso(), blocked_by=[], parent_id=None,
    ))
    conn.commit()


def _seed_failures(conn, agent: str, count: int, failed_at: str, reason: str = "ModuleNotFoundError: no module named yaml") -> None:
    """Write `count` failed inbox rows for `agent` with the given failed_at,
    exactly what _reinforce_loop's window query reads (status='failed',
    failed_at >= window_start, grouped by target_agent). inbox.task_id has
    an FK to tasks(id), so each failure gets its own seeded task."""
    for i in range(count):
        item_id = f"item-{agent}-{i}"
        task_id = f"fix.thing.{agent}.{i}"
        _seed_task(conn, task_id, agent, "")
        inbox_dao.enqueue(
            conn, id=item_id, task_id=task_id, target_agent=agent,
            priority=2, max_retries=3, now=failed_at,
        )
        conn.execute(
            "UPDATE inbox SET status='failed', failed_reason=?, failed_at=? WHERE id=?",
            (reason, failed_at, item_id),
        )
    conn.commit()


def _read_reinforce_events(project_dir: Path, event_type: str = "reinforce_analysis") -> list[dict]:
    """Return only `event_type` dicts from the sandbox's trace.jsonl."""
    trace_path = project_dir / ".superharness" / "trace.jsonl"
    if not trace_path.exists():
        return []
    events = []
    for line in trace_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == event_type:
            events.append(evt)
    return events


def test_seed_failures_creates_window_rows(tmp_path):
    project = _sandbox(tmp_path)
    conn = get_connection(str(project))
    init_db(conn)
    _seed_failures(conn, "codex-cli", 2, _now_iso())
    rows = conn.execute("SELECT * FROM inbox WHERE status='failed' AND target_agent='codex-cli'").fetchall()
    conn.close()
    assert len(rows) == 2
    assert all(r["failed_at"] == _now_iso() for r in rows)


def test_read_reinforce_events_parses_trace_lines(tmp_path):
    project = _sandbox(tmp_path)
    trace_dir = project / ".superharness"
    trace_dir.mkdir(exist_ok=True)
    (trace_dir / "trace.jsonl").write_text(
        json.dumps({"type": "reinforce_analysis", "agent": "codex-cli"}) + "\n"
        + json.dumps({"type": "auto_close_report_ready", "task": "x"}) + "\n"
        + json.dumps({"type": "reinforce_analysis", "agent": "gemini-cli"}) + "\n"
    )
    events = _read_reinforce_events(project)
    assert len(events) == 2
    assert {e["agent"] for e in events} == {"codex-cli", "gemini-cli"}


def test_two_failures_trigger_analysis_event(tmp_path):
    project = _sandbox(tmp_path)
    conn = get_connection(str(project))
    init_db(conn)
    _seed_failures(conn, "codex-cli", 2, _now_iso())
    conn.close()

    with patch("superharness.engine.model_router.analyze_failure", return_value="dependency"):
        with patch.object(inbox_watch, "_self_heal", return_value=(False, "no heal available")):
            inbox_watch._reinforce_loop(str(project))

    events = _read_reinforce_events(project)
    assert len(events) == 1
    assert events[0]["classification"] == "dependency"
    assert events[0]["failures"] == 2
    assert events[0]["agent"] == "codex-cli"


def test_single_failure_does_not_trigger(tmp_path):
    project = _sandbox(tmp_path)
    conn = get_connection(str(project))
    init_db(conn)
    _seed_failures(conn, "codex-cli", 1, _now_iso())
    conn.close()

    with patch("superharness.engine.model_router.analyze_failure", return_value="dependency"):
        inbox_watch._reinforce_loop(str(project))

    assert _read_reinforce_events(project) == []


def test_stale_failures_outside_window_ignored(tmp_path):
    project = _sandbox(tmp_path)
    conn = get_connection(str(project))
    init_db(conn)
    stale_time = "2020-01-01T00:00:00Z"  # far outside _REINFORCE_WINDOW_MINUTES
    _seed_failures(conn, "codex-cli", 2, stale_time)
    conn.close()

    with patch("superharness.engine.model_router.analyze_failure", return_value="dependency"):
        inbox_watch._reinforce_loop(str(project))

    assert _read_reinforce_events(project) == []


def test_permanent_block_pauses_agent(tmp_path):
    project = _sandbox(tmp_path)
    conn = get_connection(str(project))
    init_db(conn)
    _seed_task(conn, "fix.pending.1", "codex-cli", str(project))
    _seed_failures(conn, "codex-cli", 2, _now_iso())
    # A pending item for the same agent — this is what _maybe_pause_agent
    # actually transitions to 'paused'.
    inbox_dao.enqueue(
        conn, id="pending-item", task_id="fix.pending.1", target_agent="codex-cli",
        priority=2, max_retries=3, now=_now_iso(),
    )
    conn.commit()
    conn.close()

    with patch("superharness.engine.model_router.analyze_failure", return_value="permanent_block"):
        with patch.object(inbox_watch, "_self_heal", return_value=(False, "no heal available")):
            inbox_watch._reinforce_loop(str(project))

    conn2 = get_connection(str(project))
    row = conn2.execute("SELECT status FROM inbox WHERE id='pending-item'").fetchone()
    conn2.close()
    assert row["status"] == "paused"

    pause_events = _read_reinforce_events(project, event_type="reinforce_agent_pause")
    assert len(pause_events) == 1
    assert pause_events[0]["agent"] == "codex-cli"
