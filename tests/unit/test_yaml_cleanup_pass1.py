"""RED tests for Pass 1 YAML→SQLite migration.

Covers: verify.py, subtask_cancel.py, subtask_aggregator.py,
        diff.py, auto_dispatch.py, inbox_enqueue.py

All tests seed SQLite directly — no contract.yaml or inbox.yaml written.
All tests call the NEW interface (project_dir, not contract_file).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_project(tmp_path: Path, *, tasks: list[dict] | None = None) -> Path:
    """Bootstrap a .superharness dir with SQLite and optional tasks."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "handoffs").mkdir()

    conn = get_connection(str(project))
    init_db(conn)

    for t in (tasks or []):
        extras: dict = {}
        if "subtasks" in t:
            extras["subtasks"] = t["subtasks"]
        row = TaskRow(
            id=str(t["id"]),
            title=str(t.get("title", t["id"])),
            owner=t.get("owner", "claude-code"),
            status=str(t.get("status", "todo")),
            effort=t.get("effort", "small"),
            project_path=str(project),
            development_method=t.get("development_method", "tdd"),
            acceptance_criteria=t.get("acceptance_criteria", []),
            test_types=t.get("test_types", []),
            out_of_scope=t.get("out_of_scope", []),
            definition_of_done=t.get("definition_of_done", []),
            context=t.get("context"),
            tdd=t.get("tdd"),
            version=1,
            created_at=_now(),
            blocked_by=None,
            parent_id=None,
            verified=t.get("verified", False),
        )
        tasks_dao.upsert(conn, row)
        if extras:
            conn.execute(
                "UPDATE tasks SET extras_json = ? WHERE id = ?",
                (json.dumps(extras), str(t["id"])),
            )

    conn.commit()
    conn.close()
    return project


# ──────────────────────────────────────────────────────────────────────────────
# verify.py
# ──────────────────────────────────────────────────────────────────────────────

class TestVerifyCommand:
    def test_verify_pass_writes_sqlite_not_yaml(self, tmp_path: Path) -> None:
        """verify() must accept project_dir and write verified=True to SQLite."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "feat.x", "status": "report_ready", "owner": "claude-code"},
        ])
        from superharness.commands.verify import verify
        rc = verify(str(project), "feat.x", "manual", "pass", "operator")
        assert rc == 0

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "feat.x")
        conn.close()
        assert row is not None
        assert row.verified is True
        assert row.verified_at is not None
        assert row.verified_by == "operator"

    def test_verify_fail_writes_sqlite(self, tmp_path: Path) -> None:
        """verify(result='fail') must set verified=False in SQLite."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "feat.y", "status": "report_ready"},
        ])
        from superharness.commands.verify import verify
        rc = verify(str(project), "feat.y", "manual", "fail", "operator")
        assert rc == 0

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "feat.y")
        conn.close()
        assert row is not None
        assert row.verified is False

    def test_verify_appends_ledger(self, tmp_path: Path) -> None:
        """verify() must append a VERIFY entry to ledger.md."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "feat.z", "status": "report_ready"},
        ])
        from superharness.commands.verify import verify
        verify(str(project), "feat.z", "automated", "pass", "ci-bot")
        ledger = (project / ".superharness" / "ledger.md").read_text()
        assert "VERIFY PASS" in ledger
        assert "feat.z" in ledger

    def test_verify_missing_task_returns_nonzero(self, tmp_path: Path) -> None:
        """verify() on a nonexistent task must exit non-zero."""
        project = _seed_project(tmp_path)
        from superharness.commands.verify import verify
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            verify(str(project), "nonexistent", "manual", "pass", "op")
        assert exc_info.value.code != 0

    def test_verify_no_contract_yaml_needed(self, tmp_path: Path) -> None:
        """verify() must work without any contract.yaml present."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "feat.no-yaml", "status": "report_ready"},
        ])
        assert not (project / ".superharness" / "contract.yaml").exists()
        from superharness.commands.verify import verify
        rc = verify(str(project), "feat.no-yaml", "unit-tests", "pass", "ci")
        assert rc == 0


