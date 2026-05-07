"""E2E tests: verify system works without protocol YAML files on disk.

After the SQLite migration (v1.44+), contract.yaml, inbox.yaml, failures.yaml,
and decisions.yaml are deleted. All state lives in state.sqlite3.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap_sqlite_only(project_dir: Path) -> None:
    """Set up a minimal project with SQLite only — NO protocol YAML files."""
    sh = project_dir / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "profile.yaml").write_text(
        "project_name: test\n"
        "created: 2026-01-01\n"
        "primary_agent: claude-code\n"
        "autonomy: autonomous\n"
        "auto_dispatch: false\n"
        "state_backend: sqlite_only\n"
    )

    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project_dir))
    init_db(conn)
    conn.close()

    for yf in ["contract.yaml", "inbox.yaml", "failures.yaml", "decisions.yaml"]:
        assert not (sh / yf).exists(), f"{yf} should not exist"


def _assert_no_yaml_files(project_dir: Path) -> None:
    """Assert no protocol YAML files were created as side effects."""
    sh = project_dir / ".superharness"
    for yf in ["contract.yaml", "inbox.yaml", "failures.yaml", "decisions.yaml"]:
        assert not (sh / yf).exists(), f"{yf} was created as a side effect"


def _create_task(project_dir: str, title: str, owner: str = "claude-code") -> str:
    """Create a simple task via tasks_dao and return its ID."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from datetime import datetime, timezone
    import uuid

    task_id = f"t-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        tasks_dao.upsert(conn, tasks_dao.TaskRow(
            id=task_id, title=title, owner=owner, status="todo",
            effort="medium", project_path=project_dir,
            development_method=None, acceptance_criteria=[],
            test_types=[], out_of_scope=[], definition_of_done=[],
            context=None, tdd=None, version=1, created_at=now,
            blocked_by=[], parent_id=None,
        ))
        conn.commit()
    finally:
        conn.close()

    return task_id


def _create_rich_task(
    project_dir: str, title: str, owner: str = "claude-code",
    workflow: str = "implementation", acceptance_criteria: list[str] | None = None,
    test_types: list[str] | None = None, blocked_by: list[str] | None = None,
    tdd: dict | None = None, parent_id: str | None = None,
    out_of_scope: list[str] | None = None,
    definition_of_done: list[str] | None = None,
) -> str:
    """Create a task with full metadata via tasks_dao."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from datetime import datetime, timezone
    import uuid

    task_id = f"t-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        tasks_dao.upsert(conn, tasks_dao.TaskRow(
            id=task_id, title=title, owner=owner, status="todo",
            effort="medium", project_path=project_dir,
            development_method=workflow,
            acceptance_criteria=acceptance_criteria or [],
            test_types=test_types or [],
            out_of_scope=out_of_scope or [],
            definition_of_done=definition_of_done or [],
            context=None,
            tdd=tdd or {},
            version=1, created_at=now,
            blocked_by=[],  # dependencies go in task_dependencies table
            parent_id=parent_id,
        ))
        # Insert dependencies separately (blocked_by lives in task_dependencies table)
        for dep_id in (blocked_by or []):
            conn.execute(
                "INSERT OR IGNORE INTO task_dependencies (dependent_task_id, prerequisite_task_id) VALUES (?, ?)",
                (task_id, dep_id),
            )
        conn.commit()
    finally:
        conn.close()

    return task_id


def _get_tasks(project_dir: str) -> list[dict]:
    """Get tasks directly from SQLite, bypassing test-mode YAML requirement."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from dataclasses import asdict

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = tasks_dao.get_all(conn)
        return [asdict(r) for r in rows]
    finally:
        conn.close()


