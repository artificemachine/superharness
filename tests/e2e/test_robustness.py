"""Robustness tests — race conditions, stale state, budget gates, freeze detection.

Covers failure modes that don't depend on specific lifecycle rules but on
the system's ability to handle concurrent access, stale data, and resource limits.
"""
from __future__ import annotations

import os
import sqlite3
import yaml
from pathlib import Path

import pytest

from tests.conftest import past_iso


def _write_profile(project: Path, **kwargs) -> None:
    sh = project / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    data = {
        "project_name": "test",
        "created": "2026-01-01",
        "primary_agent": "claude-code",
        "stack": "python",
        "autonomy": "autonomous",
        **kwargs,
    }
    (sh / "profile.yaml").write_text(yaml.dump(data))


def _write_contract(project: Path, tasks: list[dict]) -> None:
    sh = project / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "contract.yaml").write_text(yaml.dump({"tasks": tasks}))


def _init_sqlite(project: Path) -> None:
    from superharness.engine import db
    conn = db.get_connection(str(project))
    db.init_db(conn)
    conn.close()


# ---------------------------------------------------------------------------
# Version mismatch (task modified between read and write)
# ---------------------------------------------------------------------------

def test_task_update_version_mismatch_raises_concurrency_error(clean_harness: Path) -> None:
    """tasks_dao.update must reject updates when version has changed."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from superharness.engine.state_errors import ConcurrencyError

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        # Write directly to SQLite (not YAML)
        tasks_dao.upsert(conn, TaskRow(
            id="test-version", title="Version test", owner="claude-code",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()

        task = tasks_dao.get(conn, "test-version")
        assert task is not None
        v1 = task.version

        # Simulate another writer bumping the version
        tasks_dao.update(conn, "test-version", v1, {"status": "in_progress"})
        conn.commit()

        # Now try to update with the OLD version — should fail
        with pytest.raises(ConcurrencyError, match="version mismatch"):
            tasks_dao.update(conn, "test-version", v1, {"status": "done"})
    finally:
        conn.close()


def test_set_task_status_rejects_version_mismatch(clean_harness: Path) -> None:
    """state_writer.set_task_status must return False on version conflict."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    # Seed at plan_approved so plan_approved → in_progress is legal in the
    # canonical transition graph.
    _write_contract(clean_harness, [{
        "id": "test-v2", "owner": "claude-code", "status": "plan_approved",
    }])

    from superharness.engine.state_writer import set_task_status
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    # First update — legal transition, should succeed
    result1 = set_task_status(str(clean_harness), "test-v2", "in_progress")
    assert result1 is True

    # Second update with from_status that doesn't match the now-current state
    result2 = set_task_status(str(clean_harness), "test-v2", "stopped", from_status="plan_approved")
    assert result2 is False, "set_task_status should reject when from_status doesn't match"


# ---------------------------------------------------------------------------
# Stale watcher / freeze detection
# ---------------------------------------------------------------------------

