"""Tests for engine/smart_dispatch.py — Phase 4 smart agent routing."""
from __future__ import annotations

import pytest
from pathlib import Path


def _make_manifest(manifests_dir: Path, name: str, tags: list[str]) -> None:
    manifests_dir.mkdir(parents=True, exist_ok=True)
    tags_str = ", ".join(f'"{t}"' for t in tags)
    content = (
        f"name: {name}\n"
        f"version: \"1\"\n"
        f"description: \"{name} adapter\"\n"
        f"tags: [{tags_str}]\n"
    )
    (manifests_dir / f"{name}.yaml").write_text(content)


# ---------------------------------------------------------------------------
# No manifests — fallback to owner
# ---------------------------------------------------------------------------

def test_choose_agent_no_manifests_returns_owner(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent
    task = {"id": "t1", "title": "fix bug", "owner": "codex-cli"}
    result = choose_agent(task, manifests_dir=str(tmp_path / "nonexistent"))
    assert result == "codex-cli"


def test_choose_agent_no_manifests_no_owner_returns_fallback(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent
    task = {"id": "t1", "title": "fix bug"}
    result = choose_agent(task, manifests_dir=str(tmp_path / "nonexistent"))
    assert result == "claude-code"


# ---------------------------------------------------------------------------
# Skill match
# ---------------------------------------------------------------------------

def test_choose_agent_picks_best_match(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent
    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "claude-code", ["planning", "coding", "docs"])
    _make_manifest(mdir, "codex-cli", ["refactor", "coding"])

    task = {"id": "t1", "title": "write docs and plan", "owner": "codex-cli"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "claude-code"


def test_choose_agent_returns_owner_when_no_match(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent
    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "claude-code", ["coding"])
    _make_manifest(mdir, "codex-cli", ["refactor"])

    task = {"id": "t1", "title": "quantum entanglement research", "owner": "gemini-cli"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "gemini-cli"


def test_choose_agent_exact_tag_match(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent
    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "codex-cli", ["refactor"])
    _make_manifest(mdir, "claude-code", ["planning"])

    task = {"id": "t1", "title": "refactor the auth module", "owner": "claude-code"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "codex-cli"


# ---------------------------------------------------------------------------
# Task keyword extraction
# ---------------------------------------------------------------------------

def test_task_keywords_from_tags_list(tmp_path):
    from superharness.engine.smart_dispatch import _task_keywords
    task = {"title": "implement feature", "tags": ["security", "auth"]}
    kw = _task_keywords(task)
    assert "security" in kw
    assert "auth" in kw
    assert "implement" in kw


def test_task_keywords_empty_task():
    from superharness.engine.smart_dispatch import _task_keywords
    assert _task_keywords({}) == set()


# ---------------------------------------------------------------------------
# Score function
# ---------------------------------------------------------------------------

def test_score_zero_when_no_overlap():
    from superharness.engine.smart_dispatch import _score
    manifest = {"name": "codex-cli", "tags": ["refactor", "test"]}
    assert _score(manifest, {"planning", "docs"}) == 0


def test_score_counts_matches():
    from superharness.engine.smart_dispatch import _score
    manifest = {"name": "claude-code", "tags": ["planning", "docs", "coding"]}
    assert _score(manifest, {"planning", "docs", "security"}) == 2


# ---------------------------------------------------------------------------
# Empty task (no keywords) — falls back to owner
# ---------------------------------------------------------------------------

def test_choose_agent_empty_task_returns_owner(tmp_path):
    from superharness.engine.smart_dispatch import choose_agent
    mdir = tmp_path / "manifests"
    _make_manifest(mdir, "claude-code", ["coding"])
    task = {"owner": "codex-cli"}
    result = choose_agent(task, manifests_dir=str(mdir))
    assert result == "codex-cli"
