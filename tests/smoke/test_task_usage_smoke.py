"""Smoke test for the task_usage table introduced for per-task cost accounting."""
from __future__ import annotations

from superharness.engine.db import get_connection, init_db


def test_task_usage_table_exists_after_init(tmp_path):
    (tmp_path / ".superharness").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(task_usage)").fetchall()}
    conn.close()

    expected = {
        "id", "task_id", "agent", "source", "model",
        "input_tokens", "output_tokens", "cost_usd", "recorded_at",
    }
    assert expected <= columns
