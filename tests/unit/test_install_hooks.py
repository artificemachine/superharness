"""Tests for shux install-hooks — writes portable hook entries to ~/.claude/settings.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.helpers import run_cmd

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses bash hooks")


def _run_install_hooks(tmp_settings: Path, hooks_dir: Path) -> "subprocess.CompletedProcess[str]":
    return run_cmd(
        [sys.executable, "-m", "superharness.commands.install_hooks",
         "--settings-file", str(tmp_settings),
         "--hooks-dir", str(hooks_dir)],
        cwd=hooks_dir,
    )


class TestInstallHooks:
    def test_creates_settings_file_if_missing(self, tmp_path: Path, repo_root: Path) -> None:
        hooks_dir = repo_root / "adapters" / "claude-code" / "hooks"
        settings = tmp_path / "settings.json"
        result = _run_install_hooks(settings, hooks_dir)
        assert result.returncode == 0, result.stderr
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "hooks" in data

    def test_stop_hook_written_with_real_path(self, tmp_path: Path, repo_root: Path) -> None:
        hooks_dir = repo_root / "adapters" / "claude-code" / "hooks"
        settings = tmp_path / "settings.json"
        _run_install_hooks(settings, hooks_dir)
        data = json.loads(settings.read_text())
        stop_cmds = [
            h["command"]
            for entry in data["hooks"].get("Stop", [])
            for h in entry.get("hooks", [])
        ]
        assert any("session-stop.sh" in cmd for cmd in stop_cmds), stop_cmds
        # Must not contain ${CLAUDE_PLUGIN_ROOT} — must be resolved
        assert all("${CLAUDE_PLUGIN_ROOT}" not in cmd for cmd in stop_cmds), stop_cmds
        # Must not contain hardcoded user home path (no /Users/<name>/ or /home/<name>/)
        assert all(str(hooks_dir) in cmd or "session-stop" not in cmd for cmd in stop_cmds)

    def test_no_hardcoded_user_path_in_written_commands(self, tmp_path: Path, repo_root: Path) -> None:
        """All written hook commands must use the provided hooks_dir, not CLAUDE_PLUGIN_ROOT."""
        hooks_dir = repo_root / "adapters" / "claude-code" / "hooks"
        settings = tmp_path / "settings.json"
        _run_install_hooks(settings, hooks_dir)
        data = json.loads(settings.read_text())
        for event_entries in data["hooks"].values():
            for entry in event_entries:
                for hook in entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    assert "${CLAUDE_PLUGIN_ROOT}" not in cmd, \
                        f"Unresolved variable in hook command: {cmd!r}"

    def test_idempotent_no_duplicates(self, tmp_path: Path, repo_root: Path) -> None:
        hooks_dir = repo_root / "adapters" / "claude-code" / "hooks"
        settings = tmp_path / "settings.json"
        _run_install_hooks(settings, hooks_dir)
        _run_install_hooks(settings, hooks_dir)
        data = json.loads(settings.read_text())
        stop_cmds = [
            h["command"]
            for entry in data["hooks"].get("Stop", [])
            for h in entry.get("hooks", [])
        ]
        session_stop_count = sum(1 for c in stop_cmds if "session-stop.sh" in c)
        assert session_stop_count == 1, f"Expected 1 session-stop entry, got {session_stop_count}: {stop_cmds}"

    def test_updates_stale_hardcoded_path(self, tmp_path: Path, repo_root: Path) -> None:
        """If settings.json already has a session-stop.sh entry with wrong path, it gets updated."""
        hooks_dir = repo_root / "adapters" / "claude-code" / "hooks"
        settings = tmp_path / "settings.json"
        # Write settings with a stale hardcoded path
        settings.write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "matcher": "",
                    "hooks": [{
                        "type": "command",
                        "command": "bash /Users/otheruser/old-path/hooks/session-stop.sh",
                        "timeout": 10,
                    }]
                }]
            }
        }, indent=2))
        _run_install_hooks(settings, hooks_dir)
        data = json.loads(settings.read_text())
        stop_cmds = [
            h["command"]
            for entry in data["hooks"].get("Stop", [])
            for h in entry.get("hooks", [])
        ]
        assert all("otheruser" not in cmd for cmd in stop_cmds), \
            f"Stale path not updated: {stop_cmds}"
        assert any(str(hooks_dir) in cmd for cmd in stop_cmds), \
            f"Expected updated path {hooks_dir} in: {stop_cmds}"

    def test_preserves_unrelated_hooks(self, tmp_path: Path, repo_root: Path) -> None:
        hooks_dir = repo_root / "adapters" / "claude-code" / "hooks"
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "matcher": "",
                    "hooks": [{
                        "type": "command",
                        "command": "bash ~/.claude/hooks/clear-task.sh",
                        "timeout": 3,
                    }]
                }]
            }
        }, indent=2))
        _run_install_hooks(settings, hooks_dir)
        data = json.loads(settings.read_text())
        stop_cmds = [
            h["command"]
            for entry in data["hooks"].get("Stop", [])
            for h in entry.get("hooks", [])
        ]
        assert any("clear-task.sh" in cmd for cmd in stop_cmds), \
            f"Unrelated hook was removed: {stop_cmds}"


class TestNoHardcodedPathsInRepo:
    """Repo files must not contain hardcoded user home paths.

    Only git-tracked files are checked — .venv, caches, and build artefacts
    are excluded automatically because they are not committed.
    Test fixture paths using placeholder names like /Users/test/ are exempt.
    """

    # Placeholder names used in test fixtures / docs — not real usernames
    _FIXTURE_NAMES = frozenset({"test", "user", "username", "example", "admin", "root"})

    def _git_tracked_files(self, repo_root: Path):
        import subprocess
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        for rel in result.stdout.splitlines():
            yield repo_root / rel

    def test_no_hardcoded_user_home_in_source(self, repo_root: Path) -> None:
        import re
        pattern = re.compile(r'/(?:Users|home)/([A-Za-z0-9_.-]+)/')
        violations = []
        for fpath in self._git_tracked_files(repo_root):
            if not fpath.is_file():
                continue
            try:
                text = fpath.read_text(errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for m in pattern.finditer(line):
                    username = m.group(1)
                    if username.lower() in self._FIXTURE_NAMES:
                        continue  # known test-fixture placeholder
                    rel = fpath.relative_to(repo_root)
                    violations.append(f"{rel}:{lineno}: {line.strip()[:120]}")
        assert not violations, (
            "Hardcoded user home paths found in tracked repo files "
            "(use $HOME, relative paths, or config variables instead):\n"
            + "\n".join(violations)
        )
