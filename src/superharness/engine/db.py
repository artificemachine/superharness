from __future__ import annotations

import os
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Callable, Any, Iterator
from contextlib import contextmanager

from superharness.engine.state_errors import ConnectionError, SchemaError

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2

def now_iso() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def get_connection(project_dir: str) -> sqlite3.Connection:
    """Open a connection to the state database.
    
    Sets WAL mode, foreign keys, and busy timeout.
    Raises ConnectionError if SQLite version is too old.
    """
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise ConnectionError(
            f"SQLite version 3.35.0 or higher required (found {sqlite3.sqlite_version})"
        )
    
    db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    try:
        conn = sqlite3.connect(db_path, timeout=5000)
        conn.row_factory = sqlite3.Row
        
        # Mandatory PRAGMAs
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        
        return conn
    except sqlite3.Error as e:
        raise ConnectionError(f"Could not open database at {db_path}: {e}")

@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Reentrant transaction context manager."""
    if conn.in_transaction:
        yield
        return
        
    try:
        with conn:
            yield
    except sqlite3.Error as e:
        # Wrap database errors if needed, but conn context manager handles rollback
        raise

def init_db(conn: sqlite3.Connection) -> None:
    """Initialize schema and run migrations."""
    # Ensure migration table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT    NOT NULL
        )
    """)
    
    # Check current version
    cursor = conn.execute("PRAGMA user_version")
    version = cursor.fetchone()[0]
    
    if version < CURRENT_SCHEMA_VERSION:
        _run_migrations(conn, version)

def _run_migrations(conn: sqlite3.Connection, current_version: int) -> None:
    """Apply pending migrations in order."""
    for v in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        migration_fn = _MIGRATIONS[v - 1]
        
        with transaction(conn):
            migration_fn(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (v, now_iso())
            )
            conn.execute(f"PRAGMA user_version = {v}")
            logger.info(f"Applied schema migration v{v}")

# --- Migration Functions ---

