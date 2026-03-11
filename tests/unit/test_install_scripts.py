from __future__ import annotations

import os
import subprocess
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


def test_install_wrapper_symlink_executes_scripts_from_outside_repo(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-wrapper.sh"
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()

    install = run_bash(script, cwd=repo_root, env={"HOME": str(home)})
    assert install.returncode == 0, install.stderr

    wrapper = home / ".local" / "bin" / "superharness"
    assert wrapper.exists()

    doctor_help = subprocess.run(
        [str(wrapper), "doctor", "--help"],
        cwd=work,
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert doctor_help.returncode == 0, doctor_help.stderr
    assert "Usage:" in doctor_help.stdout

    contract_help = subprocess.run(
        [str(wrapper), "contract", "--help"],
        cwd=work,
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert contract_help.returncode == 0, contract_help.stderr
    assert "Usage:" in contract_help.stdout


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


def test_setup_watcher_worker_creates_clean_worker_and_watcher_config(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "setup-watcher-worker.sh"
    project = tmp_path / "source-proj"
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    # Minimal script set required by setup script + installer checks.
    (project / "scripts" / "install-launchd-inbox-watcher.sh").write_text(
        (repo_root / "scripts" / "install-launchd-inbox-watcher.sh").read_text()
    )
    (project / "scripts" / "inbox-watch.sh").write_text(
        (repo_root / "scripts" / "inbox-watch.sh").read_text()
    )
    (project / "scripts" / "install-launchd-inbox-watcher.sh").chmod(0o755)
    (project / "scripts" / "inbox-watch.sh").chmod(0o755)
    (project / "README.md").write_text("source\n")
    (project / ".superharness" / "contract.yaml").write_text("id: demo\n")

    home = tmp_path / "home"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)
    worker = tmp_path / "worker-proj"

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project",
            str(project),
            "--worker",
            str(worker),
            "--interval",
            "15",
            "--to",
            "both",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Watcher worker is ready." in result.stdout
    assert (worker / "README.md").exists()
    assert (worker / ".superharness").is_symlink()
    assert (worker / ".superharness").resolve() == (project / ".superharness").resolve()
    watcher_cfg = project / ".superharness" / "watcher.yaml"
    assert watcher_cfg.exists()
    cfg_text = watcher_cfg.read_text()
    assert f'watcher_project: "{worker.resolve()}"' in cfg_text
    assert "launcher_timeout_seconds: 180" in cfg_text
    assert "codex_bypass: false" in cfg_text
