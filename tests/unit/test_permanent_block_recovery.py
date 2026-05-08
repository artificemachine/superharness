"""E2E test: permanent block auto-recovery.

Verifies that when the lifecycle gate permanently blocks a dispatch,
auto-mode escalates the task to waiting_input (not todo) and records
the gate reason, stopping the infinite re-dispatch cycle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db, now_iso


@pytest.fixture
def project_with_blocked_task(tmp_path: Path) -> Path:
    """Project with a task that would be permanently blocked by lifecycle gate."""
    project = tmp_path / "proj"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    
    conn = get_connection(str(project))
    init_db(conn)
    now = now_iso()

    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("blocked-task", "Blocked Task", "claude-code", "in_progress", now, '[]', '[]', '[]', '[]'),
    )
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, failed_reason, created_at, project_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("inbox-perm-block", "blocked-task", "claude-code", "failed", 3, 3,
         "permanent block (lifecycle gate): lifecycle gate rejected (permanent block)",
         now, ""),
    )
    conn.commit()
    conn.close()
    return project


class TestPermanentBlockRecovery:
    def test_task_escalated_to_waiting_input(self, project_with_blocked_task: Path):
        """Permanent block should escalate task to waiting_input, NOT todo.
        
        waiting_input stops the auto-re-dispatch cycle. The operator must
        fix the underlying lifecycle violation (e.g., approve plan) before
        re-dispatching.
        """
        from superharness.commands.inbox_watch import _reconcile_permanent_blocks
        
        project = str(project_with_blocked_task)
        count = _reconcile_permanent_blocks(project)
        
        assert count == 1, f"Expected 1 task escalated, got {count}"
        
        conn = get_connection(project)
        init_db(conn)
        task = conn.execute("SELECT status, failed_reason FROM tasks WHERE id='blocked-task'").fetchone()
        assert task is not None
        assert task["status"] == "waiting_input", f"Expected waiting_input, got {task['status']}"
        assert "permanent block" in (task["failed_reason"] or "").lower(), \
            f"failed_reason should contain gate info, got: {task['failed_reason']}"
        
        inbox = conn.execute("SELECT status FROM inbox WHERE id='inbox-perm-block'").fetchone()
        assert inbox["status"] == "done", "Inbox should be cleaned"
        conn.close()

    def test_no_action_on_retryable_failure(self, project_with_blocked_task: Path):
        """Tasks with retries remaining should NOT be escalated."""
        from superharness.commands.inbox_watch import _reconcile_permanent_blocks
        
        project = str(project_with_blocked_task)
        conn = get_connection(project)
        init_db(conn)
        conn.execute("UPDATE inbox SET retry_count=1, max_retries=3, failed_reason='transient error' WHERE id='inbox-perm-block'")
        conn.commit()
        conn.close()
        
        count = _reconcile_permanent_blocks(project)
        assert count == 0, "Retryable failures should not escalate"
        
        conn = get_connection(project)
        init_db(conn)
        task = conn.execute("SELECT status FROM tasks WHERE id='blocked-task'").fetchone()
        assert task["status"] == "in_progress", "Retryable failures should not change task status"
        conn.close()

    def test_only_escalates_in_progress_tasks(self, project_with_blocked_task: Path):
        """Tasks not in in_progress should not be affected."""
        from superharness.commands.inbox_watch import _reconcile_permanent_blocks
        
        project = str(project_with_blocked_task)
        conn = get_connection(project)
        init_db(conn)
        conn.execute("UPDATE tasks SET status='done' WHERE id='blocked-task'")
        conn.commit()
        conn.close()
        
        count = _reconcile_permanent_blocks(project)
        assert count == 0, "Done tasks should not be escalated"

    def test_waiting_input_not_auto_dispatched(self, project_with_blocked_task: Path):
        """waiting_input tasks must not be auto-dispatched by the watcher.
        
        This is the safety property that prevents the infinite re-dispatch cycle.
        """
        from superharness.engine.next_action import allowed_statuses_for_workflow
        
        # The watcher only dispatches tasks with allowed statuses
        allowed = allowed_statuses_for_workflow("implementation")
        assert "waiting_input" not in allowed, \
            f"waiting_input must NOT be auto-dispatched. Allowed: {allowed}"