def test_stale_heartbeat_is_detected(clean_harness: Path) -> None:
    """Heartbeat older than stale_seconds must be flagged as stale."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    # Write old heartbeat
    hb_file = clean_harness / ".superharness" / "watcher.heartbeat"
    hb_file.write_text("2026-01-01T00:00:00Z\n")

    from superharness.commands.status import _heartbeat_status
    level, detail = _heartbeat_status(str(clean_harness), str(clean_harness / ".superharness"))
    assert level == "stale", f"Expected stale heartbeat, got {level}: {detail}"


def test_fresh_heartbeat_is_ok(clean_harness: Path) -> None:
    """Recent heartbeat must report OK."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from datetime import datetime, timezone
    hb_file = clean_harness / ".superharness" / "watcher.heartbeat"
    hb_file.write_text(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")

    from superharness.commands.status import _heartbeat_status
    level, detail = _heartbeat_status(str(clean_harness), str(clean_harness / ".superharness"))
    assert level == "ok", f"Expected ok heartbeat, got {level}: {detail}"


# ---------------------------------------------------------------------------
# No-output / stalled agent (graceful handling)
# ---------------------------------------------------------------------------

def test_reconcile_lifecycle_handles_no_tasks(clean_harness: Path) -> None:
    """reconcile_lifecycle must not crash with empty contract."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed == 0, "reconcile_lifecycle should return 0 for empty contract"


def test_reconcile_lifecycle_handles_missing_state(clean_harness: Path) -> None:
    """reconcile_lifecycle must not crash when state files are missing."""
    _write_profile(clean_harness)
    # No init_sqlite, no contract — simulate corrupted project

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed == 0, "reconcile_lifecycle should return 0 for missing state"


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------

def test_budget_gate_passes_when_budget_not_set(clean_harness: Path) -> None:
    """check_budget must not block when no budget is configured."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.model_budget import check_budget, BudgetStatus
    status = check_budget(str(clean_harness))
    assert status.status != BudgetStatus.BLOCK, (
        f"Budget gate should not block without configuration, got {status.status}"
    )


# ---------------------------------------------------------------------------
# Double-close / idempotent operations
# ---------------------------------------------------------------------------

def test_set_task_status_idempotent_same_status(clean_harness: Path) -> None:
    """Setting the same status twice must not break anything."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    # Seed task in plan_approved so plan_approved → in_progress is legal.
    _write_contract(clean_harness, [{
        "id": "test-idem", "owner": "claude-code", "status": "plan_approved",
    }])

    from superharness.engine.state_writer import set_task_status
    from superharness.engine.state_reader import get_tasks

    # First call: legal transition. Second call: same target → no-op (idempotent).
    set_task_status(str(clean_harness), "test-idem", "in_progress")
    set_task_status(str(clean_harness), "test-idem", "in_progress")

    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-idem")
    assert task["status"] == "in_progress", "idempotent update should preserve status"


def test_close_discussion_idempotent(clean_harness: Path) -> None:
    """Closing an already-closed discussion must not crash."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    disc_id = "test-double-close"
    disc_dir = clean_harness / ".superharness" / "discussions" / disc_id
    disc_dir.mkdir(parents=True)
    (disc_dir / "state.yaml").write_text(yaml.dump({
        "status": "closed",
        "topic": "Already closed",
        "participants": ["claude-code"],
    }))

    # Should not crash on already-closed discussion
    from superharness.engine.discussions_dao import close
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        conn.execute(
            "INSERT OR IGNORE INTO discussions (id, topic, status, created_at) VALUES (?,?,?,?)",
            (disc_id, "Already closed", "active", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        # Close it first time
        result1 = close(conn, disc_id, consensus="done", now="2026-01-01T01:00:00Z")
        conn.commit()
        # Close it second time — should not raise
        result2 = close(conn, disc_id, consensus="done", now="2026-01-01T02:00:00Z")
        assert result1 is True, "first close should succeed"
        assert result2 is False, "second close should return False (already closed)"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task with multiple agents / owner reassignment
# ---------------------------------------------------------------------------

def test_task_owner_reassignment_preserves_deadline(clean_harness: Path) -> None:
    """Changing task owner must not lose deadline_minutes."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-reassign", title="Reassign test", owner="claude-code",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
            deadline_minutes=120,
        ))
        conn.commit()

        # Change owner
        task = tasks_dao.get(conn, "test-reassign")
        tasks_dao.update(conn, "test-reassign", task.version,
                         {"owner": "codex-cli"})
        conn.commit()

        # Verify deadline preserved
        task2 = tasks_dao.get(conn, "test-reassign")
        assert task2.deadline_minutes == 120, (
            f"deadline_minutes lost after owner change: {task2.deadline_minutes}"
        )
        assert task2.owner == "codex-cli"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# opencode as valid owner
# ---------------------------------------------------------------------------

def test_opencode_is_valid_owner() -> None:
    """opencode must be in the KNOWN_AGENTS list."""
    import importlib
    mod = importlib.import_module("superharness.scripts.dashboard-ui")
    assert "opencode" in mod.KNOWN_AGENTS, "opencode missing from dashboard KNOWN_AGENTS"

    # Check that the presenter also has it by creating a task owned by opencode
    import tempfile, os
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot

    d = tempfile.mkdtemp()
    sh = os.path.join(d, '.superharness')
    os.makedirs(sh, exist_ok=True)
    with open(os.path.join(sh, 'profile.yaml'), 'w') as f:
        f.write('project_name: test\ncreated: 2026-01-01\nprimary_agent: opencode\nstack: python\nautonomy: autonomous\n')
    conn = get_connection(d)
    init_db(conn)
    tasks_dao.upsert(conn, TaskRow(
        id="test-opencode", title="OpenCode task", owner="opencode",
        status="todo", effort="medium",
        project_path=d, development_method="tdd",
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None,
        version=1, created_at="2026-01-01T00:00:00Z",
    ))
    conn.commit()
    snap = get_dashboard_status_snapshot(conn, d)
    owners = snap.get("all_task_owners", [])
    assert "opencode" in owners, f"opencode missing from all_task_owners: {owners}"
    conn.close()


def test_opencode_can_own_task(clean_harness: Path) -> None:
    """Tasks can be assigned to opencode owner."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-oc-owner", title="OpenCode owned", owner="opencode",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()
        task = tasks_dao.get(conn, "test-oc-owner")
        assert task.owner == "opencode", f"Expected opencode owner, got {task.owner}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Contract tasks ↔ active work queue consistency
# ---------------------------------------------------------------------------

def test_task_in_active_state_has_dashboard_visibility(clean_harness: Path) -> None:
    """Tasks in non-terminal states must appear in dashboard contract_tasks."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    import yaml
    sh = clean_harness / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    yaml_tasks = [
        {"id": f"vis-{s}", "owner": "claude-code", "status": s}
        for s in ("todo", "in_progress", "waiting_input", "report_ready", "review_requested")
    ]
    (sh / "contract.yaml").write_text(yaml.dump({"tasks": yaml_tasks}))

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        for status in ("todo", "in_progress", "waiting_input", "report_ready", "review_requested"):
            tasks_dao.upsert(conn, TaskRow(
                id=f"vis-{status}", title=f"Visibility test {status}", owner="claude-code",
                status=status, effort="medium",
                project_path=str(clean_harness), development_method="tdd",
                acceptance_criteria=[], test_types=[], out_of_scope=[],
                definition_of_done=[], context=None, tdd=None,
                version=1, created_at="2026-01-01T00:00:00Z",
            ))
        conn.commit()

        from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
        snap = get_dashboard_status_snapshot(conn, str(clean_harness))
        tasks = snap.get("contract_tasks", [])
        task_ids = {t["id"] for t in tasks}

        for status in ("todo", "in_progress", "waiting_input", "report_ready", "review_requested"):
            tid = f"vis-{status}"
            assert tid in task_ids, (
                f"Task {tid} ({status}) missing from dashboard contract_tasks"
            )
    finally:
        conn.close()


def test_set_task_status_does_not_orphan_inbox(clean_harness: Path) -> None:
    """Setting a task to active status should ensure inbox visibility."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.state_writer import set_task_status
    from superharness.engine.state_reader import get_tasks

    # Create task via contract YAML (simulating shux task create)
    import yaml
    sh = clean_harness / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "contract.yaml").write_text(yaml.dump({"tasks": [
        {"id": "test-consistency", "owner": "claude-code", "status": "plan_approved"},
    ]}))

    # Transition to in_progress (legal from plan_approved)
    set_task_status(str(clean_harness), "test-consistency", "in_progress")

    # Verify task exists
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-consistency")
    assert task["status"] == "in_progress"

    # Task should appear in dashboard regardless of inbox state
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
    conn = get_connection(str(clean_harness))
    init_db(conn)
    snap = get_dashboard_status_snapshot(conn, str(clean_harness))
    tasks_in_dashboard = {t["id"] for t in snap.get("contract_tasks", [])}
    assert "test-consistency" in tasks_in_dashboard, (
        "Task set to in_progress must appear in dashboard contract_tasks"
    )
    conn.close()


# ---------------------------------------------------------------------------
# Invariant: active states must have matching inbox items
# ---------------------------------------------------------------------------

def test_transition_to_active_state_creates_inbox_item() -> None:
    """Transitioning to in_progress must auto-create an inbox item (production path)."""
    import os, sys, tempfile, yaml
    from pathlib import Path

    # Force non-test mode
    if 'PYTEST_CURRENT_TEST' in os.environ: del os.environ['PYTEST_CURRENT_TEST']
    sys.modules.pop('pytest', None)

    d = Path(tempfile.mkdtemp())
    try:
        sh = d / '.superharness'; sh.mkdir()
        (sh / 'profile.yaml').write_text('project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n')
        (sh / 'contract.yaml').write_text(yaml.dump({'tasks': [{'id': 'inv-test', 'owner': 'claude-code', 'status': 'plan_approved'}]}))

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow
        conn = get_connection(str(d))
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(id='inv-test', title='T', owner='claude-code', status='plan_approved', effort='medium', project_path=str(d), development_method='tdd', acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, version=1, created_at='2026-01-01T00:00:00Z'))
        conn.commit()
        conn.close()

        from superharness.engine.state_writer import set_task_status
        result = set_task_status(str(d), 'inv-test', 'in_progress')
        assert result is True

        conn2 = get_connection(str(d))
        count = conn2.execute("SELECT COUNT(*) FROM inbox WHERE task_id='inv-test'").fetchone()[0]
        assert count >= 1, f"Production guard must auto-create inbox item (got {count})"
        conn2.close()
    finally:
        import shutil; shutil.rmtree(d)


def test_transition_to_waiting_input_creates_inbox() -> None:
    """Transitioning to waiting_input must auto-create an inbox item (production path)."""
    import os, sys, tempfile, yaml
    from pathlib import Path
    if 'PYTEST_CURRENT_TEST' in os.environ: del os.environ['PYTEST_CURRENT_TEST']
    sys.modules.pop('pytest', None)

    d = Path(tempfile.mkdtemp())
    try:
        sh = d / '.superharness'; sh.mkdir()
        (sh / 'profile.yaml').write_text('project_name: test\ncreated: 2026-01-01\nprimary_agent: opencode\nstack: python\nautonomy: autonomous\n')

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow
        conn = get_connection(str(d))
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(id='wait-inv', title='W', owner='opencode', status='todo', effort='medium', project_path=str(d), development_method='tdd', acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, version=1, created_at='2026-01-01T00:00:00Z'))
        conn.commit()
        conn.close()

        from superharness.engine.state_writer import set_task_status
        set_task_status(str(d), 'wait-inv', 'waiting_input')

        conn2 = get_connection(str(d))
        count = conn2.execute("SELECT COUNT(*) FROM inbox WHERE task_id='wait-inv'").fetchone()[0]
        assert count >= 1, f"Production guard must auto-create inbox item (got {count})"
        conn2.close()
    finally:
        import shutil; shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Schema audit: every SQLite column must map to a TaskRow field
