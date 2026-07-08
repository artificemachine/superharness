"""Smoke tests — the Claude Code plugin command surface exists and is well-formed."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parent.parent.parent
COMMANDS_DIR = ROOT / "plugin" / "commands"


def _read_frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", f"{path} missing YAML frontmatter"
    end = lines[1:].index("---") + 1
    return yaml.safe_load("\n".join(lines[1:end])) or {}


def test_commands_dir_exists_and_nonempty():
    assert COMMANDS_DIR.is_dir()
    assert list(COMMANDS_DIR.glob("*.md"))


@pytest.mark.parametrize(
    "path", sorted(COMMANDS_DIR.glob("*.md")) if COMMANDS_DIR.is_dir() else [], ids=lambda p: p.name
)
def test_every_command_file_has_valid_frontmatter(path):
    fm = _read_frontmatter(path)
    assert fm.get("description")


@pytest.mark.parametrize(
    "path", sorted(COMMANDS_DIR.glob("*.md")) if COMMANDS_DIR.is_dir() else [], ids=lambda p: p.name
)
def test_every_command_file_has_argument_hint_or_none(path):
    fm = _read_frontmatter(path)
    if "argument-hint" in fm:
        assert isinstance(fm["argument-hint"], str)


def test_command_count_matches_seven():
    assert len(list(COMMANDS_DIR.glob("*.md"))) == 7
