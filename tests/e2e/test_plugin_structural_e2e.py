"""Structural e2e tests — verify the whole Claude Code plugin resolves consistently.

Claude Code's actual /plugin marketplace add + /plugin install flow is interactive-only
and cannot be driven by an automated test. These tests validate the assembled system's
structure instead: manifests cross-reference correctly and contain no unsafe paths.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent.parent.parent
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"


def _marketplace_data() -> dict:
    return json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))


def test_marketplace_source_directory_exists():
    data = _marketplace_data()
    for entry in data["plugins"]:
        source_dir = ROOT / entry["source"]
        assert source_dir.is_dir(), f"source {entry['source']} does not exist"


def test_plugin_source_contains_at_least_one_surface():
    data = _marketplace_data()
    for entry in data["plugins"]:
        source_dir = ROOT / entry["source"]
        surfaces = ["commands", "skills", "agents"]
        assert any((source_dir / surface).is_dir() and list((source_dir / surface).iterdir()) for surface in surfaces)


def test_plugin_json_name_matches_marketplace_entry_name():
    data = _marketplace_data()
    for entry in data["plugins"]:
        plugin_json = ROOT / entry["source"] / ".claude-plugin" / "plugin.json"
        plugin_data = json.loads(plugin_json.read_text(encoding="utf-8"))
        assert plugin_data["name"] == entry["name"]


def test_no_absolute_or_traversal_paths_in_manifests():
    data = _marketplace_data()
    for entry in data["plugins"]:
        source = entry["source"]
        assert ".." not in source
        assert not source.startswith("/")

    for entry in data["plugins"]:
        plugin_json = ROOT / entry["source"] / ".claude-plugin" / "plugin.json"
        plugin_data = json.loads(plugin_json.read_text(encoding="utf-8"))
        for value in plugin_data.values():
            if isinstance(value, str) and ("/" in value or "\\" in value):
                assert ".." not in value
                assert not value.startswith("/Users") and not value.startswith("/home")


def test_readme_documents_plugin_install():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/plugin marketplace add artificemachine/superharness" in readme