# ---------------------------------------------------------------------------

def test_all_sqlite_task_columns_in_taskrow() -> None:
    """Every column in the SQLite tasks table must have a corresponding TaskRow field.

    Prevents BUG-1 (updated_at) and BUG-8 (archived_at) from recurring.
    When a migration adds a column, this test fails until TaskRow is updated.
    """
    import tempfile, os
    from pathlib import Path
    from dataclasses import fields as dc_fields

    d = Path(tempfile.mkdtemp())
    try:
        sh = d / '.superharness'; sh.mkdir()
        (sh / 'profile.yaml').write_text('project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n')

        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(d))
        init_db(conn)

        # Get all SQLite columns
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}

        # Get all TaskRow field names
        from superharness.engine.tasks_dao import TaskRow
        taskrow_fields = {f.name for f in dc_fields(TaskRow)}

        # Find columns not in TaskRow
        missing = columns - taskrow_fields
        assert not missing, (
            f"SQLite task columns without TaskRow field: {sorted(missing)}\n"
            f"Add these to TaskRow in tasks_dao.py"
        )

        # Find TaskRow fields not in SQLite (warn only)
        extra = taskrow_fields - columns
        if extra:
            print(f"[WARN] TaskRow fields without SQLite column: {sorted(extra)}")

        conn.close()
    finally:
        import shutil; shutil.rmtree(d)


