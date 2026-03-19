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
    """On macOS, init attempts watcher by default; no plist is created without explicit confirmation."""
    import platform
    project = tmp_path / "no-watcher"
    project.mkdir()

    result = _run_init_py(project, args=["Demo", "Python", "active"])
    assert result.returncode == 0, result.stderr
    if platform.system() == "Darwin":
        # Watcher install is attempted on macOS, but no plist is created without user confirmation
        import re, pathlib
        slug = re.sub(r"[^A-Za-z0-9]+", "-", project.name)
        real_plist = pathlib.Path.home() / "Library" / "LaunchAgents" / f"com.superharness.inbox.{slug}.plist"
        assert not real_plist.exists(), f"Watcher plist must not be auto-created without confirmation: {real_plist}"
    else:
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


# ── refresh: user-owned file preservation ─────────────────────────────────

def test_refresh_skips_existing_user_files(repo_root, tmp_path) -> None:
    """shux update (--refresh) must not overwrite CLAUDE.md, AGENTS.md, SOUL.md."""
    _run_init_py(tmp_path, args=["Demo", "Python", "active"])

    sentinel = "# USER CUSTOMISATION — DO NOT OVERWRITE"
    for fname in ("CLAUDE.md", "AGENTS.md", "SOUL.md"):
        f = tmp_path / fname
        f.write_text(sentinel + "\n" + f.read_text())

    result = _run_init_py(tmp_path, args=["--refresh", "--detect"])
    assert result.returncode == 0

    for fname in ("CLAUDE.md", "AGENTS.md", "SOUL.md"):
        content = (tmp_path / fname).read_text()
        assert sentinel in content, f"{fname} was overwritten by --refresh"
        assert "user-owned" in result.stdout, f"Expected skip message for {fname}"


def test_refresh_force_overwrites_user_files(repo_root, tmp_path) -> None:
    """--refresh --force must overwrite CLAUDE.md, AGENTS.md, SOUL.md."""
    _run_init_py(tmp_path, args=["Demo", "Python", "active"])

    sentinel = "# USER CUSTOMISATION — DO NOT OVERWRITE"
    for fname in ("CLAUDE.md", "AGENTS.md", "SOUL.md"):
        f = tmp_path / fname
        f.write_text(sentinel + "\n" + f.read_text())

    result = _run_init_py(tmp_path, args=["--refresh", "--force", "--detect"])
    assert result.returncode == 0

    for fname in ("CLAUDE.md", "AGENTS.md", "SOUL.md"):
        content = (tmp_path / fname).read_text()
        assert sentinel not in content, f"{fname} was NOT overwritten despite --force"
        assert "Refreshed" in result.stdout


def test_refresh_skip_message_mentions_force(repo_root, tmp_path) -> None:
    """Skip message must tell the user how to force an overwrite."""
    _run_init_py(tmp_path, args=["Demo", "Python", "active"])
    result = _run_init_py(tmp_path, args=["--refresh", "--detect"])
    assert result.returncode == 0
    assert "--force" in result.stdout


def test_init_creates_user_files_when_missing(repo_root, tmp_path) -> None:
    """Fresh init (no --refresh) always creates the files."""
    result = _run_init_py(tmp_path, args=["Demo", "Python", "active"])
    assert result.returncode == 0
    for fname in ("CLAUDE.md", "AGENTS.md"):
        assert (tmp_path / fname).exists(), f"{fname} not created by init"


def test_init_prints_plugin_install_hint_when_plugin_missing(repo_root, tmp_path) -> None:
    """Init must print plugin install hint when ~/.claude/plugins/superharness is absent."""
    import os
    project = tmp_path / "plugtest"
    project.mkdir()
    # Point HOME to a temp dir that has no plugin installed
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    result = _run_init_py(project, args=["Demo", "Python", "active"], env={"HOME": str(fake_home)})
    assert result.returncode == 0, result.stderr
    # Hint should mention the install command
    combined = result.stdout + result.stderr
    assert "install" in combined.lower() and ("plugin" in combined.lower() or "adapt" in combined.lower())


