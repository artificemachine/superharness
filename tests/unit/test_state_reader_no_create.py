"""TDD coverage for iteration 2 of ``docs/PLAN-state-db-skeleton-leak.md``.

*"Les lectures de tâches sur état absent n'allouent ni répertoire ni fichier."*

Before this iteration, `get_tasks`, `get_task` and `get_top_level_tasks` each
reached `get_connection()` + `init_db()`, which create the directory and the full
340 KB schema for every distinct absolute path ever passed in — whether or not a
single row was ever written. That is the dominant source of the 22,485
content-free `state.db` directories measured in BUG-2026-09-18.

The guard is deliberately narrow: it fires only when there is neither a database
nor legacy YAML state to ingest, and it must not swallow a state-root conflict.
A project that has state keeps working, and an explicit legacy migration still
runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine.state_errors import ConnectionError
from superharness.engine.state_reader import (
    get_contract_doc,
    get_decisions,
    get_failures,
    get_handoffs,
    get_inbox_items,
    get_ledger_entries,
    get_task,
    get_tasks,
    get_top_level_tasks,
)
from superharness.utils.paths import StateDatabaseConflictError

# name -> (callable, expected empty result)
_READERS = {
    "get_tasks": (lambda project: get_tasks(project), []),
    "get_top_level_tasks": (lambda project: get_top_level_tasks(project), []),
    "get_task": (lambda project: get_task(project, "t1"), None),
}


@pytest.mark.parametrize("reader", sorted(_READERS))
def test_missing_task_reads_create_no_files(isolated_state_dir, tmp_path, reader):
    """Reading tasks from a project with no state must leave no trace."""
    read, expected = _READERS[reader]
    project = tmp_path / "never-initialised"
    project.mkdir()

    result = read(str(project))

    assert result == expected, f"{reader} returned {result!r} for an absent project"
    assert not (project / ".superharness").exists(), f"{reader} wrote into the project"
    assert not isolated_state_dir.exists(), (
        f"{reader} created the state root {isolated_state_dir}"
    )
    created = [str(p) for p in isolated_state_dir.rglob("state.db")]
    assert created == [], f"{reader} created state databases: {created}"


@pytest.mark.parametrize("reader", sorted(_READERS))
def test_task_read_preserves_state_conflicts(monkeypatch, tmp_path, reader):
    """An explicit state root that would split existing legacy state must raise.

    Degrading into an empty result here would report "this project has no tasks"
    for a project whose state root is misconfigured — the exact false-empty state
    the plan forbids. The reader surfaces the same `ConnectionError`
    `get_connection()` raises for this condition.
    """
    read, _ = _READERS[reader]
    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    (project / ".superharness" / "state.sqlite3").write_bytes(b"")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "shared-root"))

    with pytest.raises(ConnectionError) as excinfo:
        read(str(project))

    assert "SUPERHARNESS_STATE_DIR" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, StateDatabaseConflictError)


@pytest.mark.parametrize("reader", sorted(_READERS))
def test_task_reads_still_return_existing_state(monkeypatch, tmp_path, reader):
    """The guard must not block a project whose database does exist."""
    read, _ = _READERS[reader]
    state_dir = tmp_path / "state-root"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_dir))
    project = tmp_path / "initialised"
    project.mkdir()

    conn = get_connection(str(project))
    try:
        init_db(conn)
        conn.execute(
            "INSERT INTO tasks (id, title, status, created_at) "
            "VALUES ('t1', 'T', 'pending', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()

    result = read(str(project))

    if reader == "get_task":
        assert result is not None, "an existing task was not returned"
        assert result["id"] == "t1"
    else:
        assert [task["id"] for task in result] == ["t1"]


def test_legacy_migration_path_still_runs(tmp_path, monkeypatch):
    """`.superharness/` present means explicit legacy state: the ingest still runs.

    The guard is about a project with *nothing* to read, not about suppressing the
    documented YAML → SQLite migration for fixtures and upgrades.
    """
    state_dir = tmp_path / "state-root"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_dir))
    project = tmp_path / "legacy"
    (project / ".superharness").mkdir(parents=True)

    get_tasks(str(project))

    dbs = list(Path(state_dir).rglob("state.db"))
    assert dbs, "the legacy ingest path no longer creates the database it reads"


# --- iteration 3: the remaining state readers -------------------------------

# Readers with no legacy ingest path: nothing to read means nothing to create.
_OTHER_READERS = {
    "get_inbox_items": (lambda project: get_inbox_items(project), []),
    "get_handoffs": (lambda project: get_handoffs(project), []),
    "get_handoffs_for_task": (lambda project: get_handoffs(project, "t1"), []),
    "get_failures": (lambda project: get_failures(project), []),
    "get_decisions": (lambda project: get_decisions(project), []),
    "get_ledger_entries": (lambda project: get_ledger_entries(project), []),
}


@pytest.mark.parametrize("reader", sorted(_OTHER_READERS))
def test_other_missing_state_reads_create_no_files(
    isolated_state_dir, tmp_path, reader
):
    """Every remaining public reader must leave an absent project untouched."""
    read, expected = _OTHER_READERS[reader]
    project = tmp_path / "never-initialised"
    project.mkdir()

    result = read(str(project))

    assert result == expected, f"{reader} returned {result!r} for an absent project"
    assert not (project / ".superharness").exists(), f"{reader} wrote into the project"
    assert not isolated_state_dir.exists(), (
        f"{reader} created the state root {isolated_state_dir}"
    )


@pytest.mark.parametrize("reader", sorted(_OTHER_READERS))
def test_other_state_reads_preserve_state_conflicts(monkeypatch, tmp_path, reader):
    """A misconfigured state root must raise, never read as an empty result."""
    read, _ = _OTHER_READERS[reader]
    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    (project / ".superharness" / "state.sqlite3").write_bytes(b"")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "shared-root"))

    with pytest.raises(ConnectionError) as excinfo:
        read(str(project))

    assert isinstance(excinfo.value.__cause__, StateDatabaseConflictError)


def test_aggregate_contract_read_creates_no_files(isolated_state_dir, tmp_path):
    """`get_contract_doc` composes readers; none of them may create state."""
    project = tmp_path / "never-initialised"
    project.mkdir()

    contract = get_contract_doc(str(project))

    assert contract["tasks"] == []
    assert contract["decisions"] == []
    assert contract["failures"] == []
    assert not isolated_state_dir.exists(), (
        f"get_contract_doc created the state root {isolated_state_dir}"
    )


def test_aggregate_contract_keeps_its_default_id_and_goal(isolated_state_dir, tmp_path):
    """The aggregate's documented defaults must survive the absence guard."""
    project = tmp_path / "never-initialised"
    project.mkdir()

    contract = get_contract_doc(str(project))

    assert contract["id"] == "contract"
    assert contract["goal"] == ""
    assert sorted(contract) == ["decisions", "failures", "goal", "id", "tasks"]


def test_other_readers_still_return_existing_state(monkeypatch, tmp_path):
    """The iteration-3 guard must not block a project whose database exists."""
    state_dir = tmp_path / "state-root"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_dir))
    project = tmp_path / "initialised"
    project.mkdir()

    conn = get_connection(str(project))
    try:
        init_db(conn)
        conn.commit()
    finally:
        conn.close()

    assert get_inbox_items(str(project)) == []
    assert get_handoffs(str(project)) == []
    assert get_failures(str(project)) == []
    assert get_decisions(str(project)) == []
    assert get_ledger_entries(str(project)) == []
    assert get_contract_doc(str(project))["id"] == "contract"