# ──────────────────────────────────────────────────────────────────────────────
# subtask_cancel.py
# ──────────────────────────────────────────────────────────────────────────────

class TestSubtaskCancel:
    def _project_with_subtasks(self, tmp_path: Path, sub_status: str = "pending") -> Path:
        subtasks = [
            {"id": "sub-1", "title": "First sub", "status": sub_status},
            {"id": "sub-2", "title": "Second sub", "status": "pending"},
        ]
        return _seed_project(tmp_path, tasks=[
            {"id": "task.parent", "status": "in_progress", "subtasks": subtasks},
        ])

    def test_cancel_subtask_writes_sqlite(self, tmp_path: Path) -> None:
        """cancel_subtask() must accept project_dir and persist cancel in extras_json."""
        project = self._project_with_subtasks(tmp_path)
        from superharness.commands.subtask_cancel import cancel_subtask
        rc = cancel_subtask(str(project), "task.parent", "sub-1", "operator", "no longer needed")
        assert rc == 0

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "task.parent")
        conn.close()
        assert row is not None
        extras = json.loads(row.extras_json or "{}")
        subs = {s["id"]: s for s in extras.get("subtasks", [])}
        assert subs["sub-1"]["status"] == "cancelled"
        assert subs["sub-2"]["status"] == "pending"

    def test_cancel_done_subtask_blocked(self, tmp_path: Path) -> None:
        """cancel_subtask() must refuse to cancel a done subtask."""
        project = self._project_with_subtasks(tmp_path, sub_status="done")
        from superharness.commands.subtask_cancel import cancel_subtask
        rc = cancel_subtask(str(project), "task.parent", "sub-1", "op", "reason")
        assert rc != 0

    def test_cancel_missing_subtask_returns_error(self, tmp_path: Path) -> None:
        """cancel_subtask() on an unknown sub_id must return non-zero."""
        project = self._project_with_subtasks(tmp_path)
        from superharness.commands.subtask_cancel import cancel_subtask
        rc = cancel_subtask(str(project), "task.parent", "sub-999", "op", "reason")
        assert rc != 0

    def test_cancel_appends_ledger(self, tmp_path: Path) -> None:
        """cancel_subtask() must append a SUBTASK_CANCEL entry to ledger.md."""
        project = self._project_with_subtasks(tmp_path)
        from superharness.commands.subtask_cancel import cancel_subtask
        cancel_subtask(str(project), "task.parent", "sub-2", "op", "scope reduced")
        ledger = (project / ".superharness" / "ledger.md").read_text()
        assert "SUBTASK_CANCEL" in ledger
        assert "sub-2" in ledger

    def test_cancel_no_contract_yaml_needed(self, tmp_path: Path) -> None:
        """cancel_subtask() must work without any contract.yaml present."""
        project = self._project_with_subtasks(tmp_path)
        assert not (project / ".superharness" / "contract.yaml").exists()
        from superharness.commands.subtask_cancel import cancel_subtask
        rc = cancel_subtask(str(project), "task.parent", "sub-1", "op", "reason")
        assert rc == 0


# ──────────────────────────────────────────────────────────────────────────────
# subtask_aggregator.py
# ──────────────────────────────────────────────────────────────────────────────