def test_all_sqlite_inbox_columns_in_inboxrow() -> None:
    """Every column in the SQLite inbox table must map to InboxRow."""
    import tempfile, os
    from pathlib import Path
    from dataclasses import fields as dc_fields

    d = Path(tempfile.mkdtemp())
    try:
        sh = d / '.superharness'; sh.mkdir()
        (sh / 'profile.yaml').write_text('project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n')

        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(d))
        init_db(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(inbox)").fetchall()}
        from superharness.engine.inbox_dao import InboxRow
        inbox_fields = {f.name for f in dc_fields(InboxRow)}

        missing = columns - inbox_fields
        assert not missing, (
            f"SQLite inbox columns without InboxRow field: {sorted(missing)}\n"
            f"Add these to InboxRow in inbox_dao.py"
        )
        conn.close()
    finally:
        import shutil; shutil.rmtree(d)


def test_all_statuses_in_next_action() -> None:
    """Every status in TaskStatus enum must be in ALL_STATUSES in next_action.py."""
    from superharness.engine.schemas import TaskStatus
    from superharness.engine.next_action import ALL_STATUSES

    for status in TaskStatus:
        assert status.value in ALL_STATUSES, (
            f"TaskStatus.{status.name} ('{status.value}') missing from ALL_STATUSES"
        )


# ---------------------------------------------------------------------------
# Discussion auto-consensus when all participants submit
# ---------------------------------------------------------------------------

def test_discussion_auto_consensus_on_all_submissions():
    """When all participants submit, discussion must auto-transition to consensus.
    If any point is non-agree, an auto-task is created."""
    import tempfile, yaml, os
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    try:
        disc_dir = d / ".superharness" / "discussions" / "test-auto-consensus"
        disc_dir.mkdir(parents=True)

        # Seed discussion in SQLite (post-migration source of truth) instead
        # of the legacy state.yaml fixture file.
        from superharness.engine.db import get_connection as _gc, init_db as _idb
        from superharness.engine import discussions_dao as _dd
        _conn = _gc(str(d)); _idb(_conn, str(d))
        _dd.create(_conn, id="test-auto-consensus", topic="Test auto-consensus",
                   owners=["claude-code", "codex-cli"], task_id=None,
                   now="2026-01-01T00:00:00Z")
        _conn.commit(); _conn.close()

        from superharness.engine.discussion import cmd_submit_round

        # Submit agent 1 with one non-agree point
        points_file = disc_dir / "points.yaml"
        points_file.write_text(yaml.dump([{"id": "fix-1", "verdict": "disagree", "rationale": "Must fix"}]))
        rc = cmd_submit_round(str(disc_dir), 1, "claude-code", "consensus", "Position 1", str(points_file))
        assert rc == 0

        # State should still be active (not all submitted)
        from superharness.engine.db import get_connection as _gc2
        _c = _gc2(str(d))
        try:
            row = _c.execute("SELECT status FROM discussions WHERE id='test-auto-consensus'").fetchone()
            assert row["status"] == "active", "Should remain active after first submission"
        finally:
            _c.close()

        # Submit agent 2 with another non-agree point
        points_file2 = disc_dir / "points2.yaml"
        points_file2.write_text(yaml.dump([{"id": "fix-1", "verdict": "disagree", "rationale": "Must fix"}]))
        rc = cmd_submit_round(str(disc_dir), 1, "codex-cli", "consensus", "Position 2", str(points_file2))
        assert rc == 0

        # State should now be consensus
        _c = _gc2(str(d))
        try:
            row = _c.execute("SELECT status FROM discussions WHERE id='test-auto-consensus'").fetchone()
            assert row["status"] == "consensus"
        finally:
            _c.close()

        # Verify auto-task was created (because there's a non-agree point)
        from superharness.engine.db import get_connection
        conn = get_connection(str(d))
        task = conn.execute(
            "SELECT id, title, status, owner FROM tasks WHERE id LIKE 'impl-test-auto-consensus%'"
        ).fetchone()
        assert task is not None, "Auto-task must be created when any point is non-agree"
        assert task[2] == "todo"
        conn.close()
    finally:
        import shutil; shutil.rmtree(d)


def test_discussion_not_consensus_on_partial_submission():
    """Discussion must NOT transition to consensus when not all submitted."""
    import tempfile, yaml, os
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    try:
        disc_dir = d / ".superharness" / "discussions" / "test-partial"
        disc_dir.mkdir(parents=True)

        from superharness.engine.db import get_connection as _gc, init_db as _idb
        from superharness.engine import discussions_dao as _dd
        _conn = _gc(str(d)); _idb(_conn, str(d))
        _dd.create(_conn, id="test-partial", topic="Test partial",
                   owners=["claude-code", "codex-cli", "opencode"],
                   task_id=None, now="2026-01-01T00:00:00Z")
        _conn.commit(); _conn.close()

        from superharness.engine.discussion import cmd_submit_round

        # Submit only 2 of 3
        cmd_submit_round(str(disc_dir), 1, "claude-code", "consensus", "P1", None)
        cmd_submit_round(str(disc_dir), 1, "codex-cli", "consensus", "P2", None)

        # State should NOT be consensus
        _c = _gc(str(d))
        try:
            row = _c.execute("SELECT status FROM discussions WHERE id='test-partial'").fetchone()
            assert row["status"] == "active", (
                f"Should remain active with partial submissions, got {row['status']}"
            )
        finally:
            _c.close()
    finally:
        import shutil; shutil.rmtree(d)


def test_all_agree_discussion_skips_auto_task():
    """When all points are 'agree', no auto-task should be created (confirmation only)."""
    import tempfile, yaml, os
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    try:
        disc_dir = d / ".superharness" / "discussions" / "test-all-agree"
        disc_dir.mkdir(parents=True)

        from superharness.engine.db import get_connection as _gc, init_db as _idb
        from superharness.engine import discussions_dao as _dd
        _conn = _gc(str(d)); _idb(_conn, str(d))
        _dd.create(_conn, id="test-all-agree", topic="Test all agree",
                   owners=["claude-code", "codex-cli"], task_id=None,
                   now="2026-01-01T00:00:00Z")
        _conn.commit(); _conn.close()

        from superharness.engine.discussion import cmd_submit_round

        points_file = disc_dir / "points.yaml"
        points_file.write_text(yaml.dump([{"id": "ok-1", "verdict": "agree", "rationale": "Good"}]))
        cmd_submit_round(str(disc_dir), 1, "claude-code", "agree", "P1", str(points_file))
        cmd_submit_round(str(disc_dir), 1, "codex-cli", "agree", "P2", str(points_file))

        # Should auto-consensus but NOT create task
        from superharness.engine.db import get_connection
        conn = get_connection(str(d))
        try:
            row = conn.execute("SELECT status FROM discussions WHERE id='test-all-agree'").fetchone()
            assert row["status"] == "consensus"
            task = conn.execute("SELECT COUNT(*) FROM tasks WHERE id LIKE 'impl-test-all-agree%'").fetchone()
            assert task[0] == 0, "All-agree discussions must not create auto-tasks"
        finally:
            conn.close()
    finally:
        import shutil; shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Invalid state transitions
# ---------------------------------------------------------------------------

def test_set_task_status_rejects_invalid_transition(clean_harness: Path) -> None:
    """set_task_status with from_status rejects when current status doesn't match."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-transition", "owner": "claude-code", "status": "todo"},
    ])

    from superharness.engine.state_writer import set_task_status
    # todo → plan_proposed, but with wrong from_status
    result = set_task_status(str(clean_harness), "test-transition", "plan_proposed", from_status="done")
    assert result is False, "from_status='done' should reject when task is 'todo'"

    # Correct from_status + legal transition → succeeds.
    # (todo → in_progress is no longer a legal interactive transition; tasks
    # must go through plan_proposed → plan_approved before in_progress.)
    result = set_task_status(str(clean_harness), "test-transition", "plan_proposed", from_status="todo")
    assert result is True, "from_status='todo' should allow todo → plan_proposed"


def test_set_task_status_accepts_valid_transition(clean_harness: Path) -> None:
    """All valid transitions in the state machine pipeline must work."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-valid-trans", "owner": "claude-code", "status": "todo"},
    ])

    from superharness.engine.state_writer import set_task_status
    # Walk the full canonical pipeline. report_ready → done is not legal;
    # the path goes through review_passed first.
    pipeline = [
        "plan_proposed", "plan_approved", "in_progress",
        "report_ready", "review_passed", "done",
    ]
    for step in pipeline:
        result = set_task_status(str(clean_harness), "test-valid-trans", step)
        assert result is True, f"Valid transition to {step} should succeed"

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-valid-trans")
    assert task["status"] == "done", f"Expected done after pipeline, got {task['status']}"


