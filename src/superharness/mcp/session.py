"""MCP SessionManager — Iteration 1.

Maps conn_id → ProjectSession. Each session holds an independent SQLite
connection so concurrent agents never share a connection object.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass

from superharness.utils.paths import resolve_xdg_state_db_path

import logging
logger = logging.getLogger(__name__)


class PolicyError(Exception):
    """Raised when an agent's policy limits are exceeded."""


@dataclass
class ProjectSession:
    conn_id: str
    project_path: str
    agent: str
    conn: sqlite3.Connection
    policy: dict


class SessionManager:
    """Thread-safe registry of active MCP sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ProjectSession] = {}
        self._lock = threading.Lock()

    def init_session(self, conn_id: str, project_path: str, agent: str = "unknown") -> str:
        """Open a new session for *project_path*. Returns *conn_id*.

        Tries the XDG state path first (new installs), falls back to the
        legacy .superharness/state.sqlite3 for existing projects.
        """
        xdg_path = resolve_xdg_state_db_path(project_path)
        legacy_path = os.path.join(project_path, ".superharness", "state.sqlite3")
        if os.path.isfile(xdg_path):
            db_path = xdg_path
        elif os.path.isfile(legacy_path):
            db_path = legacy_path
        else:
            raise ValueError(
                f"No superharness state found. Tried:\n  {xdg_path}\n  {legacy_path}\n"
                "Run 'shux init' first."
            )

        conn = sqlite3.connect(db_path, timeout=5000, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        policy = self._load_policy(agent)
        session = ProjectSession(
            conn_id=conn_id,
            project_path=os.path.realpath(project_path),
            agent=agent,
            conn=conn,
            policy=policy,
        )
        with self._lock:
            self._sessions[conn_id] = session
        return conn_id

    def get_connection(self, conn_id: str) -> sqlite3.Connection:
        """Return the SQLite connection for *conn_id*. Raises KeyError if not found."""
        with self._lock:
            if conn_id not in self._sessions:
                raise KeyError(f"No session '{conn_id}'")
            return self._sessions[conn_id].conn

    def get_session(self, conn_id: str) -> ProjectSession:
        """Return the full ProjectSession. Raises KeyError if not found."""
        with self._lock:
            if conn_id not in self._sessions:
                raise KeyError(f"No session '{conn_id}'")
            return self._sessions[conn_id]

    def close_session(self, conn_id: str) -> None:
        """Close and remove a session."""
        with self._lock:
            session = self._sessions.pop(conn_id, None)
        if session:
            try:
                session.conn.close()
            except Exception as e:
                logger.warning("session.py unexpected error: %s", e, exc_info=True)
                pass
    def active_sessions(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    @staticmethod
    def _load_policy(agent: str) -> dict:
        """Load agent policy from adapter manifest (non-fatal — returns defaults on error)."""
        try:
            import importlib.resources as _res
            import yaml
            manifests = _res.files("superharness").joinpath("adapter_manifests")
            manifest_path = manifests.joinpath(f"{agent}.yaml")
            text = manifest_path.read_text()
            data = yaml.safe_load(text) or {}
            return data.get("policy", {})
        except Exception as e:
            logger.warning("session.py unexpected error: %s", e, exc_info=True)
            return {}


# Module-level singleton used by the MCP server
_manager = SessionManager()


def get_manager() -> SessionManager:
    return _manager
