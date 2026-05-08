"""Fix A — recovery_count is stored in its own column and survives
failed_reason overwrites. Without this, repeated failures wiped the
counter and the watcher re-routed forever, growing max_retries
unbounded (we observed max_retries=65 in production)."""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao


def _setup(tmp_path):
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn, str(project))
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at) "
        "VALUES ('t1', 't', 'claude-code', 'in_progress', "
        "'2026-05-08T00:00:00Z', '2026-05-08T00:00:00Z')"
    )
    conn.commit()
    return project, conn


def test_inbox_has_recovery_count_column(tmp_path):
    """Migration v8 added the column with default 0."""
    project, conn = _setup(tmp_path)
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(inbox)")]
        assert "recovery_count" in cols

        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, created_at) "
            "VALUES ('i1', 't1', 'claude-code', 'pending', '2026-05-08T00:00:00Z')"
        )
        conn.commit()
        row = inbox_dao.get(conn, "i1")
        assert row.recovery_count == 0
    finally:
        conn.close()


def test_recovery_count_survives_failed_reason_overwrite(tmp_path):
    """The original bug: recovery counter was parsed from failed_reason,
    so any new failure that wrote to failed_reason wiped the counter."""
    project, conn = _setup(tmp_path)
    try:
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, "
            "recovery_count, failed_reason, created_at) "
            "VALUES ('i1', 't1', 'gemini-cli', 'failed', 5, "
            "'unknown: unclassified failure (exit code 1)', "
            "'2026-05-08T00:00:00Z')"
        )
        conn.commit()

        row = inbox_dao.get(conn, "i1")
        assert row.recovery_count == 5  # not parsed from failed_reason
        assert "recovery_" not in (row.failed_reason or "")
    finally:
        conn.close()


def test_migration_backfills_recovery_count_from_legacy_reason(tmp_path):
    """If the database had legacy 'recovery_N:agentA_to_agentB' markers
    in failed_reason at migration time, the counter is preserved."""
    import os
    from superharness.engine.db import get_connection, init_db
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)

    # Build a v7 database manually (no recovery_count column) and seed
    # a row with a legacy recovery_4 marker in failed_reason.
    db_path = str(project / ".superharness" / "state.sqlite3")
    import sqlite3
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    raw.executescript(
        """
        CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT);
        INSERT INTO tasks (id, status) VALUES ('t1', 'in_progress');
        CREATE TABLE inbox (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            target_agent TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 2,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            pid INTEGER,
            project_path TEXT,
            plan_only INTEGER NOT NULL DEFAULT 0,
            failed_reason TEXT,
            created_at TEXT NOT NULL,
            launched_at TEXT,
            last_heartbeat TEXT,
            paused_at TEXT,
            failed_at TEXT,
            done_at TEXT
        );
        INSERT INTO inbox (id, task_id, target_agent, status, failed_reason, created_at)
        VALUES ('i1', 't1', 'gemini-cli', 'failed',
                'recovery_4:claude-code_to_gemini-cli',
                '2026-05-08T00:00:00Z');
        PRAGMA user_version = 7;
        """
    )
    raw.commit()
    raw.close()

    conn = get_connection(str(project))
    init_db(conn, str(project))  # runs migrations to v8
    try:
        backfilled = conn.execute(
            "SELECT recovery_count FROM inbox WHERE id='i1'"
        ).fetchone()["recovery_count"]
        assert backfilled == 4
    finally:
        conn.close()
