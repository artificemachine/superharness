from __future__ import annotations

from tests.helpers import run_bash


def test_init_project_help_and_dry_run(repo_root, tmp_path) -> None:
    script = repo_root / "init-project.sh"

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
    script = repo_root / "init-project.sh"
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


def test_init_project_is_not_reentrant(repo_root, tmp_path) -> None:
    script = repo_root / "init-project.sh"
    project = tmp_path / "demo2"
    project.mkdir()

    first = run_bash(script, cwd=project, args=["Demo", "Python", "active"])
    second = run_bash(script, cwd=project, args=["Demo", "Python", "active"])

    assert first.returncode == 0
    assert second.returncode == 1
    assert "already exists" in second.stdout
