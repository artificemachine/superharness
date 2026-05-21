"""Tests for engine.agent_memory — RED tests for Hermes self-improvement Iteration 1.

Agent-writable memory: two-tier (global + per-project), watcher injection
into dispatch context, agent append capability.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def agent_memory():
    from superharness.engine import agent_memory
    return agent_memory


# ── RED: memory file infrastructure ──────────────────────────────────────────

def test_global_memory_dir_created(agent_memory) -> None:
    """Global memory dir should exist at ~/.config/superharness/memory/"""
    gdir = agent_memory.global_memory_dir()
    assert gdir is not None
    assert os.path.isdir(gdir)


def test_project_memory_dir_created(agent_memory, tmp_path: Path) -> None:
    """Project memory dir should exist at .superharness/memory/"""
    pdir = agent_memory.project_memory_dir(str(tmp_path))
    assert os.path.isdir(pdir)


def test_global_memory_files_created(agent_memory) -> None:
    """Default memory files should exist in global dir."""
    gdir = agent_memory.ensure_global_memory()
    for fname in ("patterns.md", "pitfalls.md", "conventions.md"):
        fpath = os.path.join(gdir, fname)
        assert os.path.isfile(fpath), f"Missing {fpath}"


def test_project_memory_files_created(agent_memory, tmp_path: Path) -> None:
    """Default memory files should exist in project dir."""
    pdir = agent_memory.ensure_project_memory(str(tmp_path))
    for fname in ("conventions.md", "decisions.md"):
        fpath = os.path.join(pdir, fname)
        assert os.path.isfile(fpath), f"Missing {fpath}"


# ── RED: agent write capability ──────────────────────────────────────────────

def test_agent_appends_to_project_memory(agent_memory, tmp_path: Path) -> None:
    """Agent should be able to append a line to project memory file."""
    content = "2026-05-20: avoid pytest -n auto on macOS, it hangs\n"
    agent_memory.append(str(tmp_path), "conventions.md", content)
    fpath = os.path.join(agent_memory.project_memory_dir(str(tmp_path)), "conventions.md")
    saved = Path(fpath).read_text()
    assert "avoid pytest -n auto" in saved


def test_agent_appends_to_global_memory(agent_memory) -> None:
    """Agent should be able to append to global memory."""
    # We test in a temp override to avoid polluting real global memory
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        content = "2026-05-20: SIGKILL leaves stale watcher lock dirs\n"
        agent_memory.append_global_override(td, "pitfalls.md", content)
        fpath = os.path.join(td, "pitfalls.md")
        saved = Path(fpath).read_text()
        assert "SIGKILL leaves stale" in saved


# ── RED: context injection ───────────────────────────────────────────────────

def test_build_context_injects_memory(agent_memory, tmp_path: Path) -> None:
    """Context hint should include memory content when memory files exist."""
    # Write something to project memory
    agent_memory.append(str(tmp_path), "conventions.md",
                        "2026-05-20: this project uses ruff, not black\n")
    # Also write to global memory
    gdir = agent_memory.global_memory_dir()
    with open(os.path.join(gdir, "conventions.md"), "a") as f:
        f.write("2026-05-20: prefer uv over pip for package management\n")

    from superharness.engine.context_hint import build_context_hint
    task = {"id": "test.task", "acceptance_criteria": ["do the thing"]}
    hint = build_context_hint(str(tmp_path), task)

    assert "ruff, not black" in hint
    assert "uv over pip" in hint


def test_empty_memory_does_not_crash_context(agent_memory, tmp_path: Path) -> None:
    """Context hint should not crash when memory files are empty."""
    # Ensure dirs exist but files are empty (default state)
    agent_memory.project_memory_dir(str(tmp_path))

    from superharness.engine.context_hint import build_context_hint
    task = {"id": "test.task", "acceptance_criteria": []}
    hint = build_context_hint(str(tmp_path), task)
    assert isinstance(hint, str)  # does not crash


# ── RED: watcher reads memory on dispatch ────────────────────────────────────

def test_watcher_injects_memory_into_context(agent_memory, tmp_path: Path) -> None:
    """Watcher should inject memory content into dispatch context."""
    agent_memory.append(str(tmp_path), "conventions.md",
                        "2026-05-20: watcher integration test\n")

    from superharness.engine.agent_memory import get_dispatch_memory_context
    context = get_dispatch_memory_context(str(tmp_path))
    assert "watcher integration test" in context
    assert "conventions.md" not in context  # filenames not included
