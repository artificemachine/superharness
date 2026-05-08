"""Black box tests — use CLI only, no internal imports. Verifies real user paths."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml


def _shux(project_dir: str, *args: str) -> subprocess.CompletedProcess:
    """Run shux status as a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.status", "--project", project_dir, *args],
        capture_output=True, text=True,
    )


def _task(project_dir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.task", "create", "--project", project_dir, *args],
        capture_output=True, text=True,
    )


def _bootstrap(project_dir: Path) -> None:
    """Minimal project setup."""
    sh = project_dir / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "profile.yaml").write_text(
        f"project_name: test\ncreated: 2026-01-01\nprimary_agent: claude-code\nstack: python\nautonomy: autonomous\n"
    )
    (sh / "contract.yaml").write_text("tasks: []\n")
    (sh / "inbox.yaml").write_text("[]\n")

    # Init SQLite
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project_dir))
    init_db(conn)
    conn.close()


# =============================================================================
# Black box tests
# =============================================================================

def test_blackbox_task_create_appears_in_status() -> None:
    """shux task create → shux status must show the task."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)

        r1 = _task(str(d), "--id", "bb-task-1", "--title", "Black box task", "--owner", "claude-code")
        assert "Created task" in r1.stdout, f"Task create failed: {r1.stdout} {r1.stderr}"

        r2 = _shux(str(d))
        assert "bb-task-1" in r2.stdout, f"Status must show created task: {r2.stdout[:500]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_blackbox_status_check_exits_correctly() -> None:
    """shux status --check must exit 0 clean, exit 1 with issues."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)
        # Write heartbeat to silence watcher warnings
        hb = d / ".superharness" / "watcher.heartbeat"
        hb.write_text("2026-05-05T00:00:00Z\n")

        r1 = _shux(str(d), "--check")
        assert r1.returncode == 1, f"Clean status with stale heartbeat should exit 1: {r1.stdout[:200]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_blackbox_status_fix_works() -> None:
    """shux status --fix must clean orphaned items."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)
        hb = d / ".superharness" / "watcher.heartbeat"
        hb.write_text("2026-05-05T00:00:00Z\n")

        # Create orphan via CLI
        _task(str(d), "--id", "orphan-me", "--title", "Orphan", "--owner", "claude-code")

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao, tasks_dao
        from superharness.engine.tasks_dao import TaskRow
        conn = get_connection(str(d))
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(id="orphan-me", title="O", owner="claude-code", status="done", effort="low", project_path=str(d), development_method="tdd", acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, version=1, created_at="2026-01-01T00:00:00Z"))
        inbox_dao.enqueue(conn, id="orph-1", task_id="orphan-me", target_agent="claude-code", priority=2, project_path=str(d), now="2026-01-01T00:00:00Z")
        conn.commit(); conn.close()

        # Write YAML too (test mode reads YAML first)
        (d / ".superharness" / "inbox.yaml").write_text(yaml.dump([{"id": "orph-1", "task": "orphan-me", "to": "claude-code", "status": "pending", "created_at": "2026-01-01T00:00:00Z"}]))

        r2 = _shux(str(d), "--fix")
        assert "Cleaned" in r2.stdout or "Fixed" in r2.stdout, f"--fix should clean: {r2.stdout[:300]}"
    finally:
        import shutil; shutil.rmtree(d)


def test_blackbox_discuss_start_creates_discussion() -> None:
    """shux discuss start must create a discussion directory."""
    d = Path(tempfile.mkdtemp())
    try:
        _bootstrap(d)
        import yaml as _yaml
        (d / ".superharness" / "contract.yaml").write_text(_yaml.dump({"tasks": []}))

        r = subprocess.run(
            [sys.executable, "-m", "superharness.commands.discuss", "start",
             "--project", str(d), "--topic", "BB test", "--task", "bb-discuss",
             "--owners", "claude-code,codex-cli", "--max-rounds", "1"],
            capture_output=True, text=True,
        )
        assert "started" in r.stdout.lower(), f"Discuss start failed: {r.stdout} {r.stderr}"
        discs = list((d / ".superharness" / "discussions").iterdir())
        assert len(discs) >= 1, f"Discussion directory must exist: {discs}"
    finally:
        import shutil; shutil.rmtree(d)