class TestSubtaskAggregator:
    def _project_with_subtasks(self, tmp_path: Path) -> Path:
        return _seed_project(tmp_path, tasks=[
            {
                "id": "task.agg",
                "status": "in_progress",
                "subtasks": [
                    {"id": "s1", "title": "Sub 1", "status": "pending"},
                    {"id": "s2", "title": "Sub 2", "status": "pending"},
                ],
            }
        ])

    def test_aggregator_accepts_project_dir(self, tmp_path: Path) -> None:
        """SubtaskAggregator(project_dir) must work without contract.yaml."""
        from superharness.engine.subtask_aggregator import SubtaskAggregator, SubtaskResult
        project = self._project_with_subtasks(tmp_path)
        assert not (project / ".superharness" / "contract.yaml").exists()
        agg = SubtaskAggregator(str(project))
        results = [
            SubtaskResult("s1", "done", 100, 0.01, "claude-code", "ok"),
            SubtaskResult("s2", "done", 200, 0.02, "claude-code", "ok"),
        ]
        summary = agg.record_results("task.agg", results)
        assert summary.all_done is True
        assert summary.any_failed is False

    def test_aggregator_sets_parent_report_ready(self, tmp_path: Path) -> None:
        """SubtaskAggregator must set parent task status to report_ready in SQLite."""
        from superharness.engine.subtask_aggregator import SubtaskAggregator, SubtaskResult
        project = self._project_with_subtasks(tmp_path)
        agg = SubtaskAggregator(str(project))
        results = [
            SubtaskResult("s1", "done", 100, 0.01, "claude-code", "ok"),
            SubtaskResult("s2", "done", 200, 0.02, "claude-code", "ok"),
        ]
        agg.record_results("task.agg", results)

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "task.agg")
        conn.close()
        assert row is not None
        assert row.status == "report_ready"

    def test_aggregator_sets_parent_failed_on_any_failure(self, tmp_path: Path) -> None:
        """SubtaskAggregator must set parent task to failed when any subtask fails."""
        from superharness.engine.subtask_aggregator import SubtaskAggregator, SubtaskResult
        project = self._project_with_subtasks(tmp_path)
        agg = SubtaskAggregator(str(project))
        results = [
            SubtaskResult("s1", "done", 100, 0.01, "claude-code", "ok"),
            SubtaskResult("s2", "failed", 0, 0.0, "claude-code", "", error="timeout"),
        ]
        summary = agg.record_results("task.agg", results)
        assert summary.any_failed is True

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "task.agg")
        conn.close()
        assert row is not None
        assert row.status == "failed"

    def test_aggregator_updates_subtask_statuses_in_sqlite(self, tmp_path: Path) -> None:
        """SubtaskAggregator must persist updated subtask statuses into extras_json."""
        from superharness.engine.subtask_aggregator import SubtaskAggregator, SubtaskResult
        project = self._project_with_subtasks(tmp_path)
        agg = SubtaskAggregator(str(project))
        results = [
            SubtaskResult("s1", "done", 50, 0.005, "haiku", "done"),
        ]
        agg.record_results("task.agg", results)

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "task.agg")
        conn.close()
        extras = json.loads(row.extras_json or "{}")
        subs = {s["id"]: s for s in extras.get("subtasks", [])}
        assert subs["s1"]["status"] == "done"
        assert subs["s1"]["model_used"] == "haiku"


# ──────────────────────────────────────────────────────────────────────────────
# diff.py
# ──────────────────────────────────────────────────────────────────────────────

