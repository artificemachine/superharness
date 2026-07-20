from __future__ import annotations

import os
import sqlite3
from typing import Iterator
from pathlib import Path

import pytest


def seed_task(conn: sqlite3.Connection, task_id: str) -> None:
    """Insert a minimal tasks row so FK-constrained child inserts
    (failures/decisions/ledger.task_id) don't need a full TaskRow."""
    conn.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) "
        "VALUES (?, ?, 'todo', 1, '2026-01-01T00:00:00Z')",
        (task_id, task_id),
    )


@pytest.fixture
def db_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    from superharness.engine.db import get_connection, init_db
    from superharness.utils.paths import resolve_xdg_state_db_path
    project = tmp_path
    (project / ".superharness").mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    yield conn
    conn.close()
    # Remove the XDG state db so stale rows don't bleed into future runs
    # that happen to generate the same tmp_path (pytest cycles base dirs).
    xdg_db = resolve_xdg_state_db_path(str(project))
    if os.path.isfile(xdg_db):
        try:
            os.remove(xdg_db)
        except OSError:
            pass