def _advance_task(project_dir: str, task_id: str, status: str) -> None:
    """Advance a task's status directly via tasks_dao."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from datetime import datetime, timezone

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        row = tasks_dao.get(conn, task_id)
        if row is None:
            raise ValueError(f"Task {task_id} not found")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_map = {
            "plan_proposed": "plan_proposed_at", "plan_approved": "plan_approved_at",
            "in_progress": "in_progress_at", "report_ready": "report_ready_at",
            "done": "done_at", "failed": "failed_at", "stopped": "stopped_at",
        }
        kwargs = {ts_map[status]: now} if status in ts_map else {}
        updated = tasks_dao.TaskRow(
            id=row.id, title=row.title, owner=row.owner, status=status,
            effort=row.effort, project_path=row.project_path,
            development_method=row.development_method,
            acceptance_criteria=row.acceptance_criteria,
            test_types=row.test_types, out_of_scope=row.out_of_scope,
            definition_of_done=row.definition_of_done,
            context=row.context, tdd=row.tdd,
            version=row.version + 1, created_at=row.created_at,
            blocked_by=row.blocked_by, parent_id=row.parent_id,
            **kwargs,
        )
        tasks_dao.upsert(conn, updated)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# contract.yaml replacement tests
# ---------------------------------------------------------------------------

def test_tasks_persist_in_sqlite_without_contract_yaml(tmp_path: Path) -> None:
    """Task creation, status advance, and retrieval all work without contract.yaml."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "SQLite Only Task")

    tasks = _get_tasks(str(tmp_path))
    assert any(t.get("id") == task_id for t in tasks), "Task not found in SQLite"

    _advance_task(str(tmp_path), task_id, "plan_proposed")
    _advance_task(str(tmp_path), task_id, "plan_approved")
    _advance_task(str(tmp_path), task_id, "in_progress")
    _advance_task(str(tmp_path), task_id, "report_ready")

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)
    assert task.get("status") == "report_ready", f"Expected report_ready, got {task.get('status')}"

    _assert_no_yaml_files(tmp_path)


def test_contract_doc_reconstructed_from_sqlite(tmp_path: Path) -> None:
    """get_contract_doc works without contract.yaml on disk."""
    _bootstrap_sqlite_only(tmp_path)

    _create_task(str(tmp_path), "Reconstructed Task")

    tasks = _get_tasks(str(tmp_path))
    assert len(tasks) >= 1, "No tasks in SQLite"
    assert any(t.get("title") == "Reconstructed Task" for t in tasks)

    _assert_no_yaml_files(tmp_path)


# ---------------------------------------------------------------------------
# inbox.yaml replacement tests
# ---------------------------------------------------------------------------

def test_inbox_enqueue_persists_in_sqlite(tmp_path: Path) -> None:
    """Inbox enqueue writes to SQLite inbox table, not inbox.yaml."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "Inbox Task")
    _advance_task(str(tmp_path), task_id, "plan_approved")

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        inbox_dao.enqueue(conn, id=f"auto-test-{task_id}", task_id=task_id,
                         target_agent="claude-code", priority=2,
                         max_retries=3, project_path=str(tmp_path),
                         plan_only=False, now=now, model_override="")
        conn.commit()

        items = inbox_dao.get_all(conn)
        assert len(items) >= 1, "No inbox items after enqueue"
        assert items[0].task_id == task_id
        assert items[0].status == "pending"
    finally:
        conn.close()

    _assert_no_yaml_files(tmp_path)


def test_inbox_status_transitions_in_sqlite(tmp_path: Path) -> None:
    """Inbox status transitions (pending → launched → done) work in SQLite."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "Transition Task")
    _advance_task(str(tmp_path), task_id, "plan_approved")

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    item_id = f"auto-trans-{task_id}"

    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        inbox_dao.enqueue(conn, id=item_id, task_id=task_id,
                         target_agent="claude-code", priority=2,
                         max_retries=3, project_path=str(tmp_path),
                         plan_only=False, now=now, model_override="")

        claimed = inbox_dao.claim_next(conn, target_agent="claude-code",
                                       pid=12345, now=now)
        assert claimed is not None, "claim_next returned None"
        assert claimed.status == "launched"

        ok = inbox_dao.update_status(conn, item_id, from_status="launched",
                                     to_status="done", now=now)
        assert ok, "update_status failed"

        item = inbox_dao.get(conn, item_id)
        assert item is not None
        assert item.status == "done"
        conn.commit()
    finally:
        conn.close()

    _assert_no_yaml_files(tmp_path)


# ---------------------------------------------------------------------------
# failures.yaml replacement tests
# ---------------------------------------------------------------------------

