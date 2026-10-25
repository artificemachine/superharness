"""BUG-2026-10-23, second defect: `shux state-gc` was blind and not read-only.

Production state databases run in WAL mode and carry the lazily created
`operator_memory` table. The inventory must classify such a database, and it
must not create `-wal`/`-shm` sidecars while doing it.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from superharness.commands.state_gc import CANDIDATE, KEPT, build_inventory
from superharness.engine import operator_memory
from superharness.engine.db import init_db

DAY = 86400
OLD = 90 * DAY
HASH = "a1b2c3d4e5f6"


def _make_dir(root: Path, *, wal: bool, with_operator_memory: bool) -> Path:
    directory = root / HASH
    directory.mkdir(parents=True)
    conn = sqlite3.connect(directory / "state.db")
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        init_db(conn)
        if with_operator_memory:
            conn.execute(operator_memory._CREATE_TABLE_SQL)
        conn.commit()
        if wal:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    if wal:
        # A cleanly closed production database leaves its header in WAL mode but
        # no sidecar files; remove what the fixture's own connections left.
        for suffix in ("-wal", "-shm"):
            (directory / f"state.db{suffix}").unlink(missing_ok=True)
    when = time.time() - OLD
    for entry in [directory, *directory.rglob("*")]:
        os.utime(entry, (when, when))
    return directory


def _verdict(root: Path) -> dict:
    summary = build_inventory(root, older_than_days=30, now=time.time())
    return next(e for e in summary["entries"] if e["path"] == HASH)


def test_empty_operator_memory_table_does_not_hide_a_skeleton(tmp_path):
    root = tmp_path / "state"
    _make_dir(root, wal=False, with_operator_memory=True)

    assert _verdict(root)["bucket"] == CANDIDATE


def test_populated_operator_memory_table_is_kept(tmp_path):
    root = tmp_path / "state"
    directory = _make_dir(root, wal=False, with_operator_memory=True)
    conn = sqlite3.connect(directory / "state.db")
    try:
        conn.execute(
            "INSERT INTO operator_memory (pattern_signature, resolution, created_at, last_used_at)"
            " VALUES ('x', 'x', 'x', 'x')"
        )
        conn.commit()
    finally:
        conn.close()

    verdict = _verdict(root)

    assert verdict["bucket"] == KEPT
    assert verdict["reason"] == "holds rows (state.db)"


def test_inventory_reads_a_wal_database_without_creating_sidecars(tmp_path):
    """A read-only open of a WAL database creates -wal/-shm on newer SQLite and
    fails to open at all on older SQLite; an immutable open does neither."""
    root = tmp_path / "state"
    directory = _make_dir(root, wal=True, with_operator_memory=False)
    before = sorted(entry.name for entry in directory.iterdir())
    assert "state.db-shm" not in before and "state.db-wal" not in before

    verdict = _verdict(root)

    assert sorted(entry.name for entry in directory.iterdir()) == before
    assert verdict["bucket"] == CANDIDATE
