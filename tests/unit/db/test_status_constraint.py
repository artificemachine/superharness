"""Iteration 6 — constrain tasks.status to the lifecycle vocabulary.

Before migration v35, `tasks.status` was a bare TEXT column across all 27
tables in the schema (the only CHECK constraint anywhere was elsewhere) — a
typo'd status like "plan_aproved" was silently accepted and the task became
invisible-stuck: no code path expects it, so it never surfaces on the board
or in `shux contract` again.
"""
from __future__ import annotations

import sqlite3

import pytest

from superharness.engine import db as db_mod
from superharness.engine.next_action import ALL_STATUSES
from superharness.engine.state_errors import SchemaError


def test_invalid_status_is_rejected(db_conn):
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) "
            "VALUES ('t-bad', 't-bad', 'plan_aproved', 1, '2026-01-01T00:00:00Z')"
        )


def test_every_valid_status_is_accepted(db_conn):
    for i, status in enumerate(ALL_STATUSES):
        db_conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) "
            "VALUES (?, ?, ?, 1, '2026-01-01T00:00:00Z')",
            (f"t-{i}", f"t-{i}", status),
        )
    db_conn.commit()
    count = db_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count == len(ALL_STATUSES)


def _build_v34_db_with_rows(tmp_path, statuses: list[str]) -> str:
    """Build a database pinned at v34 (pre-CHECK-constraint) and insert one
    task row per status given, including values outside ALL_STATUSES."""
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    db_path = str(project / ".superharness" / "state.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    original = db_mod.CURRENT_SCHEMA_VERSION
    try:
        db_mod.CURRENT_SCHEMA_VERSION = 34
        db_mod.init_db(conn, project_dir=str(project))
    finally:
        db_mod.CURRENT_SCHEMA_VERSION = original

    for i, status in enumerate(statuses):
        conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) "
            "VALUES (?, ?, ?, 1, '2026-01-01T00:00:00Z')",
            (f"row-{i}", f"row-{i}", status),
        )
    conn.commit()
    conn.close()
    return db_path


def test_migration_preserves_existing_rows(tmp_path):
    statuses = ["todo", "in_progress", "done", "failed", "review_requested"]
    db_path = _build_v34_db_with_rows(tmp_path, statuses)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    before_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    before_statuses = sorted(r["status"] for r in conn.execute("SELECT status FROM tasks"))

    db_mod.init_db(conn, project_dir=str(tmp_path / "proj"))  # 34 -> 35

    after_version = conn.execute("PRAGMA user_version").fetchone()[0]
    after_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    after_statuses = sorted(r["status"] for r in conn.execute("SELECT status FROM tasks"))
    conn.close()

    assert after_version == 35
    assert after_count == before_count == len(statuses)
    assert after_statuses == before_statuses


def test_migration_reports_unknown_status_before_failing(tmp_path):
    statuses = ["todo", "plan_aproved", "in_progress"]  # middle one is a typo
    db_path = _build_v34_db_with_rows(tmp_path, statuses)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    with pytest.raises(SchemaError) as excinfo:
        db_mod.init_db(conn, project_dir=str(tmp_path / "proj"))  # 34 -> 35

    assert "plan_aproved" in str(excinfo.value)

    # The failure must be diagnosable, not opaque — and must not have left the
    # DB half-migrated (still at 34, still holding all rows).
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    assert version == 34
    assert count == len(statuses)