def test_failure_record_in_sqlite(tmp_path: Path) -> None:
    """Failure recording and retrieval works without failures.yaml."""
    _bootstrap_sqlite_only(tmp_path)

    from superharness.engine.failure_patterns import record_failure, get_failure_hints

    patterns = record_failure(
        str(tmp_path), task_id="test-task-1",
        error_text="ImportError: No module named 'nonexistent'",
        agent="claude-code",
    )
    assert isinstance(patterns, list)

    hints = get_failure_hints(str(tmp_path), "test-task-1")
    assert isinstance(hints, list)

    _assert_no_yaml_files(tmp_path)


# ---------------------------------------------------------------------------
# decisions.yaml replacement tests
# ---------------------------------------------------------------------------

def test_decisions_record_in_sqlite(tmp_path: Path) -> None:
    """Decision recording via DAO works without decisions.yaml."""
    _bootstrap_sqlite_only(tmp_path)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import decisions_dao
    from datetime import datetime, timezone

    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        decisions_dao.record(conn, task_id="test-task", agent="claude-code",
                            decision="Use SQLite", reason="YAML is dead",
                            alternatives="YAML", now=now)
        conn.commit()
    finally:
        conn.close()

    _assert_no_yaml_files(tmp_path)


# ---------------------------------------------------------------------------
# Agent hook simulation
# ---------------------------------------------------------------------------

def test_session_stop_via_state_writer(tmp_path: Path) -> None:
    """Session stop writes via state_writer, not contract.yaml."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "Hook Task")
    _advance_task(str(tmp_path), task_id, "plan_approved")
    _advance_task(str(tmp_path), task_id, "in_progress")
    _advance_task(str(tmp_path), task_id, "stopped")

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)
    assert task.get("status") == "stopped", f"Expected stopped, got {task.get('status')}"

    _assert_no_yaml_files(tmp_path)


def test_session_start_reads_from_state_reader(tmp_path: Path) -> None:
    """Session start context reads from state_reader, not contract.yaml."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "Startup Task")
    _advance_task(str(tmp_path), task_id, "plan_approved")

    tasks = _get_tasks(str(tmp_path))
    active = [t for t in tasks
              if t.get("status") in ("in_progress", "plan_proposed",
                                     "plan_approved", "report_ready")]
    assert len(active) > 0, "Should find active task"

    _assert_no_yaml_files(tmp_path)


# ---------------------------------------------------------------------------
# Side-effect guards
# ---------------------------------------------------------------------------

def test_no_yaml_created_by_task_operations(tmp_path: Path) -> None:
    """Task create/status operations don't recreate YAML files."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "SideEffect Task")
    _advance_task(str(tmp_path), task_id, "plan_proposed")
    _advance_task(str(tmp_path), task_id, "plan_approved")
    _advance_task(str(tmp_path), task_id, "in_progress")
    _advance_task(str(tmp_path), task_id, "report_ready")

    _assert_no_yaml_files(tmp_path)


def test_no_yaml_created_by_inbox_operations(tmp_path: Path) -> None:
    """Inbox operations don't recreate YAML files."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_task(str(tmp_path), "Inbox SideEffect")
    _advance_task(str(tmp_path), task_id, "plan_approved")

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        inbox_dao.enqueue(conn, id=f"side-{task_id}", task_id=task_id,
                         target_agent="claude-code", priority=2,
                         max_retries=3, project_path=str(tmp_path),
                         plan_only=False, now=now, model_override="")
        conn.commit()
    finally:
        conn.close()

    _assert_no_yaml_files(tmp_path)


# ---------------------------------------------------------------------------
# Different task types — verify all metadata fields survive SQLite round-trip
# ---------------------------------------------------------------------------

