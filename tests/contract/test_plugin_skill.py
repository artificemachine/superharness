"""Contract tests — the superharness skill exists and routes to every curated command."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent.parent
SKILL_MD = ROOT / "plugin" / "skills" / "superharness" / "SKILL.md"

NAMED_COMMANDS = [
    "shux-contract",
    "shux-status",
    "shux-delegate",
    "shux-doctor",
    "shux-close",
]


def _read_frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", f"{path} missing YAML frontmatter"
    end = lines[1:].index("---") + 1
    return yaml.safe_load("\n".join(lines[1:end])) or {}


def test_skill_md_exists_at_expected_path():
    assert SKILL_MD.is_file()


def test_skill_md_has_name_and_description_frontmatter():
    fm = _read_frontmatter(SKILL_MD)
    assert fm.get("name")
    assert fm.get("description")


def test_skill_name_matches_directory():
    fm = _read_frontmatter(SKILL_MD)
    assert fm["name"] == SKILL_MD.parent.name == "superharness"


def test_skill_description_mentions_all_five_named_commands():
    fm = _read_frontmatter(SKILL_MD)
    description = fm["description"]
    for command in NAMED_COMMANDS:
        assert command in description, f"{command} missing from skill description"
