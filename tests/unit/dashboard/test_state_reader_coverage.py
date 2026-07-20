"""RED tests for new state_reader functions: get_failures, get_decisions, get_ledger_entries.

These tests verify the three new SQLite-backed read functions that the dashboard
needs to replace direct DAO access. They assume the functions do NOT yet exist,
so the initial run should fail with AttributeError.
"""

import json
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import failures_dao, decisions_dao, ledger_dao


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def seeded_project(tmp_path: Path) -> Path:
    """Create a project with a SQLite DB seeded with failures, decisions, ledger."""
    project = tmp_path / "project"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks: []\n")
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")

    conn = get_connection(str(project))
    try:
        init_db(conn)
        # task-1/task-2 must exist since failures/decisions/ledger.task_id
        # is FK'd to tasks(id) (migration v33).
        for _tid in ("task-1", "task-2"):
            conn.execute(
                "INSERT INTO tasks (id, title, status, version, created_at) "
                "VALUES (?, ?, 'todo', 1, '2026-04-30T00:00:00Z')",
                (_tid, _tid),
            )
        # Seed failures
        failures_dao.record(
            conn, task_id="task-1", agent="claude-code",
            pattern="timeout", error_snippet="Connection timed out",
            now="2026-04-30T10:00:00Z",
        )
        failures_dao.record(
            conn, task_id="task-2", agent="codex-cli",
            pattern="parse_error", error_snippet="Unexpected token at line 12",
            now="2026-04-30T11:00:00Z",
        )
        # Seed decisions
        decisions_dao.record(
            conn, agent="claude-code", task_id="task-1",
            decision="retry", reason="Transient network error",
            alternatives=["fail", "skip"],
            now="2026-04-30T10:05:00Z",
        )
        # Seed ledger
        ledger_dao.record(
            conn, task_id="task-1", agent="claude-code",
            action="delegate", details={"target": "codex-cli"},
            now="2026-04-30T09:55:00Z",
        )
        ledger_dao.record(
            conn, task_id="task-2", agent="codex-cli",
            action="close", details={"resolution": "completed"},
            now="2026-04-30T12:00:00Z",
        )
        conn.commit()
    finally:
        conn.close()
    return project


# ── RED tests: get_failures ────────────────────────────────────────────────────

def test_get_failures_returns_empty_list_for_empty_db(tmp_path: Path):
    """A fresh DB with no failures should return an empty list."""
    from superharness.engine.state_reader import get_failures

    project = tmp_path / "empty"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks: []\n")
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")

    conn = get_connection(str(project))
    try:
        init_db(conn)
        conn.commit()
    finally:
        conn.close()

    result = get_failures(str(project))
    assert isinstance(result, list)
    assert len(result) == 0


def test_get_failures_returns_seeded_rows(seeded_project: Path):
    """get_failures should return all seeded failure rows."""
    from superharness.engine.state_reader import get_failures

    result = get_failures(str(seeded_project))
    assert isinstance(result, list)
    assert len(result) == 2

    # Each dict should have the expected keys
    for item in result:
        assert "task_id" in item or "task" in item
        assert "agent" in item
        assert "error_snippet" in item

    task_ids = [item.get("task_id", item.get("task")) for item in result]
    assert "task-1" in task_ids
    assert "task-2" in task_ids


# ── RED tests: get_decisions ───────────────────────────────────────────────────

def test_get_decisions_returns_empty_list_for_empty_db(tmp_path: Path):
    """A fresh DB with no decisions should return an empty list."""
    from superharness.engine.state_reader import get_decisions

    project = tmp_path / "empty"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks: []\n")
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")

    conn = get_connection(str(project))
    try:
        init_db(conn)
        conn.commit()
    finally:
        conn.close()

    result = get_decisions(str(project))
    assert isinstance(result, list)
    assert len(result) == 0


def test_get_decisions_returns_seeded_rows(seeded_project: Path):
    """get_decisions should return all seeded decision rows."""
    from superharness.engine.state_reader import get_decisions

    result = get_decisions(str(seeded_project))
    assert isinstance(result, list)
    assert len(result) == 1

    item = result[0]
    assert item.get("agent") == "claude-code"
    assert item.get("decision") == "retry"
    assert "reason" in item


# ── RED tests: get_ledger_entries ──────────────────────────────────────────────

def test_get_ledger_entries_returns_empty_list_for_empty_db(tmp_path: Path):
    """A fresh DB with no ledger entries should return an empty list."""
    from superharness.engine.state_reader import get_ledger_entries

    project = tmp_path / "empty"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks: []\n")
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")

    conn = get_connection(str(project))
    try:
        init_db(conn)
        conn.commit()
    finally:
        conn.close()

    result = get_ledger_entries(str(project))
    assert isinstance(result, list)
    assert len(result) == 0


def test_get_ledger_entries_returns_seeded_rows(seeded_project: Path):
    """get_ledger_entries should return all seeded ledger entries."""
    from superharness.engine.state_reader import get_ledger_entries

    result = get_ledger_entries(str(seeded_project))
    assert isinstance(result, list)
    assert len(result) == 2

    actions = [item.get("action") for item in result]
    assert "delegate" in actions
    assert "close" in actions

    # LedgerRow.details is a dict (JSON in SQLite), check it's a dict not a string
    delegate = next(item for item in result if item.get("action") == "delegate")
    assert isinstance(delegate.get("details"), dict)


def test_get_ledger_entries_respects_hours_filter(seeded_project: Path):
    """get_ledger_entries with hours=0 should return empty (no recent entries)."""
    from superharness.engine.state_reader import get_ledger_entries

    # hours=0 should filter out everything (no entries within 0 hours from now)
    result = get_ledger_entries(str(seeded_project), hours=0)
    assert isinstance(result, list)
    assert len(result) == 0
