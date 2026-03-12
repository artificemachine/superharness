from __future__ import annotations

from pathlib import Path

from tests.helpers import REPO_ROOT, copy_from_repo, run_bash, run_cmd, shell_guard_list


def _init_git_repo(path: Path) -> None:
    run_cmd(["git", "init"], cwd=path)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=path)
    run_cmd(["git", "config", "user.name", "tester"], cwd=path)


def _copy_guard_tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    required = (
        shell_guard_list(REPO_ROOT, "--list-entrypoints")
        + shell_guard_list(REPO_ROOT, "--list-hooks")
        + [
            "protocol/templates/identity-core.md",
            "scripts/inbox-yaml.rb",
            "cli/contract-today.sh",
            "cli/doctor.sh",
            "cli/install-wrapper.sh",
            "cli/delegate-task.sh",
            "cli/task.sh",
            "superharness",
        ]
    )

    for rel in sorted(set(required)):
        copy_from_repo(rel, repo)

    _init_git_repo(repo)
    run_cmd(["git", "add", "."], cwd=repo)
    return repo


def test_shell_guard_passes_on_expected_tree(tmp_path) -> None:
    repo = _copy_guard_tree(tmp_path)
    result = run_bash(repo / "scripts/check-shell-entrypoints.sh", cwd=repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout


def test_shell_guard_detects_allowlist_drift(tmp_path) -> None:
    repo = _copy_guard_tree(tmp_path)
    extra = repo / "scripts/new-entrypoint.sh"
    extra.write_text("#!/bin/bash\necho hi\n")
    extra.chmod(0o755)
    run_cmd(["git", "add", str(extra)], cwd=repo)

    result = run_bash(repo / "scripts/check-shell-entrypoints.sh", cwd=repo)

    assert result.returncode == 1
    assert "missing from ENTRYPOINT_FILES allowlist" in result.stdout


def test_pre_commit_hook_executes_guard(tmp_path) -> None:
    repo = _copy_guard_tree(tmp_path)
    result = run_bash(repo / ".githooks/pre-commit", cwd=repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Shell entrypoint guard passed" in result.stdout


def test_shell_guard_list_all_includes_entrypoints_and_hooks(tmp_path) -> None:
    repo = _copy_guard_tree(tmp_path)
    result = run_bash(repo / "scripts/check-shell-entrypoints.sh", cwd=repo, args=["--list-all"])
    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert "scripts/inbox-watch.sh" in lines
    assert ".githooks/pre-commit" in lines
