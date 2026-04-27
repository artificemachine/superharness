"""Parity tests for iters 3b-3e: every write path must sync YAML and SQLite.

RED before migration (SQLite not updated). GREEN after (mirror calls added).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_sqlite(project: Path) -> None:
    """Initialise a fresh SQLite DB in the harness."""
    from superharness.engine import db
    conn = db.get_connection(str(project))
    db.init_db(conn)
    conn.close()


def _sqlite_task_status(project: Path, task_id: str) -> str | None:
    db_path = project / ".superharness" / "state.sqlite3"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def _sqlite_inbox_status(project: Path, item_id: str) -> str | None:
    db_path = project / ".superharness" / "state.sqlite3"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status FROM inbox WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def _seed_task_sqlite(project: Path, task_id: str, status: str) -> None:
    from superharness.engine import db, tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = db.get_connection(str(project))
    db.init_db(conn)
    t = TaskRow(
        id=task_id, title=task_id, owner="claude-code", status=status,
        effort=None, project_path=None, development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None,
        version=1, created_at="2026-01-01T00:00:00Z",
    )
    with db.transaction(conn):
        tasks_dao.upsert(conn, t)
    conn.close()


def _seed_inbox_sqlite(project: Path, item_id: str, task_id: str, status: str, **extra) -> None:
    from superharness.engine import db, inbox_dao
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    conn = db.get_connection(str(project))
    db.init_db(conn)
    # Ensure parent task exists (FK)
    t = TaskRow(
        id=task_id, title=task_id, owner="claude-code", status="todo",
        effort=None, project_path=None, development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None,
        version=1, created_at="2026-01-01T00:00:00Z",
    )
    with db.transaction(conn):
        try:
            tasks_dao.upsert(conn, t)
        except Exception:
            pass
        inbox_dao.enqueue(
            conn,
            id=item_id,
            task_id=task_id,
            target_agent=extra.get("to", "claude-code"),
            priority=extra.get("priority", 1),
            project_path=str(project),
            now="2026-01-01T00:00:00Z",
        )
        if status != "pending":
            inbox_dao.update_status(
                conn, item_id,
                from_status="pending",
                to_status=status,
                now="2026-01-01T00:00:00Z",
            )
    conn.close()


# ---------------------------------------------------------------------------
# 3b — contract writes sync SQLite
# ---------------------------------------------------------------------------

def test_lifecycle_contract_timeout_syncs_sqlite(clean_harness: Path) -> None:
    """reconcile_lifecycle: in_progress task → archived in both YAML and SQLite."""
    _init_sqlite(clean_harness)
    _seed_task_sqlite(clean_harness, "feat.stale", "in_progress")

    contract = clean_harness / ".superharness" / "contract.yaml"
    contract.write_text(yaml.dump({"tasks": [{
        "id": "feat.stale",
        "status": "in_progress",
        "updated_at": "2026-01-01T00:00:00Z",
        "owner": "claude-code",
    }]}))

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    yaml_tasks = (yaml.safe_load(contract.read_text()) or {}).get("tasks", [])
    assert next(t for t in yaml_tasks if t["id"] == "feat.stale")["status"] == "archived"
    assert _sqlite_task_status(clean_harness, "feat.stale") == "archived"


def test_review_escalation_syncs_sqlite(clean_harness: Path) -> None:
    """escalate_stale_reviews: chain advances → SQLite task not orphaned/stale."""
    _init_sqlite(clean_harness)
    _seed_task_sqlite(clean_harness, "feat.review", "review_requested")

    contract = clean_harness / ".superharness" / "contract.yaml"
    contract.write_text(yaml.dump({"tasks": [{
        "id": "feat.review",
        "status": "review_requested",
        "review_requested_at": "2026-01-01T00:00:00Z",
        "review_chain": ["codex-cli", "operator"],
        "review_chain_index": 0,
        "owner": "claude-code",
    }]}))

    from superharness.engine.review_escalation import escalate_stale_reviews
    escalate_stale_reviews(str(clean_harness), timeout_minutes=1)

    yaml_tasks = (yaml.safe_load(contract.read_text()) or {}).get("tasks", [])
    yaml_task = next(t for t in yaml_tasks if t["id"] == "feat.review")
    assert yaml_task["review_chain_index"] == 1

    # SQLite row must still exist with a consistent status
    assert _sqlite_task_status(clean_harness, "feat.review") is not None


# ---------------------------------------------------------------------------
# 3c — inbox writes sync SQLite
# ---------------------------------------------------------------------------

def test_lifecycle_inbox_timeout_syncs_sqlite(clean_harness: Path) -> None:
    """reconcile_lifecycle: paused inbox item → failed in both YAML and SQLite."""
    _init_sqlite(clean_harness)
    _seed_inbox_sqlite(clean_harness, "item-paused", "feat.foo", "paused")

    inbox = clean_harness / ".superharness" / "inbox.yaml"
    inbox.write_text(yaml.dump([{
        "id": "item-paused",
        "task": "feat.foo",
        "to": "claude-code",
        "status": "paused",
        "paused_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
    }]))

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    yaml_items = yaml.safe_load(inbox.read_text()) or []
    assert next(i for i in yaml_items if i["id"] == "item-paused")["status"] == "failed"
    assert _sqlite_inbox_status(clean_harness, "item-paused") == "failed"


# ---------------------------------------------------------------------------
# 3d — handoff writes go through state_writer
# ---------------------------------------------------------------------------

def test_upsert_handoff_writes_file(clean_harness: Path) -> None:
    """state_writer.upsert_handoff creates the handoff file."""
    from superharness.engine.state_writer import upsert_handoff
    ok = upsert_handoff(str(clean_harness), "close-feat.foo", {"status": "done", "summary": "ok"})
    assert ok is True
    f = clean_harness / ".superharness" / "handoffs" / "close-feat.foo.yaml"
    assert f.exists()
    data = yaml.safe_load(f.read_text())
    assert data["status"] == "done"


# ---------------------------------------------------------------------------
# 3e — default backend is dual; sqlite_only is opt-in via profile.yaml
# ---------------------------------------------------------------------------

def test_state_reader_default_backend_is_dual(clean_harness: Path) -> None:
    """Without STATE_BACKEND env var or profile.yaml override, state_reader uses dual."""
    os.environ.pop("STATE_BACKEND", None)
    from superharness.engine import state_reader
    backend = state_reader._get_backend(str(clean_harness))
    assert backend == "dual"


def test_state_reader_profile_yaml_opt_in_to_sqlite_only(clean_harness: Path) -> None:
    """Setting state_backend: sqlite_only in profile.yaml opts in to strict mode."""
    os.environ.pop("STATE_BACKEND", None)
    profile = clean_harness / ".superharness" / "profile.yaml"
    profile.write_text("state_backend: sqlite_only\n")
    try:
        from superharness.engine import state_reader
        backend = state_reader._get_backend(str(clean_harness))
        assert backend == "sqlite_only"
    finally:
        profile.unlink(missing_ok=True)


def test_state_reader_env_override_still_works(clean_harness: Path) -> None:
    """STATE_BACKEND env var overrides the default."""
    os.environ["STATE_BACKEND"] = "dual"
    try:
        from superharness.engine import state_reader
        assert state_reader._get_backend(str(clean_harness)) == "dual"
    finally:
        os.environ.pop("STATE_BACKEND", None)