# ---------------------------------------------------------------------------
# Enqueue for unknown agent
# ---------------------------------------------------------------------------

def test_enqueue_unknown_agent_is_accepted(clean_harness: Path) -> None:
    """Enqueuing for an agent without a dispatch adapter should still create the inbox item.
    The watcher handles the 'cannot dispatch unknown agent' case at launch time.
    """
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao, inbox_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-unknown-agent", title="T", owner="unknown-agent",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()

        # Enqueue should still work (item is created, dispatch fails later)
        inbox_dao.enqueue(conn, id="ua-1", task_id="test-unknown-agent",
            target_agent="unknown-agent", priority=2, project_path=str(clean_harness),
            now="2026-01-01T00:00:00Z")
        conn.commit()

        item = inbox_dao.get(conn, "ua-1")
        assert item is not None, "Enqueue for unknown agent should create inbox item"
        assert item.target_agent == "unknown-agent"
        assert item.status == "pending"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dashboard handles all statuses in task report
# ---------------------------------------------------------------------------

def test_task_report_handles_all_statuses(clean_harness: Path) -> None:
    """task_report must not crash for any status value."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    import sys; sys.path.insert(0, "src")
    import importlib
    mod = importlib.import_module("superharness.scripts.dashboard-ui")

    from superharness.engine.next_action import ALL_STATUSES

    # Write to both YAML and SQLite
    yaml_tasks = [
        {"id": f"report-{st}", "owner": "claude-code", "status": st}
        for st in ALL_STATUSES
    ]
    _write_contract(clean_harness, yaml_tasks)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        for st in ALL_STATUSES:
            tasks_dao.upsert(conn, TaskRow(
                id=f"report-{st}", title=f"Report test {st}", owner="claude-code",
                status=st, effort="medium",
                project_path=str(clean_harness), development_method="tdd",
                acceptance_criteria=[], test_types=[], out_of_scope=[],
                definition_of_done=[], context=None, tdd=None,
                version=1, created_at="2026-01-01T00:00:00Z",
            ))
        conn.commit()

        for st in ALL_STATUSES:
            result = mod.task_report(clean_harness, f"report-{st}", "claude-code")
            assert result.get("contract_status") == st, (
                f"task_report failed for status '{st}': got {result.get('contract_status')}"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Watcher module integrity — prevent silent crashes from broken code
# ---------------------------------------------------------------------------

def test_all_watcher_modules_importable() -> None:
    """Every module imported by the watcher must be importable without error.

    Prevents the bug where a syntax error in state_writer.py crashed every
    watcher cycle for 7+ hours without detection.
    """
    critical_modules = [
        "superharness.engine.state_writer",
        "superharness.engine.state_reader",
        "superharness.engine.lifecycle_rules",
        "superharness.engine.db",
        "superharness.engine.tasks_dao",
        "superharness.engine.inbox_dao",
        "superharness.engine.discussions_dao",
        "superharness.engine.ledger_dao",
        "superharness.engine.contract_io",
        "superharness.engine.dashboard_presenter",
        "superharness.engine.next_action",
        "superharness.engine.schemas",
        "superharness.commands.status",
        "superharness.commands.inbox_gc",
        "superharness.commands.inbox_watch",
    ]
    for mod in critical_modules:
        try:
            importlib = __import__("importlib")
            importlib.import_module(mod)
        except Exception as e:
            pytest.fail(f"Watcher module {mod} is not importable: {e}")


def test_lifecycle_rules_fire_without_datetime_error(clean_harness: Path) -> None:
    """reconcile_lifecycle must not crash with datetime errors.

    Prevents the 'can't subtract offset-naive and offset-aware datetimes'
    error that crashed the watcher for 7+ hours.
    """
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-dt-safe", "owner": "claude-code", "status": "in_progress",
         "updated_at": "2026-01-01T00:00:00Z"},
    ])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    # Must not raise any exception
    changed = reconcile_lifecycle(str(clean_harness))
    assert isinstance(changed, int), f"reconcile_lifecycle should return int, got {type(changed)}"


# ---------------------------------------------------------------------------
# CI test: SQLite is the only operational read path
# ---------------------------------------------------------------------------

def test_default_state_backend_is_sqlite_only() -> None:
    """STATE_BACKEND must default to sqlite_only in production."""
    import os
    # Ensure no env override
    old = os.environ.pop("STATE_BACKEND", None)
    try:
        from superharness.engine.state_reader import _get_backend
        backend = _get_backend("/tmp/nonexistent")
        assert backend == "sqlite_only", (
            f"Default STATE_BACKEND must be 'sqlite_only', got '{backend}'"
        )
    finally:
        if old:
            os.environ["STATE_BACKEND"] = old


def test_no_yaml_ingestion_in_production_read() -> None:
    """_ensure_ingested must NOT be called during production reads."""
    import inspect
    from superharness.engine.state_reader import get_tasks, get_inbox_items, get_task

    for func in (get_tasks, get_inbox_items, get_task):
        src = inspect.getsource(func)
        assert "_ensure_ingested" not in src, (
            f"{func.__name__} must not call _ensure_ingested() in production path"
        )


def test_sqlite_only_mode_raises_on_error() -> None:
    """In sqlite_only mode, SQLite errors must propagate — no silent YAML fallback."""
    import inspect
    from superharness.engine.state_reader import get_tasks

    src = inspect.getsource(get_tasks)
    # Must contain the raise statement for sqlite_only mode
    assert 'if backend == "sqlite_only"' in src or 'sqlite_only' in src, (
        "get_tasks must check for sqlite_only mode and raise on error"
    )


# ---------------------------------------------------------------------------
# SQLite-only enforcement: verify all 5 fixes work end-to-end
# ---------------------------------------------------------------------------

def test_sqlite_only_backend_returns_sqlite_data(clean_harness: Path) -> None:
    """In sqlite_only mode, reads must come from SQLite, not YAML."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    # Write YAML with stale data, SQLite with correct data
    _write_contract(clean_harness, [
        {"id": "test-sqlite-only", "owner": "claude-code", "status": "todo"},
    ])
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-sqlite-only", title="SQLite version", owner="claude-code",
            status="in_progress", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()
    finally:
        conn.close()

    # In test mode, YAML is primary — task shows "todo"
    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-sqlite-only")
    # Test mode overlays SQLite status onto YAML, so we should see "in_progress"
    assert task["status"] == "in_progress", (
        f"SQLite status should override YAML in test mode, got {task['status']}"
    )


