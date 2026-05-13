"""Unit tests: auto_fallback_owner policy in inbox_watch.

Verifies that when profile.yaml configures `auto_fallback_owner`:
- Exhausted-retry tasks are reassigned to the fallback owner and get a fresh budget
- Tasks already owned by the fallback owner are left for auto_recover escalation
- Tasks still with retries remaining are untouched
- Invalid fallback_owner values are rejected gracefully
- Escalation to waiting_input only happens after the fallback also exhausts retries
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from superharness.engine.db import get_connection, init_db, now_iso


def _make_project(tmp_path: Path, profile: dict | None = None) -> Path:
    project = tmp_path / "proj"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    if profile is not None:
        (harness / "profile.yaml").write_text(yaml.dump(profile), encoding="utf-8")
    return project


def _seed(project: Path, *, task_owner: str, inbox_agent: str,
          retry_count: int, max_retries: int, task_status: str = "in_progress") -> tuple[str, str]:
    conn = get_connection(str(project))
    init_db(conn)
    now = now_iso()
    task_id = "t-fallback-test"
    inbox_id = "inbox-fallback-test"
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, "
        "acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, "Fallback Test Task", task_owner, task_status, now,
         "[]", "[]", "[]", "[]"),
    )
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, "
        "max_retries, failed_reason, created_at, project_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (inbox_id, task_id, inbox_agent, "failed",
         retry_count, max_retries, "transient error", now, str(project)),
    )
    conn.commit()
    conn.close()
    return task_id, inbox_id


def _read_state(project: Path, task_id: str, inbox_id: str) -> tuple[dict, dict]:
    conn = get_connection(str(project))
    init_db(conn)
    task_row = conn.execute(
        "SELECT status, owner FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    inbox_row = conn.execute(
        "SELECT status, target_agent, retry_count, max_retries, failed_reason "
        "FROM inbox WHERE id=?", (inbox_id,)
    ).fetchone()
    conn.close()
    task = dict(task_row) if task_row else {}
    inbox = dict(inbox_row) if inbox_row else {}
    return task, inbox


class TestAutoFallbackOwnerReassign:
    def test_reassigns_exhausted_task_to_fallback(self, tmp_path: Path):
        """Exhausted task not owned by fallback gets reassigned with a fresh budget."""
        project = _make_project(tmp_path, profile={"auto_fallback_owner": "codex-cli"})
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        task, inbox = _read_state(project, task_id, inbox_id)
        assert task["owner"] == "codex-cli", f"Expected task owner=codex-cli, got {task['owner']}"
        assert inbox["status"] == "pending"
        assert inbox["target_agent"] == "codex-cli"
        assert inbox["retry_count"] == 0
        assert inbox["max_retries"] == 3
        assert "auto-fallback" in (inbox["failed_reason"] or "")

    def test_does_not_reassign_when_already_fallback_owner(self, tmp_path: Path):
        """Task already owned by fallback owner is left alone (exhausted too)."""
        project = _make_project(tmp_path, profile={"auto_fallback_owner": "codex-cli"})
        task_id, inbox_id = _seed(
            project,
            task_owner="codex-cli",
            inbox_agent="codex-cli",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        task, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["status"] == "failed", "Should remain failed for auto_recover to escalate"
        assert task["owner"] == "codex-cli"

    def test_does_not_touch_tasks_with_retries_remaining(self, tmp_path: Path):
        """Items with retry_count < max_retries are left for _auto_retry_failed."""
        project = _make_project(tmp_path, profile={"auto_fallback_owner": "codex-cli"})
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=1,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        _, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["status"] == "failed", "Should remain failed — still has retries"
        assert inbox["target_agent"] == "claude-code"

    def test_no_op_when_no_profile(self, tmp_path: Path):
        """No profile.yaml means no reassignment."""
        project = _make_project(tmp_path, profile=None)
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        _, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["status"] == "failed"
        assert inbox["target_agent"] == "claude-code"

    def test_no_op_when_fallback_owner_not_set(self, tmp_path: Path):
        """Empty auto_fallback_owner means no reassignment."""
        project = _make_project(tmp_path, profile={"auto_retry": True})
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        _, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["status"] == "failed"

    def test_invalid_fallback_owner_rejected(self, tmp_path: Path, capsys):
        """Invalid agent name is rejected with a warning, no state change."""
        project = _make_project(
            tmp_path, profile={"auto_fallback_owner": "unknown-agent"}
        )
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        _, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["status"] == "failed", "Invalid owner — no state change"
        captured = capsys.readouterr()
        assert "invalid auto_fallback_owner" in captured.err

    def test_custom_fallback_max_retries(self, tmp_path: Path):
        """auto_fallback_max_retries controls the retry budget given to fallback owner."""
        project = _make_project(
            tmp_path,
            profile={"auto_fallback_owner": "codex-cli", "auto_fallback_max_retries": 5},
        )
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        _, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["max_retries"] == 5

    def test_skips_done_and_stopped_tasks(self, tmp_path: Path):
        """Tasks in terminal states are not reassigned."""
        project = _make_project(tmp_path, profile={"auto_fallback_owner": "codex-cli"})
        for terminal_status in ("done", "stopped", "archived", "waiting_input"):
            conn = get_connection(str(project))
            init_db(conn)
            now = now_iso()
            conn.execute(
                "INSERT OR REPLACE INTO tasks "
                "(id, title, owner, status, created_at, acceptance_criteria, "
                "test_types, out_of_scope, definition_of_done) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"t-{terminal_status}", f"Task {terminal_status}", "claude-code",
                 terminal_status, now, "[]", "[]", "[]", "[]"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO inbox "
                "(id, task_id, target_agent, status, retry_count, max_retries, "
                "failed_reason, created_at, project_path) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"inbox-{terminal_status}", f"t-{terminal_status}",
                 "claude-code", "failed", 3, 3, "error", now, str(project)),
            )
            conn.commit()
            conn.close()

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        conn = get_connection(str(project))
        init_db(conn)
        for terminal_status in ("done", "stopped", "archived", "waiting_input"):
            row = conn.execute(
                "SELECT target_agent FROM inbox WHERE id=?",
                (f"inbox-{terminal_status}",),
            ).fetchone()
            assert row["target_agent"] == "claude-code", \
                f"Terminal task ({terminal_status}) should not be reassigned"
        conn.close()

    def test_ledger_records_reassignment(self, tmp_path: Path):
        """A ledger entry with action=auto_fallback_owner is recorded on reassignment."""
        project = _make_project(tmp_path, profile={"auto_fallback_owner": "codex-cli"})
        task_id, inbox_id = _seed(
            project,
            task_owner="claude-code",
            inbox_agent="claude-code",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        conn = get_connection(str(project))
        init_db(conn)
        row = conn.execute(
            "SELECT action FROM ledger WHERE task_id=? AND action='auto_fallback_owner'",
            (task_id,),
        ).fetchone()
        conn.close()
        assert row is not None, "Ledger entry for auto_fallback_owner should exist"


class TestFallbackOwnerEscalationAfterExhaustion:
    def test_fallback_exhausted_tasks_left_for_escalation(self, tmp_path: Path):
        """After fallback also fails all retries, auto_recover will escalate to waiting_input."""
        project = _make_project(tmp_path, profile={"auto_fallback_owner": "codex-cli"})
        # Simulate state AFTER fallback owner has also exhausted retries:
        # task.owner == fallback_owner, inbox exhausted
        task_id, inbox_id = _seed(
            project,
            task_owner="codex-cli",
            inbox_agent="codex-cli",
            retry_count=3,
            max_retries=3,
        )

        from superharness.commands.inbox_watch import _auto_fallback_owner_reassign
        _auto_fallback_owner_reassign(str(project))

        # auto_fallback_owner must not touch this — it's up to auto_recover
        _, inbox = _read_state(project, task_id, inbox_id)
        assert inbox["status"] == "failed"
        assert inbox["target_agent"] == "codex-cli"