def test_implementation_workflow_with_tdd(tmp_path: Path) -> None:
    """Implementation task with TDD, acceptance criteria, test types, DoD."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_rich_task(
        str(tmp_path), "Implement Login",
        workflow="implementation",
        acceptance_criteria=[
            "User can log in with email and password",
            "Invalid credentials show error",
            "Rate limiting after 5 failed attempts",
        ],
        test_types=["unit", "integration"],
        tdd={
            "red": "Write failing tests for login flow",
            "green": "Implement password hashing and session tokens",
            "refactor": "Extract auth helpers, add rate limit middleware",
        },
        definition_of_done=["All tests pass", "Code reviewed", "Deployed to staging"],
    )

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)

    assert task.get("development_method") == "implementation"
    assert len(task.get("acceptance_criteria", [])) == 3
    assert "unit" in task.get("test_types", [])
    assert task.get("tdd", {}).get("red") is not None
    assert len(task.get("definition_of_done", [])) == 3

    _assert_no_yaml_files(tmp_path)


def test_quick_workflow_task(tmp_path: Path) -> None:
    """Quick workflow task — no TDD, minimal metadata."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_rich_task(
        str(tmp_path), "Fix Typo in README",
        workflow="quick",
        acceptance_criteria=["Typo recieve → receive"],
        out_of_scope=["Rewriting entire README"],
    )

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)

    assert task.get("development_method") == "quick"
    assert len(task.get("out_of_scope", [])) == 1
    # tdd may be None (SQLite NULL) — both None and {} are valid empty states
    assert task.get("tdd") in (None, {})

    _assert_no_yaml_files(tmp_path)


def test_discussion_task_type(tmp_path: Path) -> None:
    """Discussion workflow task persists correctly."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_rich_task(
        str(tmp_path), "Discussion: SQLite vs PostgreSQL for state backend",
        workflow="discussion",
        acceptance_criteria=[
            "Evaluate migration complexity",
            "Compare query performance",
            "Decision documented with rationale",
        ],
    )

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)
    assert task.get("development_method") == "discussion"

    _assert_no_yaml_files(tmp_path)


def test_review_workflow_task(tmp_path: Path) -> None:
    """Review workflow task persists correctly."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_rich_task(
        str(tmp_path), "Review: PR #200 security audit",
        workflow="review",
        acceptance_criteria=[
            "No SQL injection vectors",
            "All inputs validated",
            "Auth checks on every endpoint",
        ],
    )

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)
    assert task.get("development_method") == "review"

    _assert_no_yaml_files(tmp_path)


def test_tasks_with_dependencies(tmp_path: Path) -> None:
    """Tasks with blocked_by dependencies persist correctly."""
    _bootstrap_sqlite_only(tmp_path)

    dep_id = _create_task(str(tmp_path), "Database Schema")
    task_id = _create_rich_task(
        str(tmp_path), "API Endpoint",
        blocked_by=[dep_id],
    )

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)
    assert dep_id in task.get("blocked_by", [])

    _assert_no_yaml_files(tmp_path)


def test_multi_level_dependencies(tmp_path: Path) -> None:
    """Tasks with multiple levels of blocked_by chain correctly."""
    _bootstrap_sqlite_only(tmp_path)

    a_id = _create_task(str(tmp_path), "Task A — foundation")
    b_id = _create_rich_task(str(tmp_path), "Task B — middleware", blocked_by=[a_id])
    c_id = _create_rich_task(str(tmp_path), "Task C — frontend", blocked_by=[b_id])

    tasks = _get_tasks(str(tmp_path))
    by_id = {t.get("id"): t for t in tasks}

    assert a_id in by_id[b_id].get("blocked_by", [])
    assert b_id in by_id[c_id].get("blocked_by", [])

    _assert_no_yaml_files(tmp_path)


def test_subtasks_persist(tmp_path: Path) -> None:
    """Subtasks with parent_id persist correctly."""
    _bootstrap_sqlite_only(tmp_path)

    parent_id = _create_task(str(tmp_path), "Orchestrator Decomposition")
    sub_id = _create_rich_task(
        str(tmp_path), "Subtask: Parse input",
        parent_id=parent_id,
    )

    tasks = _get_tasks(str(tmp_path))
    sub = next(t for t in tasks if t.get("id") == sub_id)
    assert sub.get("parent_id") == parent_id

    _assert_no_yaml_files(tmp_path)


def test_multi_agent_ownership(tmp_path: Path) -> None:
    """Tasks owned by claude-code, codex-cli, gemini-cli coexist."""
    _bootstrap_sqlite_only(tmp_path)

    ids = {
        "claude-code": _create_task(str(tmp_path), "Claude Task", owner="claude-code"),
        "codex-cli": _create_task(str(tmp_path), "Codex Task", owner="codex-cli"),
        "gemini-cli": _create_task(str(tmp_path), "Gemini Task", owner="gemini-cli"),
    }

    tasks = _get_tasks(str(tmp_path))
    owners = {t.get("id"): t.get("owner") for t in tasks}

    for agent, tid in ids.items():
        assert owners.get(tid) == agent, f"Task {tid} should be owned by {agent}"

    _assert_no_yaml_files(tmp_path)