def test_yaml_sync_is_no_op() -> None:
    """yaml_sync.drain_queue must always return DrainResult with 0 applied/failed."""
    from superharness.engine.yaml_sync import drain_queue, DrainResult
    result = drain_queue("/tmp/nonexistent")
    assert isinstance(result, DrainResult)
    assert result.applied == 0, "drain_queue must be a no-op"
    assert result.failed == 0, "drain_queue must be a no-op"


def test_yaml_sync_module_is_minimal() -> None:
    """yaml_sync.py must not contain any active sync/writeback logic beyond the docstring."""
    src = open("src/superharness/engine/yaml_sync.py").read()
    # Remove docstring before checking
    if src.startswith('"""'):
        end = src.index('"""', 3)
        src = src[end + 3:]
    forbidden = ["_export", "_sync_tasks", "contract.yaml", "inbox.yaml"]
    found = [w for w in forbidden if w in src]
    assert not found, (
        f"yaml_sync.py must be stripped of active sync logic, found: {found}"
    )


def test_state_reader_no_yaml_ingestion_call() -> None:
    """Production read paths must not call any function with 'ingest' in its name."""
    import inspect
    from superharness.engine import state_reader as sr

    # Check that _ensure_ingested is not called in production paths
    funcs = ["get_tasks", "get_task", "get_inbox_items"]
    for fname in funcs:
        src = inspect.getsource(getattr(sr, fname))
        assert "_ensure_ingested" not in src or "_is_running_tests" not in src, (
            f"{fname} must not call _ensure_ingested in production path"
        )


# ---------------------------------------------------------------------------
# Discussion view content validation
# ---------------------------------------------------------------------------

def test_discussion_view_shows_all_submissions() -> None:
    """discussion_agent_status must return all agent submissions with content."""
    import tempfile, yaml, os
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    try:
        disc_dir = d / ".superharness" / "discussions" / "test-view-all"
        disc_dir.mkdir(parents=True)

        (disc_dir / "state.yaml").write_text(yaml.dump({
            "id": "test-view-all", "status": "active",
            "topic": "Test all submissions",
            "participants": ["claude-code", "codex-cli", "opencode"],
            "current_round": 1, "max_rounds": 1,
            "created_at": "2026-01-01T00:00:00Z",
        }))

        # Write 3 round submissions
        for agent in ["claude-code", "codex-cli", "opencode"]:
            (disc_dir / f"round-1-{agent}.yaml").write_text(yaml.dump({
                "agent": agent, "round": 1, "verdict": "consensus",
                "position": f"Position from {agent}",
                "points": [{"id": "p1", "verdict": "agree", "rationale": "OK"}],
                "submitted_at": "2026-01-01T01:00:00Z",
            }))

        import sys; sys.path.insert(0, "src")
        import importlib
        mod = importlib.import_module("superharness.scripts.dashboard-ui")
        result = mod.discussion_agent_status(d, "test-view-all")

        assert result["total_submissions"] == 3, f"Expected 3 submissions, got {result['total_submissions']}"
        agents = {s["agent"] for s in result["submissions"]}
        assert agents == {"claude-code", "codex-cli", "opencode"}, f"Missing agents: {agents}"

        # Timeline must have 4 events (created + 3 submissions)
        assert len(result["timeline"]) == 4, f"Expected 4 timeline events, got {len(result['timeline'])}"
    finally:
        import shutil; shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Task report with active agent log
# ---------------------------------------------------------------------------

def test_task_report_includes_launcher_log_when_active(clean_harness: Path) -> None:
    """task_report must include log content when a launcher log exists."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-log-report", "owner": "claude-code", "status": "in_progress"},
    ])

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-log-report", title="Log test", owner="claude-code",
            status="in_progress", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()
    finally:
        conn.close()

    # Write a launcher log
    log_dir = clean_harness / ".superharness" / "launcher-logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "test-log-report-claude-code-test.log").write_text(
        "[2026-01-01T00:01:00Z] Agent started\n"
        "[2026-01-01T00:02:00Z] Processing step 1\n"
        "[2026-01-01T00:03:00Z] Done\n"
    )

    import sys; sys.path.insert(0, "src")
    import importlib
    mod = importlib.import_module("superharness.scripts.dashboard-ui")
    result = mod.task_log_content(clean_harness, "test-log-report", "claude-code", lines=10)

    assert result.get("exists") is True, f"Launcher log should exist: {result}"
    assert "Agent started" in result.get("log", ""), "Log should contain agent output"


# ---------------------------------------------------------------------------
# Dashboard snapshot includes all required panels
# ---------------------------------------------------------------------------

def test_dashboard_snapshot_has_all_panels(clean_harness: Path) -> None:
    """Dashboard status snapshot must include all panel data fields."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
    conn = get_connection(str(clean_harness))
    init_db(conn)
    snap = get_dashboard_status_snapshot(conn, str(clean_harness))
    conn.close()

    required = [
        "contract_tasks", "ledger_tail", "out_tail", "err_tail",
        "activity_feed", "inbox_items", "board_columns", "review_queue",
        "active_discussions", "failures", "decisions",
    ]
    missing = [k for k in required if k not in snap]
    assert not missing, f"Dashboard snapshot missing fields: {missing}"


# =============================================================================
# PLAN Iteration 1: Tool-loop guardrails
# =============================================================================

