"""State-path safety tests for Operator database initialization."""
from __future__ import annotations

import os
import sqlite3

import pytest

from superharness.engine.operator import Operator
from superharness.utils.paths import (
    StateDatabaseConflictError,
    project_hash,
    resolve_xdg_state_db_path,
)


def test_operator_override_conflict_is_fatal_and_non_destructive(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    legacy = project / ".superharness" / "state.sqlite3"
    legacy.parent.mkdir(parents=True)
    legacy.touch()
    override = tmp_path / "shared"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(override))

    with pytest.raises(StateDatabaseConflictError):
        Operator(project)._ensure_db_initialized()

    target = override / project_hash(str(project)) / "state.db"
    assert legacy.exists()
    assert legacy.stat().st_size == 0
    assert not target.exists()
    assert not target.parent.exists()


def test_operator_repairs_only_plain_resolver_selection(tmp_path, monkeypatch):
    project = tmp_path / "project"
    legacy = project / ".superharness" / "state.sqlite3"
    legacy.parent.mkdir(parents=True)
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-home"))
    xdg_path = resolve_xdg_state_db_path(str(project))
    os.makedirs(os.path.dirname(xdg_path), exist_ok=True)
    open(xdg_path, "w").close()

    Operator(project)._ensure_db_initialized()

    assert legacy.exists()
    conn = sqlite3.connect(legacy)
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='marker'"
        ).fetchone()
    finally:
        conn.close()
