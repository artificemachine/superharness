"""Hooks section — stale worktree path detection + global CLAUDE.md update."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from superharness.ui.prompts import print_header, print_info, print_warning

# Worktree temp prefix — must match commands/worktree_gc.py:WORKTREE_BASE
_WORKTREE_BASE = os.path.join(tempfile.gettempdir(), "superharness-worktrees")


def _default_settings_path() -> Path:
    """Return path to Claude Code settings.json, overridable via env var for tests."""
    override = os.environ.get("SUPERHARNESS_CLAUDE_SETTINGS")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "settings.json"


def scan_stale_worktree_paths(settings_json_path: Path) -> list[str]:
    """Return worktree paths in hook commands that no longer exist on disk.

    Scans all hook event lists in settings.json for command strings that
    reference paths under the superharness-worktrees temp directory. Any
    such path that is no longer present on disk is classified as stale.

    Args:
        settings_json_path: Path to ~/.claude/settings.json (or test override).

    Returns:
        List of stale path strings (may be empty). Never raises.
    """
    if not settings_json_path.exists():
        return []

    try:
        data = json.loads(settings_json_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    stale: list[str] = []
    hooks_block = data.get("hooks", {})
    if not isinstance(hooks_block, dict):
        return []

    for event_entries in hooks_block.values():
        if not isinstance(event_entries, list):
            continue
        for entry in event_entries:
            if not isinstance(entry, dict):
                continue
            cmd = entry.get("command", "")
            if not isinstance(cmd, str):
                continue
            for token in cmd.split():
                if token.startswith(_WORKTREE_BASE) and not os.path.exists(token):
                    stale.append(token)

    return stale


def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Hooks section: detect stale worktree paths and update global CLAUDE.md."""
    print_header("Hooks")

    # 1. Scan for stale worktree paths in Claude Code settings.json
    settings_path = _default_settings_path()
    stale = scan_stale_worktree_paths(settings_path)

    if stale:
        print_warning(
            f"{len(stale)} stale worktree path(s) found in {settings_path}:"
        )
        for path in stale:
            print_warning(f"  {path}")
        print_warning("Run: shux worktree-gc  to clean orphaned worktrees.")
    else:
        print_info("No stale worktree paths detected in Claude Code settings.")

    # 2. Ensure global CLAUDE.md has the superharness section
    try:
        from superharness.commands.onboard import _step_global_claude_md
        _step_global_claude_md({})
    except Exception as exc:  # pragma: no cover
        print_info(f"Note: could not update global CLAUDE.md: {exc}")