class TestDiffFindTask:
    def test_find_task_reads_from_sqlite(self, tmp_path: Path) -> None:
        """_find_task must return task metadata from SQLite without contract.yaml."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "task.diff-me", "status": "in_progress", "owner": "claude-code"},
        ])
        assert not (project / ".superharness" / "contract.yaml").exists()
        from superharness.commands.diff import _find_task
        result = _find_task(project, "task.diff-me")
        assert result is not None
        assert result["id"] == "task.diff-me"
        assert result["owner"] == "claude-code"

    def test_find_task_returns_none_for_missing(self, tmp_path: Path) -> None:
        """_find_task must return None for an unknown task_id."""
        project = _seed_project(tmp_path)
        from superharness.commands.diff import _find_task
        result = _find_task(project, "nonexistent")
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# auto_dispatch.py
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoDispatch:
    def test_auto_dispatch_reads_todo_tasks_from_sqlite(self, tmp_path: Path) -> None:
        """run_auto_dispatch must enqueue todo tasks from SQLite without contract.yaml."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "task.todo-1", "status": "todo", "owner": "claude-code"},
        ])
        assert not (project / ".superharness" / "contract.yaml").exists()
        from superharness.commands.auto_dispatch import run_auto_dispatch
        rc = run_auto_dispatch(str(project), dry_run=True)
        assert rc == 0

    def test_auto_dispatch_enqueues_into_sqlite(self, tmp_path: Path) -> None:
        """run_auto_dispatch must write enqueued items to SQLite inbox (not yaml)."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "task.enq-1", "status": "todo", "owner": "claude-code"},
        ])
        from superharness.commands.auto_dispatch import run_auto_dispatch
        rc = run_auto_dispatch(str(project), dry_run=False)
        assert rc == 0

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(str(project))
        init_db(conn)
        items = inbox_dao.get_all(conn)
        conn.close()
        task_ids = [i.task_id for i in items]
        assert "task.enq-1" in task_ids

    def test_auto_dispatch_skips_blocked_tasks(self, tmp_path: Path) -> None:
        """run_auto_dispatch must skip tasks with unresolved blocked_by."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "blocker", "status": "in_progress"},
            {"id": "task.blocked", "status": "todo", "owner": "claude-code"},
        ])
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(project))
        init_db(conn)
        conn.execute("UPDATE tasks SET blocked_by_raw = ? WHERE id = ?",
                     (json.dumps(["blocker"]), "task.blocked"))
        conn.commit()
        conn.close()

        from superharness.commands.auto_dispatch import run_auto_dispatch
        rc = run_auto_dispatch(str(project), dry_run=False)
        assert rc == 0

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(str(project))
        init_db(conn)
        items = inbox_dao.get_all(conn)
        conn.close()
        task_ids = [i.task_id for i in items]
        assert "task.blocked" not in task_ids

    def test_auto_dispatch_no_todo_tasks(self, tmp_path: Path) -> None:
        """run_auto_dispatch returns 0 and prints message when no todo tasks exist."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "task.done-already", "status": "done"},
        ])
        from superharness.commands.auto_dispatch import run_auto_dispatch
        rc = run_auto_dispatch(str(project), dry_run=False)
        assert rc == 0


# ──────────────────────────────────────────────────────────────────────────────
# inbox_enqueue.py
# ──────────────────────────────────────────────────────────────────────────────

class TestInboxEnqueue:
    def test_enqueue_cmd_writes_sqlite_without_inbox_yaml(self, tmp_path: Path) -> None:
        """enqueue_cmd must write to SQLite inbox without creating inbox.yaml."""
        project = _seed_project(tmp_path, tasks=[
            {
                "id": "task.eq-1",
                "status": "plan_approved",
                "owner": "claude-code",
            },
        ])
        assert not (project / ".superharness" / "inbox.yaml").exists()
        from superharness.commands.inbox_enqueue import enqueue_cmd
        rc = enqueue_cmd(
            project_dir=str(project),
            target="claude-code",
            task_id="task.eq-1",
            item_id="test-item-001",
            priority=2,
            plan_only=False,
        )
        assert rc == 0

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(str(project))
        init_db(conn)
        items = inbox_dao.get_all(conn)
        conn.close()
        ids = [i.id for i in items]
        assert "test-item-001" in ids

    def test_enqueue_cmd_no_contract_yaml_needed(self, tmp_path: Path) -> None:
        """enqueue_cmd must not require contract.yaml to be present."""
        project = _seed_project(tmp_path, tasks=[
            {"id": "task.eq-2", "status": "plan_approved", "owner": "claude-code"},
        ])
        assert not (project / ".superharness" / "contract.yaml").exists()
        from superharness.commands.inbox_enqueue import enqueue_cmd
        rc = enqueue_cmd(
            project_dir=str(project),
            target="claude-code",
            task_id="task.eq-2",
            item_id="test-item-002",
            priority=2,
            plan_only=False,
        )
        assert rc == 0

    def test_enqueue_cmd_rejects_done_task(self, tmp_path: Path) -> None:
        """enqueue_cmd must block enqueueing a task that is already done."""
        import pytest
        project = _seed_project(tmp_path, tasks=[
            {"id": "task.eq-done", "status": "done", "owner": "claude-code"},
        ])
        from superharness.commands.inbox_enqueue import enqueue_cmd
        with pytest.raises(SystemExit) as exc_info:
            enqueue_cmd(
                project_dir=str(project),
                target="claude-code",
                task_id="task.eq-done",
                item_id="test-item-done",
                priority=2,
                plan_only=False,
            )
        assert exc_info.value.code != 0
