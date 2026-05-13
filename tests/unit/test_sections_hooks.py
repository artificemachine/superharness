"""RED tests for the hooks section (ui/sections/hooks.py) — stale worktree detection."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


def _scan(settings_path: Path) -> list[str]:
    from superharness.ui.sections.hooks import scan_stale_worktree_paths
    return scan_stale_worktree_paths(settings_path)


def _worktree_base() -> str:
    return os.path.join(tempfile.gettempdir(), "superharness-worktrees")


def _settings_with_hook_command(cmd: str, tmp_path: Path) -> Path:
    """Write a minimal settings.json with a single hook entry."""
    data = {
        "hooks": {
            "PreToolUse": [{"matcher": "*", "command": cmd}]
        }
    }
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------


def test_hooks_section_returns_no_stale_when_settings_missing(tmp_path):
    """scan_stale_worktree_paths returns [] when settings.json does not exist."""
    missing = tmp_path / "nonexistent_settings.json"
    assert _scan(missing) == []


def test_hooks_section_detects_stale_worktree_path_not_on_disk(tmp_path):
    """A hook command referencing a worktree path that is NOT on disk → stale."""
    worktree_base = _worktree_base()
    stale_path = os.path.join(worktree_base, "task-abc123", "session-exit.sh")
    # Ensure the path does not exist
    assert not os.path.exists(stale_path)

    settings = _settings_with_hook_command(f"bash {stale_path}", tmp_path)
    stale = _scan(settings)
    assert stale_path in stale


def test_hooks_section_ignores_paths_that_exist_on_disk(tmp_path):
    """A hook command referencing an existing path is NOT reported as stale."""
    worktree_base = _worktree_base()
    # Create an actual directory that looks like a worktree slot
    live_dir = Path(worktree_base) / "live-slot"
    live_dir.mkdir(parents=True, exist_ok=True)
    script = live_dir / "hook.sh"
    script.write_text("#!/bin/bash\n")

    settings = _settings_with_hook_command(f"bash {script}", tmp_path)
    stale = _scan(settings)
    assert str(script) not in stale

    # Cleanup
    import shutil
    shutil.rmtree(str(live_dir), ignore_errors=True)


def test_hooks_section_handles_non_worktree_commands_cleanly(tmp_path):
    """Hook commands that don't reference the worktree prefix are ignored."""
    settings = _settings_with_hook_command("/usr/local/bin/my-hook.sh", tmp_path)
    stale = _scan(settings)
    assert stale == []


def test_hooks_section_handles_malformed_settings_json(tmp_path):
    """Malformed JSON in settings.json must not raise — returns []."""
    bad = tmp_path / "settings.json"
    bad.write_text("{ not valid json }")
    assert _scan(bad) == []


def test_hooks_section_reports_warning_when_stale(tmp_path, capsys, monkeypatch):
    """run() prints a warning when stale worktree paths are found."""
    from superharness.ui.sections.hooks import run

    worktree_base = _worktree_base()
    stale_path = os.path.join(worktree_base, "stale-task-xyz", "session-exit.sh")
    assert not os.path.exists(stale_path)

    settings = _settings_with_hook_command(f"bash {stale_path}", tmp_path)
    # Override the default settings path via monkeypatching
    monkeypatch.setenv("SUPERHARNESS_CLAUDE_SETTINGS", str(settings))

    sh = tmp_path / ".superharness"
    sh.mkdir()

    run(tmp_path, non_interactive=True)

    out = capsys.readouterr().out
    assert "stale" in out.lower() or "worktree-gc" in out.lower() or "worktree" in out.lower()


def test_hooks_section_no_warning_when_no_stale(tmp_path, capsys, monkeypatch):
    """run() does not warn when there are no stale paths."""
    from superharness.ui.sections.hooks import run

    settings = _settings_with_hook_command("/usr/local/bin/safe-hook.sh", tmp_path)
    monkeypatch.setenv("SUPERHARNESS_CLAUDE_SETTINGS", str(settings))

    (tmp_path / ".superharness").mkdir()
    run(tmp_path, non_interactive=True)

    out = capsys.readouterr().out
    # Should not yell about stale worktrees
    assert "stale" not in out.lower() or "worktree-gc" not in out.lower()
