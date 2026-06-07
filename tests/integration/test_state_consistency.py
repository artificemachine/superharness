"""Iter 12 RED integration tests: DB path split-brain detection and consolidation."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys


def _shux(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "superharness.cli", *args],
        capture_output=True, text=True, cwd=cwd,
    )


def _init_sqlite(path: str) -> None:
    """Create a minimal valid SQLite state db at path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()


# ── test_doctor_detects_two_dbs ────────────────────────────────────────────────

def test_doctor_detects_two_dbs(tmp_path, monkeypatch):
    """doctor must report a WARN when both XDG and legacy state dbs exist.

    RED: doctor currently does not check for two-DB coexistence (split-brain).
    GREEN: add a check that warns when both paths exist simultaneously.
    """
    from superharness.utils.paths import resolve_xdg_state_db_path

    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "proj")
    os.makedirs(project)

    # Create BOTH the XDG db and the legacy db
    xdg_db = resolve_xdg_state_db_path(project)
    legacy_db = os.path.join(project, ".superharness", "state.sqlite3")
    _init_sqlite(xdg_db)
    _init_sqlite(legacy_db)

    result = _shux("doctor", "--project", project, cwd=project)
    output = result.stdout + result.stderr

    assert "split-brain" in output.lower() or "two state db" in output.lower() or "both state" in output.lower(), (
        f"doctor output did not warn about two-DB coexistence (split-brain).\n"
        f"Expected a WARN containing 'split-brain', 'two state db', or 'both state'.\n"
        f"Got: {output!r}"
    )


# ── test_migrate_state_consolidates_when_both_exist ───────────────────────────

def test_migrate_state_consolidates_when_both_exist(tmp_path, monkeypatch):
    """migrate-state must merge legacy into XDG when both exist, not abort.

    RED: currently migrate-state aborts with exit 1 when XDG already exists,
    even when legacy has newer data. GREEN: detect split-brain, merge (prefer
    XDG unless --prefer-legacy), then remove legacy.
    """
    from superharness.utils.paths import resolve_xdg_state_db_path
    from superharness.commands.migrate_state import run_migrate_state

    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "proj")
    os.makedirs(project)

    xdg_db = resolve_xdg_state_db_path(project)
    legacy_db = os.path.join(project, ".superharness", "state.sqlite3")
    _init_sqlite(xdg_db)
    _init_sqlite(legacy_db)

    # Should succeed (or report the split-brain) rather than hard-abort with 1
    rc = run_migrate_state(project_dir=project, dry_run=True, keep_legacy=True)
    assert rc == 0, (
        f"migrate-state aborted (rc={rc}) when both XDG and legacy dbs exist. "
        "It should detect split-brain and report/merge rather than hard-failing."
    )
