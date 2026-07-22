"""CLI-level regression test for `inbox sync_task_status`.

Bug: session-stop.sh and session-exit.sh call
`python3 -m superharness.engine.inbox sync_task_status --file ... --task ...
--to stopped --now ...` on every session end, but `sync_task_status()` was
deleted from engine/inbox.py in c5d68ea3 ("strip YAML CRUD from inbox.py")
while the docstring, --help text, and both hooks kept referencing it. The
command always fell through to `raise UsageError(... "not fully implemented
in CLI yet")`, which the hooks swallowed via `2>/dev/null || true` — task
status silently never synced back to the inbox when a session ended.

This exercises the exact subprocess boundary the hooks use (module CLI via
`main(argv)`), not just the DAO function, per the fix priority: prove a real
status transition happens end-to-end, not just an exit code.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

TASK_ID = "feat.sync-task-status-regression"


def _make_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()
    return tmp_path


def _seed_task_and_inbox_row(project_dir: Path, task_id: str, *, status: str = "launched") -> str:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao, tasks_dao

    conn = get_connection(str(project_dir))
    init_db(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tasks_dao.upsert(conn, tasks_dao.TaskRow(
        id=task_id, title="test", owner="claude-code", status="in_progress",
        effort="medium", project_path=str(project_dir), development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at=now, updated_at=now,
        plan_proposed_at=None, plan_approved_at=None, in_progress_at=now,
        report_ready_at=None, review_requested_at=None,
        done_at=None, cancelled_at=None, blocked_by=[],
        verified=False, verified_at=None, verified_by=None, deadline_minutes=None,
        failed_at=None, stopped_at=None, failed_reason=None,
        archived_at=None, archived_reason=None, model_tier=None, pause_reason=None,
        workflow="implementation",
    ))
    item_id = f"i-{task_id}"
    inbox_dao.enqueue(conn, id=item_id, task_id=task_id, target_agent="claude-code",
                       project_path=str(project_dir), now=now)
    if status != "pending":
        conn.execute("UPDATE inbox SET status=?, pid=123 WHERE id=?", (status, item_id))
    conn.commit()
    conn.close()
    return item_id


def _inbox_row(project_dir: Path, item_id: str):
    from superharness.engine.db import get_connection
    conn = get_connection(str(project_dir))
    try:
        cur = conn.execute("SELECT status, pid FROM inbox WHERE id=?", (item_id,))
        return cur.fetchone()
    finally:
        conn.close()


def test_sync_task_status_cli_transitions_and_prints_synced_count(tmp_path, capsys):
    """Reproduces the exact call the session-stop/session-exit hooks make."""
    from superharness.engine import inbox

    proj = _make_project(tmp_path)
    item_id = _seed_task_and_inbox_row(proj, TASK_ID, status="launched")
    inbox_file = str(proj / ".superharness" / "inbox.yaml")

    inbox.main([
        "sync_task_status", "--file", inbox_file,
        "--task", TASK_ID, "--to", "stopped",
        "--now", "2026-01-01T00:05:00Z",
    ])

    out = capsys.readouterr().out
    assert "synced=1" in out, "hooks parse this exact string to decide whether to log a ledger entry"

    row = _inbox_row(proj, item_id)
    assert row["status"] == "stopped"
    assert row["pid"] is None


def test_sync_task_status_cli_no_active_rows_prints_synced_zero(tmp_path, capsys):
    from superharness.engine import inbox

    proj = _make_project(tmp_path)
    _seed_task_and_inbox_row(proj, TASK_ID, status="done")
    inbox_file = str(proj / ".superharness" / "inbox.yaml")

    inbox.main([
        "sync_task_status", "--file", inbox_file,
        "--task", TASK_ID, "--to", "stopped",
        "--now", "2026-01-01T00:05:00Z",
    ])

    assert "synced=0" in capsys.readouterr().out
