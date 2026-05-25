"""Performance benchmarks — verify system stays fast under load."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest


def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    return conn


class TestInboxQueryPerformance:
    """Inbox queries should stay fast even with many rows."""

    def test_query_1000_rows_under_100ms(self, tmp_path):
        conn = _setup_db(tmp_path)
        # Seed 1000 inbox rows
        for i in range(1000):
            conn.execute(
                "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, created_at) "
                "VALUES (?, ?, ?, ?, 0, 3, datetime('now'))",
                (f"perf-{i}", f"task-{i%10}", "claude-code", "done"),
            )
        conn.commit()

        start = time.perf_counter()
        rows = conn.execute("SELECT * FROM inbox WHERE status='done' LIMIT 50").fetchall()
        elapsed = (time.perf_counter() - start) * 1000
        assert len(rows) == 50
        assert elapsed < 100, f"Inbox query took {elapsed:.1f}ms (limit: 100ms)"
        conn.close()

    def test_status_count_fast(self, tmp_path):
        conn = _setup_db(tmp_path)
        for i in range(500):
            conn.execute(
                "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, created_at) "
                "VALUES (?, ?, 'claude-code', ?, 0, 3, datetime('now'))",
                (f"cnt-{i}", f"task-{i%5}", "done" if i % 3 != 0 else "failed"),
            )
        conn.commit()

        start = time.perf_counter()
        result = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM inbox GROUP BY status"
        ).fetchall()
        elapsed = (time.perf_counter() - start) * 1000
        assert len(result) >= 2
        assert elapsed < 50, f"Status count took {elapsed:.1f}ms (limit: 50ms)"
        conn.close()
