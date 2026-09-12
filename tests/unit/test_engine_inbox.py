from __future__ import annotations
import pytest

import json
from pathlib import Path

from tests.helpers import run_cmd


INBOX_HEADER = (
    "# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n"
)


def _inbox_file(tmp_path: Path, items_yaml: str = "") -> Path:
    f = tmp_path / "inbox.yaml"
    f.write_text(INBOX_HEADER + items_yaml)
    return f


def _run_inbox(repo_root: Path, cmd: str, args: list[str]) -> object:
    import sys

    return run_cmd(
        [sys.executable, "-m", "superharness.engine.inbox", cmd] + args,
        cwd=repo_root,
    )






















































# ── Iter 8 RED: dispatch failures must be logged ──────────────────────────────


def test_dispatch_nonzero_rc_logged():
    """inbox_dispatch must configure file logging so dispatch failures are captured."""
    import inspect
    from superharness.commands import inbox_dispatch as m

    src = inspect.getsource(m)
    # After fix: the module adds a file logging handler so errors reach disk
    has_file_handler = (
        "FileHandler" in src
        or "file_handler" in src.lower()
        or "log_file" in src.lower()
    )
    has_nonzero_rc_log = "returncode" in src and any(
        tok in src for tok in ("warning", "_log.warn", "_log.error")
    )
    assert has_file_handler or has_nonzero_rc_log, (
        "inbox_dispatch has no file logging — dispatch failures are silently discarded. "
        "Add a FileHandler or log non-zero dispatch return codes."
    )


# ── Iter 11 RED: dispatched is not an active inbox status ─────────────────────


def test_dispatched_not_active_status():
    """'dispatched' must not appear in inbox_dao._ACTIVE_STATUSES after session-injection removal.

    RED: Currently 'dispatched' is in _ACTIVE_STATUSES.
    After deletion (GREEN), this check passes.
    """
    from superharness.engine import inbox_dao

    assert "dispatched" not in inbox_dao._ACTIVE_STATUSES, (
        "'dispatched' is still in inbox_dao._ACTIVE_STATUSES. "
        "Remove it along with the rest of the session-injection path (Iter 11)."
    )


# ── Iter 13 RED: unique inbox constraint prevents duplicate dispatch ─────────


def _make_conn_with_schema():
    """Create an in-memory SQLite DB with the full superharness schema."""
    import sqlite3
    from superharness.engine.db import init_db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


def test_no_duplicate_round_item():
    """A second inbox insert for the same (task_id, target_agent) must fail.

    RED: No UNIQUE constraint on (task_id, target_agent) — duplicate rows can
    be inserted silently, causing double-dispatch. GREEN: add a partial UNIQUE
    index on inbox(task_id, target_agent) WHERE status NOT IN ('failed','done').
    """
    import sqlite3

    conn = _make_conn_with_schema()
    # Insert task first (FK requirement)
    conn.execute(
        "INSERT INTO tasks (id, title, status, owner, created_at) VALUES (?,?,?,?,?)",
        (
            "t-iter13",
            "Duplicate test task",
            "in_progress",
            "claude-code",
            "2026-06-07T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, priority, retry_count, max_retries, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "inbox-iter13-a",
            "t-iter13",
            "claude-code",
            "pending",
            5,
            0,
            3,
            "2026-06-07T00:00:00Z",
        ),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, priority, retry_count, max_retries, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                "inbox-iter13-b",
                "t-iter13",
                "claude-code",
                "pending",
                5,
                0,
                3,
                "2026-06-07T00:01:00Z",
            ),
        )
        conn.commit()
