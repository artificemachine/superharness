"""Keystone test for the SQLite source-of-truth refactor.

Before this work, no writer persisted handoffs to the `handoffs` table — they
were YAML-only, so the table was always empty (and `get_handoffs` was broken,
always returning []). These tests pin the fix: writing a handoff now lands a
row in SQLite, and it is readable through the DAO and state_reader.
"""
from __future__ import annotations

from pathlib import Path


def _seed_task(project: Path, task_id: str) -> None:
    """Insert a minimal task so the handoffs FK (task_id -> tasks.id) passes."""
    from superharness.engine.db import managed_connection, now_iso
    with managed_connection(str(project)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, status, created_at) "
            "VALUES (?, ?, 'todo', ?)",
            (task_id, task_id, now_iso()),
        )


def test_upsert_handoff_persists_to_sqlite(clean_harness: Path) -> None:
    from superharness.engine import state_writer, handoffs_dao
    from superharness.engine.db import get_connection, init_db

    _seed_task(clean_harness, "t-keystone")
    ok = state_writer.upsert_handoff(
        str(clean_harness),
        "t-keystone-to-owner",
        {
            "task": "t-keystone",
            "from": "claude-code",
            "to": "owner",
            "status": "done",
            "summary": "verify handoff lands in sqlite",
        },
    )
    assert ok

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        rows = handoffs_dao.get_all(conn)
    finally:
        conn.close()

    assert any(r.task_id == "t-keystone" for r in rows), \
        "handoff written via upsert_handoff must appear in the SQLite handoffs table"


def test_get_handoffs_reads_written_handoff(clean_harness: Path) -> None:
    """state_reader.get_handoffs (previously always returned []) now sees it."""
    from superharness.engine import state_writer, state_reader

    _seed_task(clean_harness, "t-read")
    state_writer.upsert_handoff(
        str(clean_harness),
        "t-read-to-owner",
        {"task": "t-read", "from": "claude-code", "to": "owner",
         "status": "done", "summary": "readable via state_reader"},
    )

    handoffs = state_reader.get_handoffs(str(clean_harness), task_id="t-read")
    assert handoffs, "get_handoffs must return the persisted handoff (was broken before)"
    assert handoffs[0]["task_id"] == "t-read"


def test_handoff_search_finds_content(clean_harness: Path) -> None:
    from superharness.engine import state_writer, handoffs_dao
    from superharness.engine.db import get_connection, init_db

    _seed_task(clean_harness, "t-search")
    state_writer.upsert_handoff(
        str(clean_harness),
        "t-search-to-owner",
        {"task": "t-search", "from": "claude-code", "to": "owner",
         "status": "done", "summary": "UNIQUE_TOKEN_xyz in the body"},
    )

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        hits = handoffs_dao.search(conn, "UNIQUE_TOKEN_xyz")
    finally:
        conn.close()

    assert hits and hits[0].task_id == "t-search"


def test_backfill_imports_yaml_and_is_idempotent(clean_harness: Path) -> None:
    import yaml
    from superharness.engine import state_writer, handoffs_dao
    from superharness.engine.db import get_connection, init_db

    _seed_task(clean_harness, "t-old")
    # Simulate a pre-existing YAML handoff (orphan task also present to test skip)
    hdir = clean_harness / ".superharness" / "handoffs"
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / "t-old-report-2026-01-01-claude-code.yaml").write_text(yaml.safe_dump(
        {"task": "t-old", "phase": "report", "from": "claude-code", "to": "owner",
         "status": "report_ready", "date": "2026-01-01T00:00:00Z", "outcome": "legacy"}
    ))
    (hdir / "t-ghost-report-2026-01-01-x.yaml").write_text(yaml.safe_dump(
        {"task": "t-ghost", "phase": "report", "date": "2026-01-01T00:00:00Z"}
    ))

    first = state_writer.backfill_handoffs_from_yaml(str(clean_harness))
    assert first["added"] == 1, first
    assert first["skipped_orphan"] == 1, first  # t-ghost task doesn't exist

    second = state_writer.backfill_handoffs_from_yaml(str(clean_harness))
    assert second["added"] == 0 and second["skipped_dup"] == 1, second  # idempotent

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        rows = handoffs_dao.get_history(conn, "t-old")
    finally:
        conn.close()
    assert len(rows) == 1
