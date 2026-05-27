from __future__ import annotations

import os
import sqlite3
import logging
import shutil
from datetime import datetime, timezone
from typing import Callable, Any, Iterator
from contextlib import contextmanager

from superharness.engine.state_errors import ConnectionError, SchemaError
from superharness.utils.paths import resolve_xdg_state_db_path

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 26

def now_iso() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table using PRAGMA table_info.

    Robust to both row_factory=None (returns tuples) and row_factory=Row.
    Previously required row_factory=Row; missing it caused silent migration
    drift where ALTER columns weren't added but user_version still bumped.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for r in rows:
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        name = r["name"] if hasattr(r, "keys") else r[1]
        if name == column:
            return True
    return False

def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl_clause: str):
    """Add a column to a table if it doesn't already exist."""
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_clause}")

def _backup_db(project_dir: str, version: int):
    """Create a backup of the database before a migration.

    Backs up from wherever the db actually lives (XDG path or legacy path).
    """
    if not project_dir:
        return
    xdg = resolve_xdg_state_db_path(project_dir)
    legacy = os.path.join(project_dir, ".superharness", "state.sqlite3")
    src = xdg if os.path.isfile(xdg) else legacy
    dst = f"{src}.bak.v{version}"
    if os.path.isfile(src) and not os.path.isfile(dst):
        try:
            shutil.copy2(src, dst)
            logger.info(f"Created pre-migration backup: {dst}")
        except Exception as e:
            raise SchemaError(f"Pre-migration backup failed for v{version} at {dst}: {e}") from e


def get_connection(project_dir: str) -> sqlite3.Connection:
    """Open a connection to the state database.

    Path resolution order:
      1. XDG state path (~/.local/state/superharness/<hash>/state.db) if it exists.
      2. Legacy path (.superharness/state.sqlite3) if it exists.
      3. .superharness/ directory exists but no db yet → use legacy path (project
         initialized via shux init but db not yet created; backward-compat until
         shux init is updated to seed the XDG path directly).
      4. Neither → create at XDG path (truly new project with no .superharness/).

    Sets WAL mode, foreign keys, and busy timeout.
    Raises ConnectionError if SQLite version is too old.
    """
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise ConnectionError(
            f"SQLite version 3.35.0 or higher required (found {sqlite3.sqlite_version})"
        )

    # When dispatching from a git worktree the caller sets SUPERHARNESS_STATE_PROJECT
    # to the original project path so state reads use the correct XDG hash instead
    # of hashing the ephemeral worktree path and opening an empty database.
    state_project = os.environ.get("SUPERHARNESS_STATE_PROJECT", "").strip() or project_dir

    xdg_path = resolve_xdg_state_db_path(state_project)
    legacy_path = os.path.join(state_project, ".superharness", "state.sqlite3")
    legacy_dir = os.path.join(state_project, ".superharness")

    if os.path.isfile(xdg_path):
        db_path = xdg_path
    elif os.path.isfile(legacy_path):
        db_path = legacy_path
    elif os.path.isdir(legacy_dir):
        db_path = legacy_path  # initialized project, db not yet created
    else:
        db_path = xdg_path  # new project — create at XDG location

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

@contextmanager
def managed_connection(project_dir: str) -> Iterator[sqlite3.Connection]:
    """Context manager: open connection, init DB, commit on success, close always.
    
    Usage:
        with managed_connection(project_dir) as conn:
            tasks_dao.upsert(conn, row)
    """
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(conn: sqlite3.Connection, project_dir: str | None = None) -> None:
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
        _run_migrations(conn, version, project_dir)

def _run_migrations(conn: sqlite3.Connection, current_version: int, project_dir: str | None = None) -> None:
    """Apply pending migrations in order."""
    for v in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        _run_single_migration(conn, v, project_dir)

def _run_single_migration(conn: sqlite3.Connection, v: int, project_dir: str | None = None) -> None:
    """Run a single schema migration with backup and rollback."""
    if project_dir:
        _backup_db(project_dir, v - 1)
        
    with transaction(conn):
        conn.execute(f"SAVEPOINT migrate_v{v}")
        try:
            migration_fn = _MIGRATIONS[v - 1]
            migration_fn(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (v, now_iso())
            )
            conn.execute(f"PRAGMA user_version = {v}")
            conn.execute(f"RELEASE SAVEPOINT migrate_v{v}")
            logger.info(f"Applied schema migration v{v}")
        except Exception as e:
            logger.error("Migration v%d failed: %s — rolling back", v, e)
            conn.execute(f"ROLLBACK TO SAVEPOINT migrate_v{v}")
            raise

