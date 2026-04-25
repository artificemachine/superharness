from __future__ import annotations

import sqlite3
from typing import Iterator
from pathlib import Path

import pytest

@pytest.fixture
def db_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    from superharness.engine.db import get_connection, init_db
    project = tmp_path
    (project / ".superharness").mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    yield conn
    conn.close()
