from __future__ import annotations

from tests.helpers import run_bash, run_cmd


def test_claude_install_dry_run(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/install.sh"
    home = tmp_path / "home"
    home.mkdir()

    result = run_bash(script, cwd=tmp_path, env={"HOME": str(home)}, args=["--dry-run"])
    assert result.returncode == 0
    assert "[dry-run]" in result.stdout


def test_claude_install_symlink_lifecycle(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/install.sh"
    home = tmp_path / "home"
    home.mkdir()

    first = run_bash(script, cwd=tmp_path, env={"HOME": str(home)})
    second = run_bash(script, cwd=tmp_path, env={"HOME": str(home)})

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "Already installed" in second.stdout


def test_install_git_hooks_force_behavior(repo_root, tmp_path) -> None:
    script = repo_root / "scripts/install-git-hooks.sh"

    run_cmd(["git", "init"], cwd=tmp_path)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=tmp_path)
    run_cmd(["git", "config", "user.name", "tester"], cwd=tmp_path)

    run_cmd(["git", "config", "core.hooksPath", "custom-hooks"], cwd=tmp_path)
    blocked = run_bash(script, cwd=tmp_path)
    assert blocked.returncode == 1
    assert "Refusing to overwrite" in blocked.stdout

    dry_force = run_bash(script, cwd=tmp_path, args=["--force", "--dry-run"])
    assert dry_force.returncode == 0
    assert "Would replace" in dry_force.stdout

    forced = run_bash(script, cwd=tmp_path, args=["--force"])
    assert forced.returncode == 0

    hooks_path = run_cmd(["git", "config", "--get", "core.hooksPath"], cwd=tmp_path)
    assert hooks_path.stdout.strip() == ".githooks"