def test_init_no_hint_when_plugin_already_installed(repo_root, tmp_path) -> None:
    """Init must NOT print plugin hint when ~/.claude/plugins/superharness already exists."""
    import os
    project = tmp_path / "plugtest2"
    project.mkdir()
    # Create fake plugin directory in a fake HOME
    fake_home = tmp_path / "fakehome2"
    plugin_dir = fake_home / ".claude" / "plugins" / "superharness"
    plugin_dir.mkdir(parents=True)
    result = _run_init_py(project, args=["Demo", "Python", "active"], env={"HOME": str(fake_home)})
    assert result.returncode == 0, result.stderr
    # The plugin hint line should not appear
    assert "install the plugin" not in result.stdout


def test_refresh_runs_install_hooks(repo_root, tmp_path) -> None:
    """shux update (--refresh) must also run install-hooks, not just fresh init."""
    import json
    project = tmp_path / "refresh-hooks"
    project.mkdir()
    fake_home = tmp_path / "fakehome-refresh"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    # Fresh init first
    _run_init_py(project, args=["Demo", "Python", "active"], env={"HOME": str(fake_home)})
    # Remove settings to verify refresh re-creates it
    settings_file = fake_home / ".claude" / "settings.json"
    if settings_file.exists():
        settings_file.unlink()

    # Now run --refresh (simulates shux update)
    result = _run_init_py(project, args=["--refresh", "--detect"], env={"HOME": str(fake_home)})
    assert result.returncode == 0, result.stderr
    assert settings_file.exists(), "--refresh must run install-hooks and create settings.json"
    data = json.loads(settings_file.read_text())
    stop_cmds = [
        h["command"]
        for entry in data.get("hooks", {}).get("Stop", [])
        for h in entry.get("hooks", [])
    ]
    assert any("session-stop.sh" in cmd for cmd in stop_cmds), \
        f"--refresh must write session-stop.sh hook: {stop_cmds}"


def test_init_skip_hooks_flag(repo_root, tmp_path) -> None:
    """--skip-hooks must prevent install-hooks from running."""
    project = tmp_path / "skip-hooks"
    project.mkdir()
    fake_home = tmp_path / "fakehome-skip"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    result = _run_init_py(project, args=["--skip-hooks", "Demo", "Python", "active"],
                          env={"HOME": str(fake_home)})
    assert result.returncode == 0, result.stderr
    assert "Hooks: skipped (--skip-hooks)" in result.stdout
    settings_file = fake_home / ".claude" / "settings.json"
    assert not settings_file.exists(), "--skip-hooks must not create settings.json"


def test_init_runs_install_hooks(repo_root, tmp_path) -> None:
    """shux init must run install-hooks and write hook entries to ~/.claude/settings.json."""
    import json, os
    project = tmp_path / "inithooks"
    project.mkdir()
    fake_home = tmp_path / "fakehome-hooks"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    result = _run_init_py(project, args=["Demo", "Python", "active"], env={"HOME": str(fake_home)})
    assert result.returncode == 0, result.stderr

    settings_file = fake_home / ".claude" / "settings.json"
    assert settings_file.exists(), "install-hooks must create ~/.claude/settings.json"
    data = json.loads(settings_file.read_text())
    assert "hooks" in data, "settings.json must contain hooks key"
    stop_cmds = [
        h["command"]
        for entry in data["hooks"].get("Stop", [])
        for h in entry.get("hooks", [])
    ]
    assert any("session-stop.sh" in cmd for cmd in stop_cmds), \
        f"session-stop.sh not found in Stop hooks: {stop_cmds}"


def test_init_install_hooks_does_not_fail_init(repo_root, tmp_path) -> None:
    """Even if install-hooks fails (e.g. hooks.json missing), init must still succeed."""
    import os
    project = tmp_path / "inithooks-fail"
    project.mkdir()
    # HOME with no .claude/ — install-hooks should create it or skip gracefully
    fake_home = tmp_path / "fakehome-missing"
    fake_home.mkdir()

    result = _run_init_py(project, args=["Demo", "Python", "active"], env={"HOME": str(fake_home)})
    assert result.returncode == 0, f"init must not fail when install-hooks runs: {result.stderr}"
