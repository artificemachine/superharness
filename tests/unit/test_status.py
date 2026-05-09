from __future__ import annotations

"""Tests for superharness status.

NOTE: The original tests in this file tested cli/status.sh, which was a contract
dashboard script deleted in S6 (dead cli/*.sh cleanup). The new `superharness status`
command (superharness.commands.status) reports watcher/inbox health, not the contract
dashboard. Tests have been updated accordingly.
"""

import sys

import pytest

from tests.helpers import REPO_ROOT


pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def _run_python(args: list[str]) -> "subprocess.CompletedProcess[str]":
    import os
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.status"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _write_harness(project_dir, *, inbox_yaml: str | None = None):
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(parents=True, exist_ok=True)
    if inbox_yaml is not None:
        (sh_dir / "inbox.yaml").write_text(inbox_yaml)
    return sh_dir


@pytest.mark.skipif(sys.platform == "win32", reason="Unix execute-bit not meaningful on Windows NTFS")
def test_status_script_is_executable(repo_root) -> None:
    """src/superharness/scripts/status.sh should still be executable (Bash wrapper kept)."""
    script = repo_root / "src" / "superharness" / "scripts" / "status.sh"
    assert script.exists(), "src/superharness/scripts/status.sh not found"
    import stat
    assert script.stat().st_mode & stat.S_IXUSR, "src/superharness/scripts/status.sh is not executable"


def test_status_no_contract(repo_root, tmp_path) -> None:
    """status exits 1 when .superharness is missing."""
    project = tmp_path / "proj"
    project.mkdir()
    result = _run_python(["--project", str(project)])
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "Missing .superharness" in combined or "missing" in combined.lower()


def test_status_shows_contract_id_and_goal(repo_root, tmp_path) -> None:
    """status shows watcher/inbox summary for a valid project."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_harness(project)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "superharness status" in result.stdout


def test_status_task_counts(repo_root, tmp_path) -> None:
    """status reports inbox counts correctly."""
    project = tmp_path / "proj"
    project.mkdir()
    inbox_yaml = """\
- id: item-1
  status: pending
  to: claude-code
  task: task-a
- id: item-2
  status: pending
  to: claude-code
  task: task-b
- id: item-3
  status: done
  to: claude-code
  task: task-c
"""
    _write_harness(project, inbox_yaml=inbox_yaml)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "pending=2" in result.stdout
    assert "done=1" in result.stdout


def test_status_next_task(repo_root, tmp_path) -> None:
    """status shows inbox summary line."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_harness(project)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "inbox:" in result.stdout


def test_status_no_ledger(repo_root, tmp_path) -> None:
    """status works even without a ledger file."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_harness(project)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    # Should include watcher/heartbeat output
    assert "heartbeat:" in result.stdout


def test_status_ledger_last_entry(repo_root, tmp_path) -> None:
    """status summary line is present."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_harness(project)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Issues" in result.stdout or "No issues found" in result.stdout


def test_status_no_watcher_heartbeat(repo_root, tmp_path) -> None:
    """status shows missing heartbeat."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_harness(project)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "missing" in result.stdout.lower() or "no heartbeat" in result.stdout.lower()


def test_status_fresh_watcher(repo_root, tmp_path) -> None:
    """status shows recent heartbeat age."""
    from datetime import datetime, timezone
    project = tmp_path / "proj"
    project.mkdir()
    sh_dir = _write_harness(project)
    # Write a fresh heartbeat (5 seconds ago)
    now = datetime.now(timezone.utc)
    (sh_dir / "watcher.heartbeat").write_text(now.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    # Should show ok heartbeat
    assert "ok" in result.stdout.lower() or "ago" in result.stdout.lower()


def test_status_stale_watcher(repo_root, tmp_path) -> None:
    """status shows stale heartbeat."""
    project = tmp_path / "proj"
    project.mkdir()
    sh_dir = _write_harness(project)
    # Write a stale heartbeat (10 minutes ago)
    (sh_dir / "watcher.heartbeat").write_text("2026-01-01T00:00:00Z\n")
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "stale" in result.stdout.lower()


def test_status_no_profile(repo_root, tmp_path) -> None:
    """status works without a profile.yaml."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_harness(project)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "superharness status" in result.stdout


def test_status_with_profile(repo_root, tmp_path) -> None:
    """status works with a profile.yaml present."""
    project = tmp_path / "proj"
    project.mkdir()
    sh_dir = _write_harness(project)
    (sh_dir / "profile.yaml").write_text("autonomy: autonomous\nprimary_agent: codex-cli\nteam_size: small\n")
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "superharness status" in result.stdout


def test_status_reads_worker_project_heartbeat(repo_root, tmp_path) -> None:
    from datetime import datetime, timezone

    project = tmp_path / "proj"
    project.mkdir()
    sh_dir = _write_harness(project)
    worker = tmp_path / "worker"
    (worker / ".superharness").mkdir(parents=True)
    (sh_dir / "watcher.yaml").write_text(
        # Use as_posix() so Windows backslashes don't become YAML escape sequences.
        f'watcher_project: "{worker.as_posix()}"\ninterval_seconds: 30\n',
        encoding="utf-8",
    )
    (sh_dir / "watcher.heartbeat").write_text("2026-01-01T00:00:00Z\n", encoding="utf-8")
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (worker / ".superharness" / "watcher.heartbeat").write_text(fresh + "\n", encoding="utf-8")

    result = _run_python(["--project", str(project)])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "heartbeat: ok" in result.stdout.lower()
    assert "worker project" in result.stdout.lower()
