from __future__ import annotations

import os
import sqlite3
from typing import Iterator
from pathlib import Path

import pytest

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
