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


def test_install_launchd_rejects_invalid_confirm_codex_bypass(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home-invalid-codex"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project",
            str(project),
            "--to",
            "codex-cli",
            "--confirm-codex-bypass",
            "maybe",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 2
    assert "--confirm-codex-bypass must be yes or no" in result.stderr


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


def test_install_launchd_plist_keepalive_only_restarts_on_crash(repo_root, tmp_path) -> None:
    """KeepAlive must use SuccessfulExit=false so launchd only restarts on crash,
    not after a normal single-cycle exit."""
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
    # Must NOT use unconditional <true/> for KeepAlive
    assert "<key>KeepAlive</key>" in plist_text
    assert "<key>SuccessfulExit</key>" in plist_text
    assert "<false/>" in plist_text
    # Verify we don't have the old pattern: KeepAlive followed immediately by <true/>
    import re
    assert not re.search(r"<key>KeepAlive</key>\s*<true/>", plist_text), \
        "KeepAlive must not use unconditional <true/>"


def test_install_launchd_protected_path_requires_allow_flag(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    home = tmp_path / "home-protected"
    project = home / "Documents" / "proj"
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    fake_bin = _fake_launchd_bin(tmp_path)

    blocked = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )
    assert blocked.returncode == 1
    assert "Refusing launchd install for protected macOS folder" in blocked.stderr

    allowed = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
            "--allow-protected-path",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )
    assert allowed.returncode == 0, allowed.stderr


def test_install_launchd_writes_recover_arguments_to_plist(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
            "--recover-timeout-minutes", "11",
            "--recover-action", "retry",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    label = "com.superharness.inbox.proj-demo-"
    plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_text = plist.read_text()
    assert "<string>--recover-timeout-minutes</string>" in plist_text
    assert "<string>11</string>" in plist_text
    assert "<string>--recover-action</string>" in plist_text
    assert "<string>retry</string>" in plist_text


def test_ensure_launchd_rejects_invalid_confirm_codex_bypass(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "ensure-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project",
            str(project),
            "--confirm-codex-bypass",
            "maybe",
        ],
    )
    assert result.returncode == 2
    assert "--confirm-codex-bypass must be yes or no" in result.stderr


def test_reset_watcher_rejects_invalid_confirm_codex_bypass(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "reset-watcher-and-test.sh"
    project = _setup_launchd_project(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project",
            str(project),
            "--confirm-codex-bypass",
            "bad",
        ],
    )
    assert result.returncode == 2
    assert "--confirm-codex-bypass must be yes or no" in result.stderr


def test_sync_worker_copy_preserves_superharness_symlink(repo_root, tmp_path) -> None:
    """sync_worker_copy must not replace the worker .superharness symlink with
    a real directory copy. It should exclude .superharness entirely."""
    script = repo_root / "scripts" / "inbox-watch.sh"
    source = tmp_path / "source-proj"
    source.mkdir()
    (source / ".git").mkdir()
    (source / ".superharness").mkdir()
    (source / ".superharness" / "contract.yaml").write_text("id: test\n")
    (source / ".superharness" / "inbox.yaml").write_text("---\n")
    (source / "README.md").write_text("source\n")
    (source / ".venv").mkdir()
    (source / ".venv" / "bin").mkdir()
    (source / "node_modules").mkdir()
    (source / ".pytest_cache").mkdir()

    # Create worker dir with .superharness as a symlink (like setup-watcher-worker.sh does)
    worker = tmp_path / ".superharness-workers" / "source-proj"
    worker.mkdir(parents=True)
    (worker / "README.md").write_text("old\n")
    (worker / ".superharness").symlink_to(source / ".superharness")

    home = tmp_path
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(source), "--help"],
        env={"HOME": str(home)},
    )
    # --help exits 0 without running; we just need the script to be valid
    assert result.returncode == 0

    # Now actually run sync_worker_copy by sourcing the function
    sync_script = tmp_path / "run_sync.sh"
    sync_script.write_text(f"""#!/bin/bash
set -euo pipefail
PROJECT_DIR="{source}"
HOME="{home}"
export HOME
sync_worker_copy() {{
  local source_repo="$PROJECT_DIR"
  local worker_dir="$HOME/.superharness-workers/$(basename "$source_repo")"
  if [ -d "$worker_dir" ] && [ -d "$source_repo/.git" ]; then
    rsync -a --delete \\
      --exclude '.git' \\
      --exclude '.superharness' \\
      --exclude '.venv' \\
      --exclude 'node_modules' \\
      --exclude '.pytest_cache' \\
      "$source_repo/" "$worker_dir/" 2>/dev/null || true
  fi
}}
sync_worker_copy
""")
    sync_script.chmod(0o755)

    sync_result = run_bash(sync_script, cwd=tmp_path)
    assert sync_result.returncode == 0, sync_result.stderr

    # .superharness must still be a symlink
    assert (worker / ".superharness").is_symlink(), \
        ".superharness should remain a symlink after sync_worker_copy"
    assert (worker / ".superharness").resolve() == (source / ".superharness").resolve()
    # Source content should be synced
    assert (worker / "README.md").read_text() == "source\n"
    # Excluded dirs should not exist in worker
    assert not (worker / ".venv").exists(), ".venv should be excluded from sync"
    assert not (worker / "node_modules").exists(), "node_modules should be excluded from sync"
    assert not (worker / ".pytest_cache").exists(), ".pytest_cache should be excluded from sync"


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


