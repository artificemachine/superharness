"""Test for the tool-loop-block ledger record in _analyze_task_logs.

TDD: written to expose a real NameError bug found by a 2026-07-21
portfolio-ready audit's ruff pass (F821 undefined-name) — the block-loop
branch called `_ledger_record2(...)` without importing it, unlike the three
other call sites in this file that alias `ledger_dao.record` the same way.
The NameError was silently swallowed by the surrounding broad
`except Exception`, so the watcher never crashed — it just silently lost
the ledger audit trail for every tool-loop block, and fell through into
the staleness checks below instead of `continue`-ing past them. Zero test
coverage on this branch let it ship undetected.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.mark.regression
def test_tool_loop_block_records_ledger_entry(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    launcher_logs = project / ".superharness" / "launcher-logs"
    launcher_logs.mkdir()

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(project))
    init_db(conn)

    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    tasks_dao.upsert(conn, TaskRow(
        id="t-loop-1", title="Tool loop test", owner="claude-code", status="in_progress",
        effort="medium", project_path=str(project), development_method="tdd",
        acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[],
        context=None, tdd=None, version=1, created_at=old,
    ))
    conn.commit()
    inbox_dao.enqueue(
        conn, id="inbox-1", task_id="t-loop-1", target_agent="claude-code", now=old,
    )
    inbox_dao.update_status(conn, "inbox-1", from_status="pending", to_status="launched", now=old)
    conn.commit()

    log_file = launcher_logs / "t-loop-1_claude-code.log"
    log_file.write_text("some log content\n")
    # Make sure the log file itself doesn't look freshly active.
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp()
    os.utime(log_file, (old_ts, old_ts))

    import superharness.engine.loop_detector as loop_detector
    monkeypatch.setattr(
        loop_detector, "detect_loop",
        lambda log_path, window=None: {"loop_detected": True, "block": True,
                                        "reason": "repeated identical tool call",
                                        "pattern": "test-pattern", "count": 9},
    )

    import superharness.engine.state_writer as state_writer
    monkeypatch.setattr(state_writer, "set_task_status", lambda *a, **k: None)

    from superharness.commands.inbox_watch import _analyze_task_logs
    _analyze_task_logs(str(project))  # must not raise NameError

    from superharness.engine import ledger_dao
    entries = ledger_dao.get_recent(conn, limit=20)
    assert any(e.action == "block_loop" for e in entries), (
        "expected a block_loop ledger entry, got: " + repr(entries)
    )

    row = inbox_dao.get(conn, "inbox-1")
    assert row.status == "failed", (
        "tool-loop block should transition the inbox item to failed, got: " + row.status
    )