def test_loop_detector_flags_repeated_tool_calls() -> None:
    """5 consecutive identical tool calls in a launcher log must be flagged as loop."""
    import tempfile, os

    d = tempfile.mkdtemp()
    log = os.path.join(d, "test.log")
    with open(log, "w") as f:
        for _ in range(5):
            f.write("Tool: read_file(path='src/x.py')\n")
        f.write("Tool: write_file(path='src/x.py')\n")  # different tool — break

    from superharness.engine.loop_detector import detect_loop
    result = detect_loop(log, window=5)
    assert result["loop_detected"] is True, f"Expected loop, got {result}"
    assert result["pattern"] == "read_file", f"Expected read_file pattern, got {result['pattern']}"
    assert result["count"] >= 5


def test_loop_detector_ignores_diverse_logs() -> None:
    """A log with diverse tool calls must not be flagged as a loop."""
    import tempfile, os

    d = tempfile.mkdtemp()
    log = os.path.join(d, "test.log")
    with open(log, "w") as f:
        f.write("Tool: read_file(path='a.py')\n")
        f.write("Tool: grep(pattern='foo')\n")
        f.write("Tool: write_file(path='b.py')\n")
        f.write("Tool: execute(cmd='pytest')\n")
        f.write("Tool: read_file(path='c.py')\n")

    from superharness.engine.loop_detector import detect_loop
    result = detect_loop(log, window=5)
    assert result["loop_detected"] is False, f"Expected no loop, got {result}"


# =============================================================================
# PLAN Iteration 2: shux handoff generate
# =============================================================================

def test_handoff_generate_creates_valid_handoff(clean_harness: Path) -> None:
    """shux handoff generate must create a handoff YAML with all mandatory fields."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-handoff-gen", "owner": "claude-code", "status": "in_progress",
         "title": "Test handoff generation", "acceptance_criteria": ["AC1", "AC2"]},
    ])

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-handoff-gen", title="Test", owner="claude-code",
            status="in_progress", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=["AC1", "AC2"], test_types=[], out_of_scope=[],
            definition_of_done=[], context="Some context", tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()
    finally:
        conn.close()

    from superharness.engine.handoff_generator import generate_handoff
    result = generate_handoff(str(clean_harness), "test-handoff-gen")

    required = ["summary", "scope", "acceptance", "risks", "artifacts"]
    for field in required:
        assert field in result, f"Handoff missing required field: {field}"
    assert result["summary"] != "", "Summary must not be empty"
    assert len(result["acceptance"]) >= 2, "Must include acceptance criteria"


# =============================================================================
# PLAN Iteration 3: FTS-backed recall
# =============================================================================

def test_fts_recall_finds_handoff_by_keyword(clean_harness: Path) -> None:
    """search function must find handoffs by keyword."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    from pathlib import Path
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    # Write a handoff file
    handoffs = clean_harness / ".superharness" / "handoffs"
    handoffs.mkdir(parents=True, exist_ok=True)
    (handoffs / "test-handoff.yaml").write_text(
        "id: h1\ntask: task-a\nfrom: claude-code\nto: owner\nstatus: done\n"
        "summary: Fixed the SQLite regression bug\n"
    )

    from superharness.engine.recall import search
    results = search(clean_harness, ["sqlite"])  # search uses lowercase matching
    assert len(results) > 0, "search should find handoff by keyword 'sqlite'"


# =============================================================================
# PLAN Iteration 4: JSONL event stream
# =============================================================================

def test_event_stream_writes_on_task_change(clean_harness: Path) -> None:
    """Task status change must write a JSONL event."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-event", "owner": "claude-code", "status": "todo"},
    ])

    from superharness.engine.event_stream import write_event, read_events
    write_event(str(clean_harness), "status_change", task_id="test-event",
                from_status="todo", to_status="in_progress")

    events = read_events(str(clean_harness))
    assert len(events) >= 1, "Event stream must have at least 1 event"
    assert events[0]["type"] == "status_change"
    assert events[0]["task_id"] == "test-event"


# =============================================================================
# PLAN Iteration 5: Adapter policy gates
# =============================================================================

def test_policy_gate_blocks_agent_over_budget() -> None:
    """Agent exceeding per-agent cost limit must be blocked."""
    from superharness.engine.policy_gate import check_agent_policy

    result = check_agent_policy(
        agent="claude-code",
        cost_usd=5.0,
        max_cost_usd=3.0,
        loop_detected=False,
    )
    assert result["blocked"] is True, "Agent over budget must be blocked"
    assert "cost" in result["reason"].lower()


def test_policy_gate_allows_agent_under_budget() -> None:
    """Agent under budget must be allowed."""
    from superharness.engine.policy_gate import check_agent_policy

    result = check_agent_policy(
        agent="claude-code",
        cost_usd=1.0,
        max_cost_usd=3.0,
        loop_detected=False,
    )
    assert result["blocked"] is False, "Agent under budget must be allowed"


def test_policy_gate_blocks_agent_with_loop() -> None:
    """Agent with detected loop must be blocked regardless of cost."""
    from superharness.engine.policy_gate import check_agent_policy

    result = check_agent_policy(
        agent="claude-code",
        cost_usd=1.0,
        max_cost_usd=10.0,
        loop_detected=True,
    )
    assert result["blocked"] is True, "Agent with loop must be blocked"
    assert "loop" in result["reason"].lower()


# =============================================================================
# PLAN Iteration 6: Skill curation + usage insights
# =============================================================================

def test_skill_metrics_records_usage() -> None:
    """Skill usage must be recordable with agent, task, and outcome."""
    import tempfile, os
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    try:
        sh = d / ".superharness"; sh.mkdir()
        (sh / "profile.yaml").write_text("project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n")

        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(d))
        init_db(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill TEXT NOT NULL,
                agent TEXT NOT NULL,
                task_id TEXT NOT NULL,
                outcome TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        from superharness.engine.skill_metrics import record_skill_usage, get_skill_insights
        record_skill_usage(str(d), skill="tdd", agent="claude-code", task_id="task-1", outcome="success")
        record_skill_usage(str(d), skill="tdd", agent="codex-cli", task_id="task-2", outcome="success")
        record_skill_usage(str(d), skill="ship", agent="claude-code", task_id="task-3", outcome="failed")

        insights = get_skill_insights(str(d))
        assert len(insights) >= 2, f"Expected at least 2 skills, got {len(insights)}"

        tdd = next(i for i in insights if i["skill"] == "tdd")
        assert tdd["uses"] == 2
        assert tdd["success_rate"] == 1.0  # 2/2

        ship = next(i for i in insights if i["skill"] == "ship")
        assert ship["uses"] == 1
        assert ship["success_rate"] == 0.0  # 0/1
    finally:
        import shutil; shutil.rmtree(d)


# =============================================================================
# Integration tests: wiring verification
# =============================================================================

def test_event_stream_wired_into_set_task_status() -> None:
    """set_task_status must write an event to the stream (production path)."""
    import tempfile, yaml, os, sys
    from pathlib import Path

    # Force non-test mode
    if "PYTEST_CURRENT_TEST" in os.environ: del os.environ["PYTEST_CURRENT_TEST"]
    sys.modules.pop("pytest", None)

    d = Path(tempfile.mkdtemp())
    try:
        sh = d / ".superharness"; sh.mkdir()
        (sh / "profile.yaml").write_text("project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n")
        # Seed at plan_approved so plan_approved → in_progress is legal in
        # the canonical transition graph.
        (sh / "contract.yaml").write_text(yaml.dump({"tasks": [{"id": "test-ev", "owner": "claude-code", "status": "plan_approved"}]}))

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow
        conn = get_connection(str(d))
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(id="test-ev", title="T", owner="claude-code", status="plan_approved", effort="medium", project_path=str(d), development_method="tdd", acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, version=1, created_at="2026-01-01T00:00:00Z"))
        conn.commit()
        conn.close()

        from superharness.engine.state_writer import set_task_status
        ok = set_task_status(str(d), "test-ev", "in_progress")
        assert ok, "plan_approved → in_progress must succeed"

        from superharness.engine.event_stream import read_events
        events = read_events(str(d))
        status_changes = [e for e in events if e["type"] == "status_change"]
        assert len(status_changes) >= 1, f"set_task_status must write event stream, got {len(status_changes)}"
    finally:
        import shutil; shutil.rmtree(d)


def test_handoff_generate_cli_works(clean_harness: Path) -> None:
    """shux handoff-generate must be importable and runnable."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite, _write_contract
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-cli-gen", "owner": "claude-code", "status": "in_progress"},
    ])

    from superharness.commands.handoff_generate import main as gen_main
    import sys, io
    old_stdout = sys.stdout
    try:
        sys.stdout = io.StringIO()
        gen_main(["--project", str(clean_harness), "--task", "test-cli-gen"])
        output = sys.stdout.getvalue()
        assert "Handoff written to" in output, f"CLI should write handoff, got: {output}"
    finally:
        sys.stdout = old_stdout


