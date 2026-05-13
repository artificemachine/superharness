"""Tests for shux install-hooks — writes portable hook entries to ~/.claude/settings.json."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from superharness.commands.install_hooks import _find_hooks_dir, _is_ephemeral
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


class TestEphemeralGuard:
    """_is_ephemeral() and _find_hooks_dir() must reject temp-directory paths.

    When Claude Code runs install-hooks from a git worktree created under /tmp,
    baking that path into settings.json produces a dead reference the moment
    the worktree is deleted.  The guard prevents this.
    """

    def test_is_ephemeral_returns_true_for_tmp(self) -> None:
        tmp = Path(tempfile.gettempdir())
        assert _is_ephemeral(tmp / "some-worktree" / "src")

    def test_is_ephemeral_returns_false_for_home(self, repo_root: Path) -> None:
        assert not _is_ephemeral(repo_root / "adapters" / "claude-code" / "hooks")

    def test_find_hooks_dir_raises_when_module_is_in_tmp(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """_find_hooks_dir() must raise FileNotFoundError if both candidate
        paths resolve into the system temp directory.

        We simulate a worktree install by monkeypatching __file__ inside the
        install_hooks module to a path under tmp_path (which itself lives under
        the system tempdir because pytest uses it).
        """
        import superharness.commands.install_hooks as mod

        fake_file = tmp_path / "superharness" / "commands" / "install_hooks.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()

        # Plant a fake hooks dir that would match the in-package candidate,
        # but it is under tmp so the guard must reject it.
        fake_hooks = tmp_path / "superharness" / "adapters" / "claude-code" / "hooks"
        fake_hooks.mkdir(parents=True)

        monkeypatch.setattr(mod, "__file__", str(fake_file))
        with pytest.raises(FileNotFoundError, match="not found"):
            _find_hooks_dir()

    def test_find_hooks_dir_succeeds_from_real_repo(self, repo_root: Path) -> None:
        """_find_hooks_dir() must succeed when called from the real (non-ephemeral) repo."""
        hooks_dir = _find_hooks_dir()
        assert hooks_dir.is_dir()
        assert not _is_ephemeral(hooks_dir)


class TestNoHardcodedPathsInRepo:
    """Repo files must not contain hardcoded user home paths.

    Only git-tracked files are checked — .venv, caches, and build artefacts
    are excluded automatically because they are not committed.
    Test fixture paths using placeholder names like /Users/test/ are exempt.
    .superharness/ is excluded: it is operational protocol state that naturally
    contains absolute project_path values set at task-creation time.
    """

    # Placeholder names used in test fixtures / docs — not real usernames
    _FIXTURE_NAMES = frozenset({"test", "user", "username", "example", "admin", "root", "yourname", "otheruser", "testuser", "alice", "bob"})

    # Directories containing operational/protocol state — absolute paths are expected there
    _SKIP_DIRS = frozenset({".superharness"})

    def _git_tracked_files(self, repo_root: Path):
        import subprocess
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        for rel in result.stdout.splitlines():
            # Skip operational state directories
            parts = Path(rel).parts
            if parts and parts[0] in self._SKIP_DIRS:
                continue
            yield repo_root / rel

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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
