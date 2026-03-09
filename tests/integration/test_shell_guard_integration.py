from __future__ import annotations

from pathlib import Path

from tests.helpers import copy_from_repo, run_bash, run_cmd


def _init_git_repo(path: Path) -> None:
    run_cmd(["git", "init"], cwd=path)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=path)
    run_cmd(["git", "config", "user.name", "tester"], cwd=path)


def _copy_guard_tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    required = [
        "init-project.sh",
        "adapters/claude-code/install.sh",
        "adapters/claude-code/hooks/branch-guard.sh",
        "adapters/claude-code/hooks/ledger-append.sh",
        "adapters/claude-code/hooks/scope-guard.sh",
        "adapters/claude-code/hooks/session-start.sh",
        "scripts/check-shell-entrypoints.sh",
        "scripts/check-contract-hygiene.sh",
        "scripts/delegate-to-claude.sh",
        "scripts/delegate-to-codex.sh",
        "scripts/ensure-launchd-inbox-watcher.sh",
        "scripts/inbox-dispatch.sh",
        "scripts/inbox-enqueue.sh",
        "scripts/inbox-normalize.sh",
        "scripts/inbox-recover-stale.sh",
        "scripts/inbox-watch.sh",
        "scripts/install-launchd-inbox-watcher.sh",
        "scripts/install-git-hooks.sh",
        "scripts/uninstall-launchd-inbox-watcher.sh",
        ".githooks/pre-commit",
        "identity/core.md",
        "scripts/inbox-yaml.rb",
    ]

    for rel in required:
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