# --- Migration Functions ---

def _migration_v1(conn: sqlite3.Connection) -> None:
    """Initial schema creation."""
    
    # Tasks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner  ON tasks(owner)")

    # Task Dependencies
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_dependencies (
            dependent_task_id     TEXT NOT NULL,
            prerequisite_task_id  TEXT NOT NULL,
            PRIMARY KEY (dependent_task_id, prerequisite_task_id),
            FOREIGN KEY (dependent_task_id)    REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (prerequisite_task_id) REFERENCES tasks(id) ON DELETE RESTRICT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deps_prereq ON task_dependencies(prerequisite_task_id)")

    # Inbox
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inbox (
            id              TEXT    PRIMARY KEY,
            task_id         TEXT    NOT NULL,
            target_agent    TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            priority        INTEGER NOT NULL DEFAULT 2,
            retry_count     INTEGER NOT NULL DEFAULT 0,
            max_retries     INTEGER NOT NULL DEFAULT 3,
            recovery_count  INTEGER NOT NULL DEFAULT 0,
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_status_priority ON inbox(status, priority DESC, created_at)")
    conn.execute("CREATE INDEX idx_inbox_heartbeat       ON inbox(status, last_heartbeat)")

    # Handoffs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS handoffs (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_handoffs_task ON handoffs(task_id, created_at DESC)")

    # Failures
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failures (
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
        CREATE TABLE IF NOT EXISTS decisions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            agent         TEXT,
            task_id       TEXT,
            decision      TEXT    NOT NULL,
            reason        TEXT,
            alternatives  TEXT,
            created_at    TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_agent_time ON decisions(agent, created_at)")

    # Ledger
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ledger (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT,
            agent       TEXT,
            action      TEXT NOT NULL,
            details     TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_time ON ledger(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_task ON ledger(task_id, created_at)")

    # Review store
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_store (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            owner       TEXT    NOT NULL,
            task_type   TEXT    NOT NULL DEFAULT '',
            duration_s  REAL    NOT NULL DEFAULT 0,
            score       REAL    NOT NULL DEFAULT 0,
            failed      INTEGER NOT NULL DEFAULT 0,
            recorded_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_owner_type ON review_store(owner, task_type)")

    # Watcher singleton
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watcher_instance (
            key             TEXT    PRIMARY KEY CHECK (key = 'singleton'),
            pid             INTEGER NOT NULL,
            hostname        TEXT,
            started_at      TEXT    NOT NULL,
            last_heartbeat  TEXT    NOT NULL
        )
    """)

    # Parity queue
    conn.execute("""
        CREATE TABLE IF NOT EXISTS yaml_sync_queue (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_yaml_sync_pending ON yaml_sync_queue(status, created_at)")

def _migration_v2(conn: sqlite3.Connection) -> None:
    """Add parent_id to tasks, discussions tables, and yaml_sync_queue dedup index."""

    # F10: parent_id distinguishes top-level tasks from subtasks in the same table.
    # Subtasks have parent_id = their parent task id; top-level tasks have parent_id IS NULL.
    _add_column_if_missing(conn, "tasks", "parent_id", "TEXT REFERENCES tasks(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id)")

    # Discussions — persistent store for multi-agent discuss sessions.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discussions (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_discussions_task   ON discussions(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_discussions_status ON discussions(status)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS discussion_rounds (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_disc_rounds_disc ON discussion_rounds(discussion_id, round_number)")

    # F8: UNIQUE partial index on yaml_sync_queue prevents duplicate pending ops for the
    # same (op_type, entity id). NULL ids (for ops without an id field) are always distinct.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_yaml_sync_pending_dedup
        ON yaml_sync_queue(op_type, json_extract(payload, '$.id'))
        WHERE status = 'pending'
    """)


def _migration_v3(conn: sqlite3.Connection) -> None:
    """Add verified/verified_at/verified_by columns to tasks."""
    _add_column_if_missing(conn, "tasks", "verified", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "tasks", "verified_at", "TEXT")
    _add_column_if_missing(conn, "tasks", "verified_by", "TEXT")


def _migration_v4(conn: sqlite3.Connection) -> None:
    """Add missing lifecycle columns to tasks."""
    _add_column_if_missing(conn, "tasks", "updated_at", "TEXT")
    _add_column_if_missing(conn, "tasks", "failed_at", "TEXT")
    _add_column_if_missing(conn, "tasks", "stopped_at", "TEXT")
    _add_column_if_missing(conn, "tasks", "failed_reason", "TEXT")
    _add_column_if_missing(conn, "tasks", "pause_reason", "TEXT")
    _add_column_if_missing(conn, "tasks", "archived_at", "TEXT")
    _add_column_if_missing(conn, "tasks", "archived_reason", "TEXT")
    _add_column_if_missing(conn, "tasks", "model_tier", "TEXT")


def _migration_v5(conn: sqlite3.Connection) -> None:
    """Add deadline_minutes column to tasks table."""
    _add_column_if_missing(conn, "tasks", "deadline_minutes", "INTEGER")


def _migration_v6(conn: sqlite3.Connection) -> None:
    """Add FTS5 virtual table for full-text search over handoffs and ledger."""
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS handoffs_fts USING fts5(
            id, task_id, agent, summary, content,
            content=handoffs, content_rowid=rowid
        )
    """)


def _migration_v7(conn: sqlite3.Connection) -> None:
    """Add worktree_path column to tasks for dashboard worktree visibility."""
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN worktree_path TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists


def _migration_v8(conn: sqlite3.Connection) -> None:
    """Add recovery_count column to inbox so the auto-recover counter
    is no longer stored inside the failed_reason text (which gets wiped
    every time a new failure overwrites it)."""
    _add_column_if_missing(conn, "inbox", "recovery_count", "INTEGER NOT NULL DEFAULT 0")
    # Backfill from any pre-existing 'recovery_N:...' markers in failed_reason.
    import re as _re
    rows = conn.execute(
        "SELECT id, failed_reason FROM inbox WHERE failed_reason LIKE 'recovery_%'"
    ).fetchall()
    for row in rows:
        m = _re.match(r"recovery_(\d+)", row["failed_reason"] or "")
        if m:
            conn.execute(
                "UPDATE inbox SET recovery_count = ? WHERE id = ?",
                (int(m.group(1)), row["id"]),
            )


def _migration_v9(conn: sqlite3.Connection) -> None:
    """Add blocked_by_raw column to tasks for informational dependency
    references (test fixtures and pre-migration projects often list
    blocked_by IDs that don't exist as tasks; the strict FK on
    task_dependencies rejects those, so we keep a soft copy here)."""
    _add_column_if_missing(conn, "tasks", "blocked_by_raw", "TEXT")


def _migration_v10(conn: sqlite3.Connection) -> None:
    """Stamped per-task workflow/require_tdd. Column kept for backwards compat;
    autonomy is now profile-only (normalize_autonomy in engine/profile.py)."""
    _add_column_if_missing(conn, "tasks", "workflow", "TEXT")
    _add_column_if_missing(conn, "tasks", "autonomy", "TEXT")  # deprecated — no longer written
    _add_column_if_missing(conn, "tasks", "require_tdd", "INTEGER")


def _migration_v11(conn: sqlite3.Connection) -> None:
    """Generic JSON extras column for nested per-task metadata that
    doesn't deserve its own column: subtasks, classifier, decomposer,
    retry. The adapter payload merges this into each task dict so
    consumers (Morpheme, dashboard) see the structured blocks they
    expect without us forcing a strict schema for every nested shape."""
    _add_column_if_missing(conn, "tasks", "extras_json", "TEXT")


def _migration_v12(conn: sqlite3.Connection) -> None:
    """Contract lock: snapshot acceptance_criteria + tdd at plan_approved time.
    locked_contract stores a JSON snapshot; contract_locked_at is the timestamp.
    Once set, guarded fields (acceptance_criteria, tdd) are immutable."""
    _add_column_if_missing(conn, "tasks", "locked_contract", "TEXT")
    _add_column_if_missing(conn, "tasks", "contract_locked_at", "TEXT")


def _migration_v13(conn: sqlite3.Connection) -> None:
    """task_observations table: per-task observation snapshots, written at
    lifecycle transitions (e.g. report_ready) by future auto-capture or by
    explicit callers today. Storage-only in this iteration; no transition
    hook and no summarizer adapter."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_observations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT    NOT NULL,
            phase       TEXT    NOT NULL,
            summary     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_observations_task_id "
        "ON task_observations(task_id, created_at)"
    )


def _migration_v14(conn: sqlite3.Connection) -> None:
    """summarizer_calls table: per-call log used by the cross-process
    rate limiter and by future cost-tracking surfaces (shux insights).
    Captures provider, model, success, and optional token usage."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS summarizer_calls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            provider        TEXT    NOT NULL,
            model           TEXT,
            called_at       TEXT    NOT NULL,
            success         INTEGER NOT NULL,
            input_tokens    INTEGER,
            output_tokens   INTEGER
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_summarizer_calls_provider_called_at "
        "ON summarizer_calls(provider, called_at)"
    )


def _migration_v15(conn: sqlite3.Connection) -> None:
    """operator_commands table: one row per Telegram message processed by the
    gateway listener. idempotency_key enforces exactly-once execution."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_commands (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key  TEXT    NOT NULL UNIQUE,
            command          TEXT    NOT NULL,
            task_id          TEXT,
            sender_id        TEXT    NOT NULL,
            status           TEXT    NOT NULL DEFAULT 'pending',
            result           TEXT,
            created_at       TEXT    NOT NULL,
            executed_at      TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_operator_commands_task_id "
        "ON operator_commands(task_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_operator_commands_status "
        "ON operator_commands(status, created_at)"
    )


def _migration_v16(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "tasks", "estimated_minutes", "TEXT")


def _migration_v17(conn: sqlite3.Connection) -> None:
    """Add reason column to inbox for manually-paused items (skip_if_field support)."""
    _add_column_if_missing(conn, "inbox", "reason", "TEXT")


def _migration_v18(conn: sqlite3.Connection) -> None:
    """agent_heartbeats: per-agent liveness pings. Stale rows (>2 min) are
    flagged as zombie by the watcher reconciler."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_heartbeats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent       TEXT    NOT NULL,
            task_id     TEXT,
            status      TEXT    NOT NULL DEFAULT 'alive',
            pid         INTEGER,
            updated_at  TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_agent "
        "ON agent_heartbeats(agent, updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_task "
        "ON agent_heartbeats(task_id, updated_at DESC)"
    )


def _migration_v19(conn: sqlite3.Connection) -> None:
    """task_artifacts: files produced by agents, linked to tasks.
    Each row tracks path, type, hash, and the agent that produced it."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_artifacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT    NOT NULL,
            agent       TEXT,
            path        TEXT    NOT NULL,
            type        TEXT    NOT NULL DEFAULT 'file',
            hash        TEXT,
            size_bytes  INTEGER,
            created_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_artifacts_task "
        "ON task_artifacts(task_id, created_at DESC)"
    )


def _migration_v20(conn: sqlite3.Connection) -> None:
    """Add type column to inbox so discussion shadow entries can be
    distinguished from regular task dispatch entries."""
    _add_column_if_missing(conn, "inbox", "type", "TEXT NOT NULL DEFAULT 'task'")


def _migration_v21(conn: sqlite3.Connection) -> None:
    """project_meta: key/value store for contract-level metadata (id, goal)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_meta (
            key    TEXT PRIMARY KEY,
            value  TEXT
        )
        """
    )


def _migration_v22(conn: sqlite3.Connection) -> None:
    """profile_trials: A/B test table for behavioral profile changes (Iteration 6)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_trials (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_key            TEXT    NOT NULL,
            old_value              TEXT,
            new_value              TEXT,
            baseline_success_rate  REAL    NOT NULL,
            trial_started_at       TEXT    NOT NULL,
            task_count_target      INTEGER NOT NULL DEFAULT 5,
            trial_completed_at     TEXT,
            trial_success_rate     REAL,
            outcome                TEXT,
            reverted               INTEGER NOT NULL DEFAULT 0,
            reinforced             INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_profile_trials_outcome "
        "ON profile_trials(outcome, trial_started_at)"
    )


def _migration_v23(conn: sqlite3.Connection) -> None:
    """Drop the orphaned, misconfigured handoffs_fts table (created in v6).

    It was an external-content FTS5 table declaring columns (agent, summary)
    that do not exist in the handoffs table, was never populated or queried,
    and is dead code. See docs/ANALYSIS-sqlite-doctrine-drift.md.
    """
    conn.execute("DROP TABLE IF EXISTS handoffs_fts")


def _migration_v24(conn: sqlite3.Connection) -> None:
    """Drop the inert yaml_sync_queue table and its indexes.

    The table was created for a YAML→SQLite sync queue that was never
    implemented. It has been empty and unqueried since creation. Removing it
    cleans up dead schema from all project databases.
    """
    conn.execute("DROP TABLE IF EXISTS yaml_sync_queue")


def _migration_v25(conn: sqlite3.Connection) -> None:
    """SQLite SoT for agent liveness: heartbeat_contract, agent_status, agent_pulse.

    Three previously-YAML-only state systems now have SQLite as source of truth.
    YAML files become export mirrors for backwards compat and external tooling.

    - agent_heartbeats: extended with richer heartbeat_contract.AgentHeartbeat fields
      (runtime, active_task, next_wake_at, written_at, tokens_used/limit, cost_usd).
      Same table previously used by `shux heartbeat`; now also holds watcher's heartbeat
      and per-agent heartbeats written via heartbeat_contract.write_heartbeat.
    - agent_runtime_status: covers .superharness/agents/<runtime>.status.yaml.
    - agent_pulses: covers .superharness/agent-pulse.yaml.
    """
    # Extend agent_heartbeats with heartbeat_contract fields
    _add_column_if_missing(conn, "agent_heartbeats", "runtime", "TEXT")
    _add_column_if_missing(conn, "agent_heartbeats", "active_task", "TEXT")
    _add_column_if_missing(conn, "agent_heartbeats", "next_wake_at", "TEXT")
    _add_column_if_missing(conn, "agent_heartbeats", "written_at", "TEXT")
    _add_column_if_missing(conn, "agent_heartbeats", "tokens_used", "INTEGER")
    _add_column_if_missing(conn, "agent_heartbeats", "tokens_limit", "INTEGER")
    _add_column_if_missing(conn, "agent_heartbeats", "cost_usd", "REAL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runtime_status (
            runtime         TEXT    PRIMARY KEY,
            schema_version  TEXT    NOT NULL DEFAULT '1',
            liveness        TEXT    NOT NULL DEFAULT 'active',
            active_task     TEXT,
            next_wake_at    TEXT,
            budget_json     TEXT,
            updated_at      TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_pulses (
            agent       TEXT    PRIMARY KEY,
            task_id     TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'running',
            pid         INTEGER,
            message     TEXT,
            last_seen   TEXT    NOT NULL
        )
        """
    )


def _migration_v26(conn: sqlite3.Connection) -> None:
    """SQLite SoT for onboarding state (v8 bulletproof fix).

    onboarding.yaml previously lived only as YAML. Tracks per-step completion
    status ('pending' | 'completed') and config_version for wizard migrations.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_state (
            project_key      TEXT    PRIMARY KEY,
            version          INTEGER NOT NULL DEFAULT 1,
            config_version   INTEGER NOT NULL DEFAULT 1,
            steps_json       TEXT    NOT NULL,
            updated_at       TEXT    NOT NULL
        )
        """
    )


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_v1,
    _migration_v2,
    _migration_v3,
    _migration_v4,
    _migration_v5,
    _migration_v6,
    _migration_v7,
    _migration_v8,
    _migration_v9,
    _migration_v10,
    _migration_v11,
    _migration_v12,
    _migration_v13,
    _migration_v14,
    _migration_v15,
    _migration_v16,
    _migration_v17,
    _migration_v18,
    _migration_v19,
    _migration_v20,
    _migration_v21,
    _migration_v22,
    _migration_v23,
    _migration_v24,
    _migration_v25,
    _migration_v26,
]
