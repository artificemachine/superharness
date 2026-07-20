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

CURRENT_SCHEMA_VERSION = 34

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
        conn = sqlite3.connect(db_path, timeout=5.0)
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

    _heal_known_migration_drift(conn)


# Every (table, column, ddl_clause) ever added via _add_column_if_missing
# across all migrations. Drift can in principle affect any of these, not
# just the historically-observed agent_heartbeats/v25 case, since the root
# cause (_column_exists silently misreporting under row_factory=None) applied
# to every call site equally. Table CREATEs are excluded — those use
# `CREATE TABLE IF NOT EXISTS` directly and aren't vulnerable to this bug.
# (version, table, column, ddl_clause) — `version` is the migration that
# introduced the column, so heal only fires once user_version claims that
# migration (or later) already applied. Missing a column because its
# migration simply hasn't run yet is normal, not drift — gating on version
# is what distinguishes the two (see _heal_known_migration_drift).
_ADDITIVE_COLUMN_MANIFEST: tuple[tuple[int, str, str, str], ...] = (
    (2, "tasks", "parent_id", "TEXT REFERENCES tasks(id)"),
    (3, "tasks", "verified", "INTEGER NOT NULL DEFAULT 0"),
    (3, "tasks", "verified_at", "TEXT"),
    (3, "tasks", "verified_by", "TEXT"),
    (4, "tasks", "updated_at", "TEXT"),
    (4, "tasks", "failed_at", "TEXT"),
    (4, "tasks", "stopped_at", "TEXT"),
    (4, "tasks", "failed_reason", "TEXT"),
    (4, "tasks", "pause_reason", "TEXT"),
    (4, "tasks", "archived_at", "TEXT"),
    (4, "tasks", "archived_reason", "TEXT"),
    (4, "tasks", "model_tier", "TEXT"),
    (5, "tasks", "deadline_minutes", "INTEGER"),
    (8, "inbox", "recovery_count", "INTEGER NOT NULL DEFAULT 0"),
    (9, "tasks", "blocked_by_raw", "TEXT"),
    (10, "tasks", "workflow", "TEXT"),
    (10, "tasks", "autonomy", "TEXT"),
    (10, "tasks", "require_tdd", "INTEGER"),
    (11, "tasks", "extras_json", "TEXT"),
    (12, "tasks", "locked_contract", "TEXT"),
    (12, "tasks", "contract_locked_at", "TEXT"),
    (16, "tasks", "estimated_minutes", "TEXT"),
    (17, "inbox", "reason", "TEXT"),
    (20, "inbox", "type", "TEXT NOT NULL DEFAULT 'task'"),
    (25, "agent_heartbeats", "runtime", "TEXT"),
    (25, "agent_heartbeats", "active_task", "TEXT"),
    (25, "agent_heartbeats", "next_wake_at", "TEXT"),
    (25, "agent_heartbeats", "written_at", "TEXT"),
    (25, "agent_heartbeats", "tokens_used", "INTEGER"),
    (25, "agent_heartbeats", "tokens_limit", "INTEGER"),
    (25, "agent_heartbeats", "cost_usd", "REAL"),
    (27, "discussions", "max_rounds", "INTEGER NOT NULL DEFAULT 3"),
    (30, "tasks", "issue_url", "TEXT"),
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _heal_known_migration_drift(conn: sqlite3.Connection) -> None:
    """Repair DBs where user_version/schema_migrations claim a migration ran
    but its DDL never actually landed.

    Real, observed failure mode (not hypothetical): before _column_exists was
    fixed to handle row_factory=None (see its docstring), a migration could
    ALTER TABLE against a column-existence check that silently returned the
    wrong answer, skip the ALTER, and still record the migration as applied
    and bump user_version — permanently, since a later init_db() only reruns
    migrations with version > the recorded one. A DB migrated through that
    window is stuck claiming e.g. v25 applied while agent_heartbeats is
    missing every column v25 was supposed to add.

    Driven by _ADDITIVE_COLUMN_MANIFEST (every _add_column_if_missing call
    site across all migrations), not hardcoded to the one historically
    observed table — the same bug could have skipped any of them. Gated on
    user_version >= the manifest entry's version: a column missing because
    its migration simply hasn't run yet is normal progress, not drift — only
    a column missing *despite* user_version already claiming that migration
    applied is the actual bug this repairs. Cheap (one PRAGMA table_info per
    distinct table) and safe to run on every init_db() call: re-invokes only
    already-idempotent DDL, never touches schema_migrations or user_version,
    and no-ops once healed.
    """
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    healed = False
    for version, table, column, ddl_clause in _ADDITIVE_COLUMN_MANIFEST:
        if user_version < version:
            continue  # migration hasn't run yet — missing column is expected, not drift
        if not _table_exists(conn, table):
            continue  # table itself predates this DB's schema — nothing to heal yet
        if _column_exists(conn, table, column):
            continue
        logger.warning(
            "Healing migration drift: %s missing column %r despite user_version=%d claiming v%d applied",
            table, column, user_version, version,
        )
        _add_column_if_missing(conn, table, column, ddl_clause)
        healed = True
    if healed:
        conn.commit()

def _run_migrations(conn: sqlite3.Connection, current_version: int, project_dir: str | None = None) -> None:
    """Apply pending migrations in order."""
    for v in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        _run_single_migration(conn, v, project_dir)

# Migrations that rebuild a table referenced by other tables' foreign keys
# (DROP TABLE fails under foreign_keys=ON if other rows reference it, even
# though no data actually violates anything — verified empirically). PRAGMA
# foreign_keys is also a no-op when toggled mid-transaction, so it must be
# flipped here, before the SAVEPOINT below opens one, not inside the
# migration function itself.
_MIGRATIONS_REQUIRING_FK_OFF: dict[int, tuple[str, ...]] = {
    # version -> tables the migration rebuilds, and therefore the tables whose
    # FK integrity it is responsible for verifying afterwards. Scoped per-table
    # deliberately: a bare `PRAGMA foreign_key_check` walks the WHOLE database
    # and fails on any unrelated pre-existing defect elsewhere (verified: a
    # hand-rolled test fixture whose `discussions` table lacks the PK that
    # `discussion_rounds` references raises "foreign key mismatch" — a schema
    # error in a table this migration never touches). A migration must answer
    # for what it changed, not assert the entire DB is pristine.
    33: ("tasks", "failures", "decisions", "ledger"),
}


def _run_single_migration(conn: sqlite3.Connection, v: int, project_dir: str | None = None) -> None:
    """Run a single schema migration with backup and rollback."""
    if project_dir:
        _backup_db(project_dir, v - 1)

    needs_fk_off = v in _MIGRATIONS_REQUIRING_FK_OFF
    prior_fk_state = None
    if needs_fk_off:
        # Restore whatever this connection's FK enforcement was before, not
        # force it ON — some callers (chaos/test harnesses) intentionally
        # run with foreign_keys=OFF (SQLite's own default) and never touch
        # this pragma themselves.
        prior_fk_state = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.execute("PRAGMA foreign_keys=OFF")

    try:
        with transaction(conn):
            conn.execute(f"SAVEPOINT migrate_v{v}")
            try:
                migration_fn = _MIGRATIONS[v - 1]
                migration_fn(conn)
                # Verify BEFORE releasing the savepoint. Running this after the
                # enclosing transaction commits (the original bug) meant a
                # violation was detected but could not be undone — user_version
                # had already advanced, leaving the DB migrated, constraint-
                # bearing, and violating: exactly the state this guard exists
                # to prevent.
                if needs_fk_off:
                    violations = []
                    for tbl in _MIGRATIONS_REQUIRING_FK_OFF[v]:
                        if not _table_exists(conn, tbl):
                            continue
                        violations.extend(
                            conn.execute(f"PRAGMA foreign_key_check({tbl})").fetchall()
                        )
                    if violations:
                        raise SchemaError(
                            f"Migration v{v} left {len(violations)} foreign key "
                            f"violation(s): {[tuple(r) for r in violations]}"
                        )
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
    finally:
        if needs_fk_off:
            conn.execute(f"PRAGMA foreign_keys={'ON' if prior_fk_state else 'OFF'}")


def _rebuild_table_with_new_ddl(
    conn: sqlite3.Connection,
    table: str,
    create_sql_template: str,
    columns: list[str],
    indexes: list[str],
    column_fallbacks: dict[str, str] | None = None,
    null_orphans: dict[str, str] | None = None,
) -> None:
    """Rebuild `table` under new DDL (e.g. an added/changed FK constraint),
    preserving all rows.

    SQLite cannot ALTER a column's FOREIGN KEY in place — this is the
    documented workaround: create a new table, copy data across an explicit
    column list, drop the old table, rename the new one into place, then
    recreate indexes (dropped along with the old table). `create_sql_template`
    must contain a `{tmp}` placeholder for the temporary table name.

    `columns` may list columns the *source* table doesn't actually have yet:
    a column that's part of a migration's original CREATE TABLE (as opposed
    to one backfilled later via _add_column_if_missing) never gets added to
    a hand-rolled/legacy table that predates it, because CREATE TABLE IF NOT
    EXISTS no-ops against an existing table (verified: a test fixture that
    hand-creates a minimal `tasks` table missing e.g. development_method hits
    exactly this). Columns present on the source are copied as-is; columns
    absent from the source fall back to the new table's own DEFAULT/NULL,
    *unless* `column_fallbacks` supplies a SQL expression for that column
    (needed for NOT NULL columns with no DEFAULT — e.g. tasks.title — where
    a legacy source table is missing the column entirely; verified against a
    test fixture with only `id, status` in its hand-rolled tasks table).

    If the source table doesn't exist at all (a test fixture can claim
    user_version=N without replicating every table an earlier migration
    would have created — verified: failures/decisions/ledger genuinely
    absent despite user_version=7), there's nothing to migrate — just
    promote the freshly-created tmp table into place.

    `null_orphans` maps a column to the table it now references. Any source
    row whose value in that column doesn't exist in the referenced table is
    copied with the column set to NULL. Adding an FK to a table that already
    holds dangling references would otherwise install a constraint the
    existing data immediately violates — and since a rebuild runs with
    foreign_keys=OFF, SQLite accepts the bad rows silently. NULLing them is
    the same outcome ON DELETE SET NULL would have produced had the
    constraint existed when the referenced row disappeared.
    """
    tmp = f"{table}__rebuild_tmp"
    column_fallbacks = column_fallbacks or {}
    null_orphans = null_orphans or {}
    conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    conn.execute(create_sql_template.format(tmp=tmp))
    if not _table_exists(conn, table):
        conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
        for stmt in indexes:
            conn.execute(stmt)
        return
    existing = {r["name"] if hasattr(r, "keys") else r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    insert_cols, select_exprs = [], []
    for c in columns:
        if c in existing:
            insert_cols.append(c)
            if c in null_orphans:
                ref = null_orphans[c]
                # NULL any value with no matching row in the referenced table.
                select_exprs.append(
                    f"CASE WHEN {c} IS NOT NULL "
                    f"AND {c} NOT IN (SELECT id FROM {ref}) THEN NULL ELSE {c} END"
                )
            else:
                select_exprs.append(c)
        elif c in column_fallbacks:
            insert_cols.append(c)
            select_exprs.append(column_fallbacks[c])
        # else: omit entirely — let the new table's own DEFAULT/NULL apply.
    insert_col_list = ", ".join(insert_cols)
    select_expr_list = ", ".join(select_exprs)
    conn.execute(f"INSERT INTO {tmp} ({insert_col_list}) SELECT {select_expr_list} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
    for stmt in indexes:
        conn.execute(stmt)

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_heartbeat ON inbox(status, last_heartbeat)")
    # Prevent duplicate dispatch: only one active item per (task_id, target_agent).
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_unique_task_agent
        ON inbox(task_id, target_agent)
        WHERE status NOT IN ('failed', 'done', 'cancelled')
    """)

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_task           ON failures(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_agent_pattern  ON failures(agent, pattern)")

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


def _migration_v27(conn: sqlite3.Connection) -> None:
    """Add max_rounds to discussions so --max-rounds is persisted and honored."""
    # Guard: discussions was created in v2, but hand-crafted test DBs seeded at
    # an intermediate schema version may not have run the full chain from v0.
    has_discussions = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='discussions'"
    ).fetchone()
    if has_discussions:
        _add_column_if_missing(conn, "discussions", "max_rounds", "INTEGER NOT NULL DEFAULT 3")


def _migration_v28(conn: sqlite3.Connection) -> None:
    """task_usage table: per-task token/cost accounting, sourced from the
    Claude Code SDK dispatch path (source='sdk') and self-reported handoff
    payloads (source='handoff') for agents with no programmatic usage data."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_usage (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id       TEXT    NOT NULL,
            agent         TEXT    NOT NULL,
            source        TEXT    NOT NULL DEFAULT 'manual',
            model         TEXT,
            input_tokens  INTEGER,
            output_tokens INTEGER,
            cost_usd      REAL,
            recorded_at   TEXT    NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_usage_task_id ON task_usage(task_id)")


def _migration_v29(conn: sqlite3.Connection) -> None:
    """watcher_cooldowns: persisted last-run timestamps for _should_run()
    in inbox_watch.py. Previously an in-memory dict keyed by action name,
    using time.monotonic() — meaningless across process boundaries. The
    watcher is by design a fresh Python process every tick (one-shot,
    respawned by the operator), so any in-memory cooldown state is empty on
    every call and every gate silently no-ops on every tick regardless of
    the cooldown argument passed in. Confirmed live 2026-07-11: reinforce's
    claimed 300s cooldown fired on every ~5-7s tick instead, driving a full
    181 MB trace.jsonl re-parse per tick. One row per action, last write
    wins."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watcher_cooldowns (
            action          TEXT    PRIMARY KEY,
            last_run_epoch  REAL    NOT NULL
        )
        """
    )


def _migration_v30(conn: sqlite3.Connection) -> None:
    """Add issue_url column to tasks: stores a linked GitHub/GitLab issue URL
    (one-way snapshot pointer, set via `shux task create --issue` or
    `shux task link`; never written back to by shux)."""
    _add_column_if_missing(conn, "tasks", "issue_url", "TEXT")


def _migration_v31(conn: sqlite3.Connection) -> None:
    """Typed telemetry events table (engine/events.py): task transitions and
    dispatch lifecycle events, written by a background emitter. Additive and
    distinct from the free-form JSONL stream in engine/event_stream.py."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           TEXT    NOT NULL,
            kind         TEXT    NOT NULL,
            task_id      TEXT,
            payload_json TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind_ts ON events(kind, ts)")


def _migration_v32(conn: sqlite3.Connection) -> None:
    """Byte-offset cursor per dispatch for transcript tailing
    (engine/transcript_tail.py). Feature-flagged off by default; see
    docs/PLAN-steal-omnigent.md iteration 7."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_cursors (
            dispatch_id  TEXT    PRIMARY KEY,
            path         TEXT,
            byte_offset  INTEGER NOT NULL DEFAULT 0,
            updated_at   TEXT
        )
    """)


def _migration_v33(conn: sqlite3.Connection) -> None:
    """FK integrity hardening.

    tasks.parent_id has referenced tasks(id) since v2 with no ON DELETE
    clause, so with foreign_keys=ON (set on every connection) SQLite's
    default action (NO ACTION) blocks deleting a parent task that still has
    subtasks — `shux task delete` (commands/task.py) does not catch this and
    crashes with IntegrityError. failures/decisions/ledger.task_id have no FK
    at all, so deleting a task instead leaves those audit tables with a
    dangling task_id (no crash, silent data debt).

    Rebuilds all four tables (see _rebuild_table_with_new_ddl) adding
    FOREIGN KEY(...) REFERENCES tasks(id) ON DELETE SET NULL — a task delete
    now orphans/nulls out the references instead of blocking or leaving them
    dangling. See _MIGRATIONS_REQUIRING_FK_OFF for why rebuilding `tasks`
    itself needs foreign_keys toggled off around the whole migration.
    """
    _rebuild_table_with_new_ddl(
        conn, "tasks",
        create_sql_template="""
            CREATE TABLE {tmp} (
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
                cancelled_at         TEXT,
                parent_id            TEXT,
                verified             INTEGER NOT NULL DEFAULT 0,
                verified_at          TEXT,
                verified_by          TEXT,
                updated_at           TEXT,
                failed_at            TEXT,
                stopped_at           TEXT,
                failed_reason        TEXT,
                pause_reason         TEXT,
                archived_at          TEXT,
                archived_reason      TEXT,
                model_tier           TEXT,
                deadline_minutes     INTEGER,
                worktree_path        TEXT,
                blocked_by_raw       TEXT,
                workflow             TEXT,
                autonomy             TEXT,
                require_tdd          INTEGER,
                extras_json          TEXT,
                locked_contract      TEXT,
                contract_locked_at   TEXT,
                estimated_minutes    TEXT,
                issue_url            TEXT,
                FOREIGN KEY (parent_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """,
        columns=[
            "id", "title", "owner", "status", "effort", "project_path", "development_method",
            "acceptance_criteria", "test_types", "out_of_scope", "definition_of_done", "context", "tdd",
            "version", "created_at", "plan_proposed_at", "plan_approved_at", "in_progress_at",
            "report_ready_at", "review_requested_at", "done_at", "cancelled_at", "parent_id",
            "verified", "verified_at", "verified_by", "updated_at", "failed_at", "stopped_at",
            "failed_reason", "pause_reason", "archived_at", "archived_reason", "model_tier",
            "deadline_minutes", "worktree_path", "blocked_by_raw", "workflow", "autonomy",
            "require_tdd", "extras_json", "locked_contract", "contract_locked_at",
            "estimated_minutes", "issue_url",
        ],
        indexes=[
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_owner  ON tasks(owner)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id)",
        ],
        # title/created_at are NOT NULL with no DEFAULT; a legacy hand-rolled
        # tasks table missing the columns entirely (e.g. only id/status)
        # would otherwise violate NOT NULL on rebuild.
        column_fallbacks={"title": "id", "created_at": "'1970-01-01T00:00:00Z'"},
        # A subtask whose parent was deleted before this FK existed keeps a
        # parent_id pointing at nothing — NULL it, matching ON DELETE SET NULL.
        null_orphans={"parent_id": "tasks"},
    )

    _rebuild_table_with_new_ddl(
        conn, "failures",
        create_sql_template="""
            CREATE TABLE {tmp} (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id        TEXT,
                agent          TEXT,
                pattern        TEXT,
                error_snippet  TEXT,
                created_at     TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """,
        columns=["id", "task_id", "agent", "pattern", "error_snippet", "created_at"],
        indexes=[
            "CREATE INDEX IF NOT EXISTS idx_failures_task           ON failures(task_id)",
            "CREATE INDEX IF NOT EXISTS idx_failures_agent_pattern  ON failures(agent, pattern)",
        ],
        null_orphans={"task_id": "tasks"},
    )

    _rebuild_table_with_new_ddl(
        conn, "decisions",
        create_sql_template="""
            CREATE TABLE {tmp} (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent         TEXT,
                task_id       TEXT,
                decision      TEXT    NOT NULL,
                reason        TEXT,
                alternatives  TEXT,
                created_at    TEXT    NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """,
        columns=["id", "agent", "task_id", "decision", "reason", "alternatives", "created_at"],
        indexes=[
            "CREATE INDEX IF NOT EXISTS idx_decisions_agent_time ON decisions(agent, created_at)",
        ],
        null_orphans={"task_id": "tasks"},
    )

    _rebuild_table_with_new_ddl(
        conn, "ledger",
        create_sql_template="""
            CREATE TABLE {tmp} (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     TEXT,
                agent       TEXT,
                action      TEXT NOT NULL,
                details     TEXT,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """,
        columns=["id", "task_id", "agent", "action", "details", "created_at"],
        indexes=[
            "CREATE INDEX IF NOT EXISTS idx_ledger_time ON ledger(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_ledger_task ON ledger(task_id, created_at)",
        ],
        null_orphans={"task_id": "tasks"},
    )


def _migration_v34(conn: sqlite3.Connection) -> None:
    """Repair DBs that applied the original v33.

    The first cut of v33 added the FK constraints but copied dangling task_id /
    parent_id values verbatim, so a DB that already held orphaned audit rows
    came out of the migration permanently violating its own new constraints
    (observed live: 3 ledger rows referencing a task deleted months earlier).
    v33 has since been fixed to NULL orphans during the rebuild, but a DB that
    already recorded v33 as applied never re-runs it — hence this migration.

    Idempotent and cheap on a clean DB: four correlated NOT IN scans that
    update nothing when there are no orphans.
    """
    for table, column in (
        ("tasks", "parent_id"),
        ("failures", "task_id"),
        ("decisions", "task_id"),
        ("ledger", "task_id"),
    ):
        if not _table_exists(conn, table) or not _column_exists(conn, table, column):
            continue
        cur = conn.execute(
            f"UPDATE {table} SET {column} = NULL "
            f"WHERE {column} IS NOT NULL AND {column} NOT IN (SELECT id FROM tasks)"
        )
        if cur.rowcount:
            logger.warning(
                "Repaired %d orphaned %s.%s reference(s) left by the original v33",
                cur.rowcount, table, column,
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
    _migration_v27,
    _migration_v28,
    _migration_v29,
    _migration_v30,
    _migration_v31,
    _migration_v32,
    _migration_v33,
    _migration_v34,
]
