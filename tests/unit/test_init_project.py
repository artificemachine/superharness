from __future__ import annotations

import subprocess
import sys

from tests.helpers import REPO_ROOT, run_cmd


def _run_init_py(cwd, args: list[str] | None = None, stdin: str | None = None, env: dict | None = None):
    """Run init_project Python module."""
    import os
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
    cmd = [sys.executable, "-m", "superharness.commands.init_project"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged,
                          input=stdin, check=False)


def test_init_project_help_and_dry_run(repo_root, tmp_path) -> None:
    help_result = _run_init_py(tmp_path, args=["--help"])
    assert help_result.returncode == 0
    assert "usage:" in help_result.stdout.lower() or "init" in help_result.stdout.lower()

    dry = _run_init_py(tmp_path, args=["--dry-run", "Demo", "Python", "active"])
    assert dry.returncode == 0
    assert "[dry-run]" in dry.stdout


def test_init_project_creates_expected_files(repo_root, tmp_path) -> None:
    project = tmp_path / "demo"
    project.mkdir()

    result = _run_init_py(project, args=["Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr

    assert (project / ".superharness/contract.yaml").exists()
    assert (project / ".superharness/failures.yaml").exists()
    assert (project / ".superharness/decisions.yaml").exists()
    assert (project / ".superharness/ledger.md").exists()
    assert (project / "CLAUDE.md").exists()
    assert (project / "AGENTS.md").exists()


def test_init_project_no_watcher_by_default(repo_root, tmp_path) -> None:
    """Without --with-watcher, init must NOT install a launchd plist."""
    project = tmp_path / "no-watcher"
    project.mkdir()

    result = _run_init_py(project, args=["Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr
    # "Watcher:" line should not appear without --with-watcher
    assert "Watcher:" not in result.stdout


def test_init_project_with_watcher_flag_accepted(repo_root, tmp_path) -> None:
    """--with-watcher flag should be accepted (even if launchd script is missing)."""
    project = tmp_path / "with-watcher"
    project.mkdir()

    result = _run_init_py(project, args=["--with-watcher", "Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr
    # The flag was accepted; watcher line may or may not appear depending on platform
    assert (project / ".superharness/contract.yaml").exists()


def test_init_project_doctor_hint_in_output(repo_root, tmp_path) -> None:
    """Init output should mention doctor and task create."""
    project = tmp_path / "hints"
    project.mkdir()

    result = _run_init_py(project, args=["Demo", "Python", "active"])
    assert result.returncode == 0
    assert "doctor" in result.stdout.lower()
    assert "task create" in result.stdout


def test_init_project_is_not_reentrant(repo_root, tmp_path) -> None:
    project = tmp_path / "demo2"
    project.mkdir()

    first = _run_init_py(project, args=["Demo", "Python", "active"])
    second = _run_init_py(project, args=["Demo", "Python", "active"])

    assert first.returncode == 0
    assert second.returncode == 1
    assert "already exists" in second.stdout
