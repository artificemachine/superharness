"""TDD: generic burst detection for any auto-flow dispatch.

The peer-review cooldown (v1.54.6) handles one specific shape.
This adds a watcher-level per-task burst check that applies to every
auto-flow: if a task generates >= N failed inbox rows in M minutes
(across any agent or flow), no new inbox row is enqueued for that task
until the window clears.

Shape caught: any fast-failing dispatch loop — peer review, plan dispatch,
review escalation — that recycles through the watcher's cycle faster than
the agent's failure TTL clears the inbox queue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


TASK_ID = "burst.test-task"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _minutes_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_db(tmp_path: Path):
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return conn


def _ensure_task(conn, task_id: str) -> None:
    from superharness.engine import tasks_dao
    now = _now()
    existing = tasks_dao.get(conn, task_id)
    if existing:
        return
    row = tasks_dao.TaskRow(
        id=task_id, title=task_id, owner="claude-code", status="in_progress",
        effort="medium", project_path="/tmp/test", development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1, created_at=now,
    )
    tasks_dao.upsert(conn, row)


def _seed_failed_inbox_row(conn, task_id: str, failed_at: str, item_id: str | None = None) -> str:
    import uuid
    from superharness.engine import inbox_dao
    if item_id is None:
        item_id = f"burst-{uuid.uuid4().hex[:8]}"
    _ensure_task(conn, task_id)
    now = _now()
    inbox_dao.enqueue(
        conn, id=item_id, task_id=task_id, target_agent="claude-code",
        priority=2, max_retries=3, project_path="/tmp/test", plan_only=False, now=now,
    )
    conn.execute(
        "UPDATE inbox SET status='failed', failed_at=? WHERE id=?",
        (failed_at, item_id),
    )
    return item_id


class TestBurstDetection:
    def test_suppressed_when_threshold_reached(self, tmp_path):
        """5 recent failed rows for the same task triggers burst suppression."""
        from superharness.engine.burst_guard import task_burst_suppressed

        conn = _make_db(tmp_path)
        for i in range(5):
            _seed_failed_inbox_row(conn, TASK_ID, failed_at=_minutes_ago(2), item_id=f"burst-{i}")
        conn.commit()

        assert task_burst_suppressed(conn, TASK_ID) is True

    def test_not_suppressed_below_threshold(self, tmp_path):
        """4 recent failed rows — one below threshold — must NOT trigger suppression."""
        from superharness.engine.burst_guard import task_burst_suppressed

        conn = _make_db(tmp_path)
        for i in range(4):
            _seed_failed_inbox_row(conn, TASK_ID, failed_at=_minutes_ago(2), item_id=f"burst-{i}")
        conn.commit()

        assert task_burst_suppressed(conn, TASK_ID) is False

    def test_not_suppressed_with_no_failures(self, tmp_path):
        """A fresh task with no inbox history must not be suppressed."""
        from superharness.engine.burst_guard import task_burst_suppressed

        conn = _make_db(tmp_path)
        assert task_burst_suppressed(conn, "no.prior.failures") is False

    def test_not_suppressed_when_failures_are_old(self, tmp_path):
        """Failures outside the window (>10 min ago) must not count toward the threshold."""
        from superharness.engine.burst_guard import task_burst_suppressed

        conn = _make_db(tmp_path)
        for i in range(10):
            _seed_failed_inbox_row(conn, TASK_ID, failed_at=_minutes_ago(15), item_id=f"old-{i}")
        conn.commit()

        assert task_burst_suppressed(conn, TASK_ID) is False

    def test_only_counts_failed_status(self, tmp_path):
        """Pending and done rows must not count toward the burst threshold."""
        from superharness.engine.burst_guard import task_burst_suppressed

        conn = _make_db(tmp_path)
        _ensure_task(conn, TASK_ID)
        now = _now()
        # Unique index allows only 1 active pending row per (task_id, target_agent).
        # Use distinct target agents so 5 pending rows can coexist.
        # Done rows are excluded from the partial unique index.
        # Use uuid-based IDs to avoid collision with stale XDG state from prior runs.
        import uuid
        agents = ["agent-a", "agent-b", "agent-c", "agent-d", "agent-e"]
        for agent in agents:
            conn.execute(
                "INSERT INTO inbox (id, task_id, target_agent, status, priority, "
                "max_retries, project_path, plan_only, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"pending-{uuid.uuid4().hex[:8]}", TASK_ID, agent, "pending", 2, 3, "/tmp", 0, now),
            )
        for _ in range(5):
            conn.execute(
                "INSERT INTO inbox (id, task_id, target_agent, status, priority, "
                "max_retries, project_path, plan_only, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"done-{uuid.uuid4().hex[:8]}", TASK_ID, "claude-code", "done", 2, 3, "/tmp", 0, now),
            )
        conn.commit()

        assert task_burst_suppressed(conn, TASK_ID) is False

    def test_different_task_failures_do_not_suppress(self, tmp_path):
        """Failures for task B must not suppress task A."""
        from superharness.engine.burst_guard import task_burst_suppressed

        conn = _make_db(tmp_path)
        for i in range(10):
            _seed_failed_inbox_row(conn, "burst.other-task", failed_at=_minutes_ago(2),
                                   item_id=f"other-{i}")
        conn.commit()

        assert task_burst_suppressed(conn, TASK_ID) is False

    def test_auto_peer_approve_respects_burst(self, tmp_path):
        """_auto_peer_approve_plans must skip tasks with an active burst."""
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.commands.inbox_watch import _auto_peer_approve_plans

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        (sh / "profile.yaml").write_text(
            "auto_approve_plans: true\nautonomy: ai_driven\nauto_dispatch: true\n"
        )
        (sh / "inbox.yaml").write_text("items: []\n")

        conn = get_connection(str(tmp_path))
        init_db(conn)
        now = _now()
        row = tasks_dao.TaskRow(
            id=TASK_ID, title="burst task", owner="claude-code", status="plan_proposed",
            effort="medium", project_path=str(tmp_path), development_method=None,
            acceptance_criteria=["done"], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None, version=1, created_at=now,
        )
        tasks_dao.upsert(conn, row)
        conn.execute("UPDATE tasks SET workflow='implementation' WHERE id=?", (TASK_ID,))

        for i in range(5):
            _seed_failed_inbox_row(conn, TASK_ID, failed_at=_minutes_ago(2), item_id=f"bp-{i}")
        conn.commit()
        conn.close()

        count = _auto_peer_approve_plans(str(tmp_path))
        assert count == 0, "burst-suppressed task must not get a new peer-review row"

    def test_auto_enqueue_todo_respects_burst(self, tmp_path):
        """auto_enqueue_todo must skip tasks with an active burst."""
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.commands.inbox_watch import auto_enqueue_todo

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        (sh / "profile.yaml").write_text(
            "auto_dispatch: true\nautonomy: ai_driven\n"
        )
        (sh / "inbox.yaml").write_text("items: []\n")

        conn = get_connection(str(tmp_path))
        init_db(conn)
        now = _now()
        row = tasks_dao.TaskRow(
            id=TASK_ID, title="burst todo", owner="claude-code", status="todo",
            effort="medium", project_path=str(tmp_path), development_method=None,
            acceptance_criteria=["done"], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None, version=1, created_at=now,
        )
        tasks_dao.upsert(conn, row)

        for i in range(5):
            _seed_failed_inbox_row(conn, TASK_ID, failed_at=_minutes_ago(2), item_id=f"bt-{i}")
        conn.commit()
        conn.close()

        count = auto_enqueue_todo(str(tmp_path))
        assert count == 0, "burst-suppressed todo task must not get a new dispatch row"
