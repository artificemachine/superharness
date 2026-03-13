from __future__ import annotations

from tests.helpers import run_bash


def test_init_project_help_and_dry_run(repo_root, tmp_path) -> None:
    script = repo_root / "scripts/init-project.sh"

    help_result = run_bash(script, cwd=tmp_path, args=["--help"])
    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout

    dry = run_bash(
        script,
        cwd=tmp_path,
        args=["--dry-run", "Demo", "Python", "active"],
    )
    assert dry.returncode == 0
    assert "[dry-run]" in dry.stdout


def test_init_project_creates_expected_files(repo_root, tmp_path) -> None:
    script = repo_root / "scripts/init-project.sh"
    project = tmp_path / "demo"
    project.mkdir()

    result = run_bash(script, cwd=project, args=["Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr

    assert (project / ".superharness/contract.yaml").exists()
    assert (project / ".superharness/failures.yaml").exists()
    assert (project / ".superharness/decisions.yaml").exists()
    assert (project / ".superharness/ledger.md").exists()
    assert (project / "CLAUDE.md").exists()
    assert (project / "AGENTS.md").exists()


def test_init_project_no_watcher_by_default(repo_root, tmp_path) -> None:
    """Without --with-watcher, init must NOT install a launchd plist."""

    script = repo_root / "scripts/init-project.sh"
    project = tmp_path / "no-watcher"
    project.mkdir()

    result = run_bash(script, cwd=project, args=["Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr
    # "Watcher:" line should not appear without --with-watcher
    assert "Watcher:" not in result.stdout


def test_init_project_with_watcher_flag_accepted(repo_root, tmp_path) -> None:
    """--with-watcher flag should be accepted (even if launchd script is missing)."""
    script = repo_root / "scripts/init-project.sh"
    project = tmp_path / "with-watcher"
    project.mkdir()

    result = run_bash(script, cwd=project, args=["--with-watcher", "Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr
    # The flag was accepted; watcher line may or may not appear depending on platform
    assert (project / ".superharness/contract.yaml").exists()


def test_init_project_doctor_hint_in_output(repo_root, tmp_path) -> None:
    """Init output should mention doctor and task create."""
    script = repo_root / "scripts/init-project.sh"
    project = tmp_path / "hints"
    project.mkdir()

    result = run_bash(script, cwd=project, args=["Demo", "Python", "active"])
    assert result.returncode == 0
    assert "doctor" in result.stdout.lower()
    assert "task create" in result.stdout


def test_init_project_is_not_reentrant(repo_root, tmp_path) -> None:
    script = repo_root / "scripts/init-project.sh"
    project = tmp_path / "demo2"
    project.mkdir()

    first = run_bash(script, cwd=project, args=["Demo", "Python", "active"])
    second = run_bash(script, cwd=project, args=["Demo", "Python", "active"])

    assert first.returncode == 0
    assert second.returncode == 1
    assert "already exists" in second.stdout
