"""Tests for MCP SessionManager — Iteration 1."""
from __future__ import annotations

import os
import sqlite3
import pytest
from pathlib import Path

from superharness.mcp.session import SessionManager, PolicyError
from superharness.utils.paths import resolve_xdg_state_db_path


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project with a state.sqlite3."""
    proj = tmp_path / "proj"
    sh = proj / ".superharness"
    sh.mkdir(parents=True)
    conn = sqlite3.connect(str(sh / "state.sqlite3"))
    conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY)")
    conn.close()
    return proj


def test_init_session_valid_project(tmp_path):
    proj = _make_project(tmp_path)
    sm = SessionManager()
    conn_id = sm.init_session("conn-1", str(proj), agent="claude-code")
    assert conn_id == "conn-1"
    assert sm.get_connection("conn-1") is not None


def test_init_session_invalid_project(tmp_path):
    sm = SessionManager()
    with pytest.raises((ValueError, FileNotFoundError)):
        sm.init_session("conn-x", str(tmp_path / "missing"), agent="claude-code")


def test_two_sessions_same_project_isolated_conns(tmp_path):
    proj = _make_project(tmp_path)
    sm = SessionManager()
    sm.init_session("conn-a", str(proj), agent="claude-code")
    sm.init_session("conn-b", str(proj), agent="codex-cli")
    conn_a = sm.get_connection("conn-a")
    conn_b = sm.get_connection("conn-b")
    assert conn_a is not conn_b


def test_two_sessions_different_projects_isolated(tmp_path):
    proj_a = _make_project(tmp_path / "a")
    proj_b = _make_project(tmp_path / "b")
    sm = SessionManager()
    sm.init_session("a1", str(proj_a), agent="claude-code")
    sm.init_session("b1", str(proj_b), agent="claude-code")
    assert sm.get_session("a1").project_path != sm.get_session("b1").project_path


def test_close_session_releases_connection(tmp_path):
    proj = _make_project(tmp_path)
    sm = SessionManager()
    sm.init_session("conn-c", str(proj), agent="claude-code")
    sm.close_session("conn-c")
    with pytest.raises(KeyError):
        sm.get_connection("conn-c")


def test_get_connection_unknown_raises_key_error(tmp_path):
    sm = SessionManager()
    with pytest.raises(KeyError):
        sm.get_connection("does-not-exist")


def test_session_stores_agent_name(tmp_path):
    proj = _make_project(tmp_path)
    sm = SessionManager()
    sm.init_session("conn-d", str(proj), agent="gemini-cli")
    session = sm.get_session("conn-d")
    assert session.agent == "gemini-cli"


# ---------------------------------------------------------------------------
# XDG path migration (Iteration 3)
# ---------------------------------------------------------------------------

def test_init_session_prefers_xdg_over_legacy(tmp_path, monkeypatch):
    """When state.db exists at the XDG path, it is opened instead of .superharness/."""
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    proj = str(tmp_path / "myproject")
    db_path = resolve_xdg_state_db_path(proj)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY)")
    conn.close()

    sm = SessionManager()
    conn_id = sm.init_session("xdg-1", proj, agent="claude-code")
    assert conn_id == "xdg-1"
    assert sm.get_connection("xdg-1") is not None


def test_init_session_falls_back_to_legacy_when_xdg_absent(tmp_path, monkeypatch):
    """When XDG path has no db, the legacy .superharness/state.sqlite3 is opened."""
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    proj = _make_project(tmp_path)  # creates only the legacy path
    sm = SessionManager()
    conn_id = sm.init_session("legacy-1", str(proj), agent="claude-code")
    assert conn_id == "legacy-1"


# ── Iter 13 RED: MCP session timeout must be seconds, not milliseconds ─────────

def test_timeout_is_seconds():
    """sqlite3.connect timeout in session.py must be seconds, not milliseconds.

    RED: session.py:57 passes timeout=5000, which means a 5000-second wait.
    sqlite3.connect's timeout is in seconds, not ms. Correct value is 5.0.
    """
    import inspect
    import superharness.mcp.session as mod
    src = inspect.getsource(mod)
    # timeout=5000 is clearly wrong (5000 seconds). Find any bad value.
    import re
    bad = re.search(r"sqlite3\.connect\(.*?timeout\s*=\s*(\d{4,})", src)
    assert bad is None, (
        f"Found timeout={bad.group(1)} in mcp/session.py sqlite3.connect call. "
        "sqlite3 timeout is in seconds, not milliseconds. Fix: timeout=5.0"
    )