def _migration_v1(conn: sqlite3.Connection) -> None:
    """Initial schema creation."""
    
    # Tasks
    conn.execute("""
        CREATE TABLE tasks (
            id                   TEXT    PRIMARY KEY,
            title                TEXT    NOT NULL,
            owner                TEXT,
            status               TEXT    NOT NULL,
            effort               TEXT,
            project_path         TEXT,
            development_method   TEXT,
            acceptance_criteria  TEXT,
            test_types           TEXT,
            out_of_scope         TEXT,
            definition_of_done   TEXT,
            context              TEXT,
            tdd                  TEXT,
            version              INTEGER NOT NULL DEFAULT 1,
            created_at           TEXT    NOT NULL,
            plan_proposed_at     TEXT,
            plan_approved_at     TEXT,
            in_progress_at       TEXT,
            report_ready_at      TEXT,
            review_requested_at  TEXT,
            done_at              TEXT,
            cancelled_at         TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX idx_tasks_owner  ON tasks(owner)")

    # Task Dependencies
    conn.execute("""
        CREATE TABLE task_dependencies (
            dependent_task_id     TEXT NOT NULL,
            prerequisite_task_id  TEXT NOT NULL,
            PRIMARY KEY (dependent_task_id, prerequisite_task_id),
            FOREIGN KEY (dependent_task_id)    REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (prerequisite_task_id) REFERENCES tasks(id) ON DELETE RESTRICT
        )
    """)
    conn.execute("CREATE INDEX idx_deps_prereq ON task_dependencies(prerequisite_task_id)")

    # Inbox
    conn.execute("""
        CREATE TABLE inbox (
            id              TEXT    PRIMARY KEY,
            task_id         TEXT    NOT NULL,
            target_agent    TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            priority        INTEGER NOT NULL DEFAULT 2,
            retry_count     INTEGER NOT NULL DEFAULT 0,
            max_retries     INTEGER NOT NULL DEFAULT 3,
            pid             INTEGER,
            project_path    TEXT,
            plan_only       INTEGER NOT NULL DEFAULT 0,
            failed_reason   TEXT,
            created_at      TEXT    NOT NULL,
            launched_at     TEXT,
            last_heartbeat  TEXT,
            paused_at       TEXT,
            failed_at       TEXT,
            done_at         TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_inbox_status_priority ON inbox(status, priority DESC, created_at)")
    conn.execute("CREATE INDEX idx_inbox_heartbeat       ON inbox(status, last_heartbeat)")

    # Handoffs
    conn.execute("""
        CREATE TABLE handoffs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      TEXT    NOT NULL,
            phase        TEXT    NOT NULL,
            status       TEXT    NOT NULL,
            from_agent   TEXT,
            to_agent     TEXT,
            content      TEXT,
            metadata     TEXT,
            created_at   TEXT    NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_handoffs_task ON handoffs(task_id, created_at DESC)")

    # Failures
    conn.execute("""
        CREATE TABLE failures (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id        TEXT,
            agent          TEXT,
            pattern        TEXT,
            error_snippet  TEXT,
            created_at     TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_failures_task           ON failures(task_id)")
    conn.execute("CREATE INDEX idx_failures_agent_pattern  ON failures(agent, pattern)")

    # Decisions
    conn.execute("""
        CREATE TABLE decisions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            agent         TEXT,
            task_id       TEXT,
            decision      TEXT    NOT NULL,
            reason        TEXT,
            alternatives  TEXT,
            created_at    TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_decisions_agent_time ON decisions(agent, created_at)")

    # Ledger
    conn.execute("""
        CREATE TABLE ledger (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT,
            agent       TEXT,
            action      TEXT NOT NULL,
            details     TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_ledger_time ON ledger(created_at)")
    conn.execute("CREATE INDEX idx_ledger_task ON ledger(task_id, created_at)")

    # Review store
    conn.execute("""
        CREATE TABLE review_store (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            owner       TEXT    NOT NULL,
            task_type   TEXT    NOT NULL DEFAULT '',
            duration_s  REAL    NOT NULL DEFAULT 0,
            score       REAL    NOT NULL DEFAULT 0,
            failed      INTEGER NOT NULL DEFAULT 0,
            recorded_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX idx_review_owner_type ON review_store(owner, task_type)")

    # Watcher singleton
    conn.execute("""
        CREATE TABLE watcher_instance (
            key             TEXT    PRIMARY KEY CHECK (key = 'singleton'),
            pid             INTEGER NOT NULL,
            hostname        TEXT,
            started_at      TEXT    NOT NULL,
            last_heartbeat  TEXT    NOT NULL
        )
    """)

    # Parity queue
    conn.execute("""
        CREATE TABLE yaml_sync_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            op_type     TEXT    NOT NULL,
            payload     TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            attempts    INTEGER NOT NULL DEFAULT 0,
            last_error  TEXT,
            created_at  TEXT    NOT NULL,
            applied_at  TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_yaml_sync_pending ON yaml_sync_queue(status, created_at)")

def _migration_v2(conn: sqlite3.Connection) -> None:
    """Add parent_id to tasks, discussions tables, and yaml_sync_queue dedup index."""

    # F10: parent_id distinguishes top-level tasks from subtasks in the same table.
    # Subtasks have parent_id = their parent task id; top-level tasks have parent_id IS NULL.
    conn.execute("ALTER TABLE tasks ADD COLUMN parent_id TEXT REFERENCES tasks(id)")
    conn.execute("CREATE INDEX idx_tasks_parent ON tasks(parent_id)")

    # Discussions — persistent store for multi-agent discuss sessions.
    conn.execute("""
        CREATE TABLE discussions (
            id          TEXT PRIMARY KEY,
            task_id     TEXT,
            topic       TEXT NOT NULL,
            owners      TEXT NOT NULL DEFAULT '[]',
            status      TEXT NOT NULL DEFAULT 'active',
            consensus   TEXT,
            created_at  TEXT NOT NULL,
            closed_at   TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
        )
    """)
    conn.execute("CREATE INDEX idx_discussions_task   ON discussions(task_id)")
    conn.execute("CREATE INDEX idx_discussions_status ON discussions(status)")

    conn.execute("""
        CREATE TABLE discussion_rounds (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id   TEXT    NOT NULL,
            round_number    INTEGER NOT NULL,
            agent           TEXT    NOT NULL,
            content         TEXT,
            verdict         TEXT,
            created_at      TEXT    NOT NULL,
            FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_disc_rounds_disc ON discussion_rounds(discussion_id, round_number)")

    # F8: UNIQUE partial index on yaml_sync_queue prevents duplicate pending ops for the
    # same (op_type, entity id). NULL ids (for ops without an id field) are always distinct.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_yaml_sync_pending_dedup
        ON yaml_sync_queue(op_type, json_extract(payload, '$.id'))
        WHERE status = 'pending'
    """)


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_v1,
    _migration_v2,
]