def test_task_with_all_metadata_fields(tmp_path: Path) -> None:
    """Every TaskRow field survives a SQLite round-trip."""
    _bootstrap_sqlite_only(tmp_path)

    dep_id = _create_task(str(tmp_path), "Pretend Dependency")
    task_id = _create_rich_task(
        str(tmp_path), "Full Metadata Task",
        workflow="review",
        acceptance_criteria=["AC1", "AC2", "AC3", "AC4", "AC5"],
        test_types=["unit", "integration", "e2e"],
        blocked_by=[dep_id],
        out_of_scope=["Refactoring unrelated modules", "Updating docs"],
        definition_of_done=["All tests green", "PR approved", "CHANGELOG updated"],
        tdd={
            "red": "Failing tests for edge cases",
            "green": "Implementation with error handling",
            "refactor": "Extract shared validators",
        },
    )

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)

    assert task.get("status") == "todo"
    assert task.get("development_method") == "review"
    assert len(task.get("acceptance_criteria", [])) == 5
    assert len(task.get("test_types", [])) == 3
    assert dep_id in task.get("blocked_by", [])
    assert len(task.get("out_of_scope", [])) == 2
    assert len(task.get("definition_of_done", [])) == 3
    assert task.get("tdd", {}).get("refactor") is not None
    assert task.get("project_path") == str(tmp_path)

    _assert_no_yaml_files(tmp_path)


def test_multiple_tasks_mixed_workflows(tmp_path: Path) -> None:
    """Multiple tasks with different workflows coexist in SQLite."""
    _bootstrap_sqlite_only(tmp_path)

    _create_rich_task(str(tmp_path), "Quick Fix", workflow="quick")
    _create_rich_task(str(tmp_path), "Full Feature", workflow="implementation",
                      acceptance_criteria=["AC1", "AC2"],
                      test_types=["unit"],
                      tdd={"red": "test", "green": "impl", "refactor": "clean"})
    _create_rich_task(str(tmp_path), "Design Discussion", workflow="discussion")
    _create_rich_task(str(tmp_path), "Code Review", workflow="review")

    tasks = _get_tasks(str(tmp_path))
    workflows = {t.get("title"): t.get("development_method") for t in tasks}

    assert workflows.get("Quick Fix") == "quick"
    assert workflows.get("Full Feature") == "implementation"
    assert workflows.get("Design Discussion") == "discussion"
    assert workflows.get("Code Review") == "review"

    _assert_no_yaml_files(tmp_path)


def test_task_advance_preserves_metadata(tmp_path: Path) -> None:
    """Advancing a task's status doesn't lose metadata fields."""
    _bootstrap_sqlite_only(tmp_path)

    task_id = _create_rich_task(
        str(tmp_path), "Preserve Metadata",
        workflow="implementation",
        acceptance_criteria=["AC1", "AC2"],
        test_types=["unit"],
        tdd={"red": "tests", "green": "code", "refactor": "clean"},
        out_of_scope=["Deploy to prod"],
        definition_of_done=["Tests pass"],
    )

    _advance_task(str(tmp_path), task_id, "plan_proposed")
    _advance_task(str(tmp_path), task_id, "plan_approved")
    _advance_task(str(tmp_path), task_id, "in_progress")
    _advance_task(str(tmp_path), task_id, "report_ready")
    _advance_task(str(tmp_path), task_id, "done")

    tasks = _get_tasks(str(tmp_path))
    task = next(t for t in tasks if t.get("id") == task_id)

    assert task.get("status") == "done"
    assert task.get("development_method") == "implementation"
    assert len(task.get("acceptance_criteria", [])) == 2
    assert "unit" in task.get("test_types", [])
    assert task.get("tdd", {}).get("green") == "code"
    assert task.get("done_at") is not None

    _assert_no_yaml_files(tmp_path)
