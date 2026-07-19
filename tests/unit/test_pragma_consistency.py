"""Pragma consistency tests (arch A3).

Several modules open raw sqlite3 connections instead of going through
engine.db.get_connection, which risks skipping the mandatory WAL /
foreign_keys / busy_timeout pragmas applied there. Each connection-opening
path below must either route through get_connection or apply the same
pragmas inline. These tests assert the pragmas actually land on the
connection object each path yields.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from superharness.engine import db as db_module


def _pragma(conn: sqlite3.Connection, name: str):
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def _assert_mandatory_pragmas(conn: sqlite3.Connection) -> None:
    assert _pragma(conn, "foreign_keys") == 1, "foreign_keys must be ON"
    assert _pragma(conn, "busy_timeout") == 5000, "busy_timeout must be 5000ms"


# ---------------------------------------------------------------------------
# engine/insights.py — rerouted through db.get_connection
# ---------------------------------------------------------------------------

def test_insights_connection_has_mandatory_pragmas(tmp_path, monkeypatch):
    project_dir = str(tmp_path)

    # Seed a real, migrated state db at the path get_insights will resolve.
    seed_conn = db_module.get_connection(project_dir)
    db_module.init_db(seed_conn, project_dir)
    seed_conn.close()

    # get_insights closes its connection in a finally block, so pragmas must
    # be read from the spy at open time, not from the (by-then-closed) object
    # afterward.
    captured: list[tuple] = []
    real_get_connection = db_module.get_connection

    def _spy(pdir):
        conn = real_get_connection(pdir)
        captured.append((_pragma(conn, "foreign_keys"), _pragma(conn, "busy_timeout")))
        return conn

    monkeypatch.setattr(db_module, "get_connection", _spy)

    from superharness.engine import insights

    result = insights.get_insights(project_dir)

    assert captured, "get_insights did not open a connection via db.get_connection"
    foreign_keys, busy_timeout = captured[0]
    assert foreign_keys == 1, "foreign_keys must be ON"
    assert busy_timeout == 5000, "busy_timeout must be 5000ms"
    assert "tasks" in result


# ---------------------------------------------------------------------------
# mcp/session.py — raw connect (check_same_thread=False), pragmas inline
# ---------------------------------------------------------------------------

def _make_mcp_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    sh = proj / ".superharness"
    sh.mkdir(parents=True)
    conn = sqlite3.connect(str(sh / "state.sqlite3"))
    conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY)")
    conn.close()
    return proj


def test_mcp_session_connection_has_mandatory_pragmas(tmp_path):
    from superharness.mcp.session import SessionManager

    proj = _make_mcp_project(tmp_path)
    sm = SessionManager()
    sm.init_session("conn-pragma", str(proj), agent="claude-code")
    conn = sm.get_connection("conn-pragma")
    _assert_mandatory_pragmas(conn)


# ---------------------------------------------------------------------------
# engine/operator_memory.py — raw connect, pragmas inline
# ---------------------------------------------------------------------------

def test_operator_memory_connection_has_mandatory_pragmas(tmp_path):
    from superharness.engine.operator_memory import OperatorMemory

    db_path = str(tmp_path / "operator-state.db")
    om = OperatorMemory(db_path)
    try:
        om.ensure_table()
        conn = om._get_conn()
        _assert_mandatory_pragmas(conn)
    finally:
        om.close()
