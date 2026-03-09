from __future__ import annotations

import os
from pathlib import Path

from tests.helpers import run_bash, run_cmd


def _setup_launchd_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj & demo"
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    return project


def _fake_launchd_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)

    uname = bin_dir / "uname"
    uname.write_text("#!/bin/bash\necho Darwin\n")
    uname.chmod(0o755)

    launchctl = bin_dir / "launchctl"
    launchctl.write_text("#!/bin/bash\nexit 0\n")
    launchctl.chmod(0o755)

    return bin_dir


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


def test_install_launchd_requires_explicit_noninteractive_confirmation(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli"],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 1
    assert "--confirm-non-interactive yes" in result.stderr


def test_install_launchd_requires_explicit_claude_skip_permissions_confirmation(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "claude-code", "--confirm-non-interactive", "yes"],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 1
    assert "--confirm-skip-permissions yes" in result.stderr


def test_install_launchd_escapes_plist_values_and_writes_confirmation_envs(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--confirm-non-interactive", "yes"],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    label = "com.superharness.inbox.proj-demo-"
    plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_text = plist.read_text()
    assert "&amp;" in plist_text
    assert "<key>SUPERHARNESS_CONFIRM_NON_INTERACTIVE</key>" in plist_text
    assert "<string>YES</string>" in plist_text
    assert "<key>SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS</key>" in plist_text
    assert "<key>SUPERHARNESS_CONFIRM_CODEX_BYPASS</key>" in plist_text
