"""Tests for MCP skills tool — Iteration 8."""
from __future__ import annotations

import pytest
from pathlib import Path


def _make_manifest(manifests_dir: Path, name: str, tags: list[str]) -> None:
    manifests_dir.mkdir(parents=True, exist_ok=True)
    content = f"name: {name}\nversion: \"1\"\ndescription: \"{name} adapter\"\ntags: [{', '.join(tags)}]\n"
    (manifests_dir / f"{name}.yaml").write_text(content)


def test_get_skills_returns_all_manifests(tmp_path):
    from superharness.mcp.tools.skills import get_skills
    manifests_dir = tmp_path / "adapter_manifests"
    _make_manifest(manifests_dir, "claude-code", ["coding", "planning"])
    _make_manifest(manifests_dir, "codex-cli", ["coding", "refactor"])
    skills = get_skills(manifests_dir=str(manifests_dir))
    assert len(skills) == 2


def test_get_skills_filter_by_tag(tmp_path):
    from superharness.mcp.tools.skills import get_skills
    manifests_dir = tmp_path / "adapter_manifests"
    _make_manifest(manifests_dir, "claude-code", ["coding", "planning"])
    _make_manifest(manifests_dir, "codex-cli", ["coding", "refactor"])
    _make_manifest(manifests_dir, "gemini-cli", ["research"])
    skills = get_skills(manifests_dir=str(manifests_dir), tag="planning")
    assert len(skills) == 1
    assert skills[0]["name"] == "claude-code"


def test_get_skills_returns_empty_for_unknown_tag(tmp_path):
    from superharness.mcp.tools.skills import get_skills
    manifests_dir = tmp_path / "adapter_manifests"
    _make_manifest(manifests_dir, "claude-code", ["coding"])
    skills = get_skills(manifests_dir=str(manifests_dir), tag="zzz-unknown")
    assert skills == []


def test_get_skills_empty_dir(tmp_path):
    from superharness.mcp.tools.skills import get_skills
    manifests_dir = tmp_path / "adapter_manifests"
    manifests_dir.mkdir()
    skills = get_skills(manifests_dir=str(manifests_dir))
    assert skills == []


def test_get_skills_missing_dir_returns_empty(tmp_path):
    from superharness.mcp.tools.skills import get_skills
    skills = get_skills(manifests_dir=str(tmp_path / "nonexistent"))
    assert skills == []
