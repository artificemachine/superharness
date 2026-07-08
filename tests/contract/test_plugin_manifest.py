"""Contract tests — verify the Claude Code plugin manifests are well-formed.

Covers:
- .claude-plugin/marketplace.json is valid JSON with a superharness plugin entry
- plugin/.claude-plugin/plugin.json is valid JSON with required fields
- plugin/commands/shux.md has valid frontmatter
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent.parent
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_JSON = ROOT / "plugin" / ".claude-plugin" / "plugin.json"
SHUX_COMMAND = ROOT / "plugin" / "commands" / "shux.md"


def _read_frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", f"{path} missing YAML frontmatter"
    end = lines[1:].index("---") + 1
    return yaml.safe_load("\n".join(lines[1:end])) or {}


def test_marketplace_json_is_valid_json():
    data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_marketplace_json_has_superharness_plugin_entry():
    data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    plugins = data["plugins"]
    assert len(plugins) == 1
    entry = plugins[0]
    assert entry["name"] == "superharness"
    assert entry["source"] == "./plugin"


def test_plugin_json_is_valid_json_and_required_fields():
    data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "superharness"
    assert data["description"]


def test_shux_command_file_has_frontmatter():
    fm = _read_frontmatter(SHUX_COMMAND)
    assert fm.get("description")