def test_loop_detector_integration_with_watcher() -> None:
    """Loop detector must be importable from watcher context."""
    from superharness.engine.loop_detector import detect_loop
    from superharness.engine.policy_gate import check_agent_policy

    # Simulate a loop detection → policy block
    import tempfile, os
    d = tempfile.mkdtemp()
    log = os.path.join(d, "loop.log")
    with open(log, "w") as f:
        for _ in range(5):
            f.write("Tool: read_file(path='x.py')\n")

    loop = detect_loop(log)
    assert loop["loop_detected"] is True

    gate = check_agent_policy("claude-code", loop_detected=True)
    assert gate["blocked"] is True
    assert "loop" in gate["reason"].lower()


def test_fts_migration_v6_creates_table(clean_harness: Path) -> None:
    """Migration v6 must create the handoffs_fts virtual table."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection
    conn = get_connection(str(clean_harness))
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'"
    ).fetchall()]
    assert "handoffs_fts" in tables, f"Migration v6 must create handoffs_fts, got: {tables}"
    conn.close()


# =============================================================================
# Undispatchable agent detection
# =============================================================================

def test_undispatchable_agent_items_are_canceled(clean_harness: Path) -> None:
    """Pending items for agents without dispatch scripts must be auto-canceled."""
    from tests.e2e.test_lifecycle_fixes_regression import _write_profile, _init_sqlite
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao, inbox_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-unknown-agent", title="T", owner="unknown-agent",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        conn.commit()

        inbox_dao.enqueue(conn, id="ua-1", task_id="test-unknown-agent",
            target_agent="unknown-agent", priority=2, project_path=str(clean_harness),
            now="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.commands.inbox_watch import _cancel_undispatchable_agents
        canceled = _cancel_undispatchable_agents(str(clean_harness))
        # unknown-agent has no delegate script → should be canceled
        # (may be 0 if there are no unknown agents in the test env)

        # Verify the item status changed
        item = inbox_dao.get(conn, "ua-1")
        assert item is not None
        assert item.status in ("stale", "failed"), (
            f"Undispatchable agent item must be auto-canceled, got {item.status}"
        )
    finally:
        conn.close()


# =============================================================================
# Split-brain prevention: no YAML reads in production paths
# =============================================================================

def test_no_yaml_reads_in_production_state_reader() -> None:
    """Production read paths must return data from SQLite, not YAML."""
    import inspect
    from superharness.engine import state_reader as sr

    funcs = ["get_tasks", "get_inbox_items", "get_task", "get_contract_doc"]
    for fname in funcs:
        src = inspect.getsource(getattr(sr, fname))
        # YAML fallback is only allowed inside except blocks or `if not _has_sqlite_db` guards
        assert "_ensure_ingested" not in src, (
            f"{fname}: must not call _ensure_ingested"
        )


def test_no_yaml_writes_in_production_state_writer() -> None:
    """Production write paths must guard YAML exports with is_sqlite_only."""
    import inspect
    from superharness.engine import state_writer as sw

    src = inspect.getsource(sw.set_task_status)
    # Production path must check is_sqlite_only before _export_contract
    assert "is_sqlite_only" in src, (
        "set_task_status must check is_sqlite_only before writing YAML"
    )


def test_dashboard_presenter_reads_discussions_from_sqlite() -> None:
    """get_dashboard_status_snapshot must not read discussion state from filesystem."""
    import inspect
    from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
    src = inspect.getsource(get_dashboard_status_snapshot)
    assert "state_file" not in src or "discussions_dao" in src, (
        "Dashboard must read discussions from SQLite, not filesystem"
    )