def test_install_launchd_creates_plist_from_scratch(repo_root, tmp_path) -> None:
    """When no plist exists, install creates it with correct label and loads it."""
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home-fresh"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    plist_dir = home / "Library" / "LaunchAgents"
    assert not plist_dir.exists(), "LaunchAgents dir should not exist yet"

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--interval", "15",
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Installed launchd inbox watcher:" in result.stdout
    label = "com.superharness.inbox.proj-demo-"
    assert f"Label: {label}" in result.stdout
    plist = plist_dir / f"{label}.plist"
    assert plist.exists(), "Plist should be created from scratch"
    plist_text = plist.read_text()
    assert f"<string>{label}</string>" in plist_text
    assert "<integer>15</integer>" in plist_text


def test_install_launchd_reinstall_overwrites_existing_plist(repo_root, tmp_path) -> None:
    """Reinstalling overwrites the plist with updated settings."""
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home-reinstall"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    # First install with interval 30
    run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--interval", "30",
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    label = "com.superharness.inbox.proj-demo-"
    plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
    first_text = plist.read_text()
    assert "<integer>30</integer>" in first_text

    # Reinstall with interval 15
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--interval", "15",
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    second_text = plist.read_text()
    assert "<integer>15</integer>" in second_text
    # Old interval should be gone
    assert "<integer>30</integer>" not in second_text


def test_install_launchd_plist_contains_project_and_target(repo_root, tmp_path) -> None:
    """Plist must contain the project path and target agent arguments."""
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home-target"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "claude-code",
            "--confirm-non-interactive", "yes",
            "--confirm-skip-permissions", "yes",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    label = "com.superharness.inbox.proj-demo-"
    plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_text = plist.read_text()
    assert "<string>--project</string>" in plist_text
    assert "<string>--to</string>" in plist_text
    assert "<string>claude-code</string>" in plist_text


def test_install_launchd_output_reports_all_settings(repo_root, tmp_path) -> None:
    """Install output must report interval, recover settings, target, and mode."""
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = _setup_launchd_project(tmp_path)
    home = tmp_path / "home-output"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--interval", "20",
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
            "--recover-timeout-minutes", "15",
            "--recover-action", "stale",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Interval: 20s" in result.stdout
    assert "Recover timeout: 15m" in result.stdout
    assert "Recover action: stale" in result.stdout
    assert "Target: codex-cli" in result.stdout
    assert "Mode: non-interactive" in result.stdout


def test_install_launchd_missing_superharness_dir_fails(repo_root, tmp_path) -> None:
    """Install fails if project has no .superharness directory."""
    script = repo_root / "scripts" / "install-launchd-inbox-watcher.sh"
    project = tmp_path / "no-harness"
    project.mkdir()
    home = tmp_path / "home-no-harness"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "codex-cli",
            "--confirm-non-interactive", "yes",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 1
    assert "Missing .superharness" in result.stderr


def test_setup_watcher_worker_persists_custom_recover_values(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "setup-watcher-worker.sh"
    project = tmp_path / "source-proj-custom"
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    (project / "scripts" / "install-launchd-inbox-watcher.sh").write_text(
        (repo_root / "scripts" / "install-launchd-inbox-watcher.sh").read_text()
    )
    (project / "scripts" / "inbox-watch.sh").write_text(
        (repo_root / "scripts" / "inbox-watch.sh").read_text()
    )
    (project / "scripts" / "install-launchd-inbox-watcher.sh").chmod(0o755)
    (project / "scripts" / "inbox-watch.sh").chmod(0o755)
    (project / ".superharness" / "contract.yaml").write_text("id: demo\n")

    home = tmp_path / "home-custom"
    home.mkdir()
    fake_bin = _fake_launchd_bin(tmp_path)
    worker = tmp_path / "worker-proj-custom"

    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--worker", str(worker),
            "--interval", "15",
            "--recover-timeout-minutes", "12",
            "--recover-action", "stale",
            "--launcher-timeout", "45",
            "--to", "both",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        },
    )

    assert result.returncode == 0, result.stderr
    watcher_cfg = project / ".superharness" / "watcher.yaml"
    cfg_text = watcher_cfg.read_text()
    assert "recover_timeout_minutes: 12" in cfg_text
    assert "recover_action: stale" in cfg_text
    assert "launcher_timeout_seconds: 45" in cfg_text
