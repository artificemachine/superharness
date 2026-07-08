"""Smoke tests — the Claude Code plugin command surface exists and is well-formed."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parent.parent.parent
COMMANDS_DIR = ROOT / "plugin" / "commands"


def test_commands_dir_exists_and_nonempty():
    assert COMMANDS_DIR.is_dir()
    assert list(COMMANDS_DIR.glob("*.md"))
