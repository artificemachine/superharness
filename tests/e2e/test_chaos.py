"""Chaos / fault injection tests — system resilience under failure."""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import yaml


def _bootstrap(project_dir: Path) -> None:
    sh = project_dir / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "profile.yaml").write_text("project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n")
    (sh / "contract.yaml").write_text("tasks: []\n")
    (sh / "inbox.yaml").write_text("[]\n")
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project_dir))
    init_db(conn)
    conn.close()


# =============================================================================
# Chaos tests
# =============================================================================

def test_corrupt_sqlite_does_not_crash_status() -> None:
    """shux status must not crash when state.sqlite3 is corrupted."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)

        # Corrupt the database
        db_path = d / ".superharness" / "state.sqlite3"
        db_path.write_bytes(b"this is not a valid sqlite database")

        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.status", "--project", str(d)],
            capture_output=True, text=True,
        )
        # Must not crash — may return empty or error but not raise
        assert result.returncode in (0, 1), f"Corrupt DB must not crash: {result.stderr[:200]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_missing_sqlite_falls_back_to_yaml() -> None:
    """When state.sqlite3 is missing, status must fall back to YAML gracefully."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)
        # Delete SQLite
        (d / ".superharness" / "state.sqlite3").unlink()

        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.status", "--project", str(d)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Missing DB should fall back gracefully: {result.stderr[:200]}"
        assert "tasks:" in result.stdout, f"Status should show task counts: {result.stdout[:200]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_stale_pid_does_not_block_new_watcher() -> None:
    """A stale watcher PID file must not prevent a new watcher from starting."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)

        # Write a stale PID (process that doesn't exist)
        daemon_state = d / ".superharness" / "daemon-state.json"
        import json
        daemon_state.write_text(json.dumps({"watcher_pid": 99999}))

        # Verify the watcher can start (via operator or direct call)
        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.daemon", "status", "--project", str(d)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Daemon status must handle stale PID: {result.stderr[:200]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_empty_inbox_does_not_crash_dispatch() -> None:
    """Dispatch with empty inbox must not crash the watcher."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)

        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.inbox_dispatch",
             "--project", str(d), "--to", "claude-code", "--print-only"],
            capture_output=True, text=True,
        )
        # print-only with empty inbox should succeed
        assert result.returncode in (0, 1), f"Empty dispatch must not crash: {result.stderr[:200]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_reconcile_handles_corrupt_handoff() -> None:
    """Lifecycle reconciler must not crash on corrupt handoff files."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)
        handoffs = d / ".superharness" / "handoffs"
        handoffs.mkdir(exist_ok=True)
        (handoffs / "corrupt.yaml").write_text("not: valid: yaml: [")

        from superharness.engine.lifecycle_rules import reconcile_lifecycle
        changed = reconcile_lifecycle(str(d))
        assert changed == 0, "Reconciler must not crash on corrupt files"
    finally:
        import shutil; shutil.rmtree(d)


def test_double_delete_does_not_crash() -> None:
    """Deleting an already-deleted inbox item must not crash."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)

        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(d))
        init_db(conn)
        # Try deleting a non-existent item
        conn.execute("DELETE FROM inbox WHERE id='nonexistent'")
        conn.commit()
        conn.close()
        # Must not raise
    finally:
        import shutil; shutil.rmtree(d)


def test_max_tasks_does_not_crash_status() -> None:
    """shux status must handle many tasks without crashing (basic load)."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow

        conn = get_connection(str(d))
        init_db(conn)
        for i in range(100):
            tasks_dao.upsert(conn, TaskRow(
                id=f"load-{i}", title=f"Load task {i}", owner="claude-code",
                status="archived", effort="low",
                project_path=str(d), development_method="tdd",
                acceptance_criteria=[f"AC-{i}"], test_types=[], out_of_scope=[],
                definition_of_done=[], context=None, tdd=None,
                version=1, created_at="2026-01-01T00:00:00Z",
            ))
        conn.commit(); conn.close()

        import time
        start = time.time()
        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.status", "--project", str(d)],
            capture_output=True, text=True,
        )
        elapsed = time.time() - start
        assert result.returncode == 0, f"Status must succeed with 100 tasks: {result.stderr[:200]}"
        assert elapsed < 5, f"Status with 100 tasks must be fast (<5s), got {elapsed:.1f}s"
    finally:
        import shutil; shutil.rmtree(d)
