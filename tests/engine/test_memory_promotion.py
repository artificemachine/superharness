"""Tests for memory auto-promotion — RED tests for Hermes self-improvement Iteration 3.

Promote project memory patterns to global memory after N occurrences.
Cross-project learning: what project A learns, project B automatically benefits from.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def agent_memory():
    from superharness.engine import agent_memory
    return agent_memory


# ── RED: pattern counting ─────────────────────────────────────────────────────

def test_count_pattern_occurrences(agent_memory, tmp_path: Path) -> None:
    """Should count how many times a pattern appears in a memory file."""
    pdir = agent_memory.ensure_project_memory(str(tmp_path))

    # Write the same pattern 3 times
    pattern = "2026-05-20: avoid pytest -n auto on macOS, it hangs\n"
    for _ in range(3):
        agent_memory.append(str(tmp_path), "pitfalls.md", pattern)

    from superharness.engine.agent_memory import _count_pattern_occurrences
    count = _count_pattern_occurrences(pdir, "pitfalls.md", pattern.strip())
    assert count == 3


def test_unique_patterns_not_overcounted(agent_memory, tmp_path: Path) -> None:
    """Different patterns should not be counted together."""
    pdir = agent_memory.ensure_project_memory(str(tmp_path))

    agent_memory.append(str(tmp_path), "pitfalls.md", "avoid pytest -n auto")
    agent_memory.append(str(tmp_path), "pitfalls.md", "use uv instead of pip")

    from superharness.engine.agent_memory import _count_pattern_occurrences
    assert _count_pattern_occurrences(pdir, "pitfalls.md", "avoid pytest -n auto") == 1
    assert _count_pattern_occurrences(pdir, "pitfalls.md", "use uv instead of pip") == 1


# ── RED: promotion rule ───────────────────────────────────────────────────────

def test_pattern_not_promoted_below_threshold(agent_memory, tmp_path: Path) -> None:
    """Pattern with <3 occurrences should NOT be promoted."""
    pdir = agent_memory.ensure_project_memory(str(tmp_path))
    pattern = "test-unique-xyz-2026: avoid running database migrations on weekends"

    # Write only 2 occurrences
    for _ in range(2):
        agent_memory.append(str(tmp_path), "pitfalls.md", pattern)

    from superharness.engine.agent_memory import promote_to_global

    with tempfile.TemporaryDirectory() as global_override:
        result = promote_to_global(
            str(tmp_path), "pitfalls.md", global_override=global_override
        )
        assert result is False  # not enough occurrences


def test_pattern_promoted_to_global(agent_memory, tmp_path: Path) -> None:
    """Pattern with ≥3 occurrences should be promoted to global memory."""
    pattern = "avoid pytest -n auto on macOS, it hangs"

    # Write 3 occurrences
    for _ in range(3):
        agent_memory.append(str(tmp_path), "pitfalls.md", pattern)

    from superharness.engine.agent_memory import promote_to_global

    with tempfile.TemporaryDirectory() as global_override:
        result = promote_to_global(
            str(tmp_path), "pitfalls.md", global_override=global_override
        )
        assert result is True

        # Verify it was written to global
        gpath = os.path.join(global_override, "pitfalls.md")
        assert os.path.isfile(gpath)
        content = Path(gpath).read_text()
        assert "avoid pytest -n auto" in content


def test_project_specific_pattern_not_promoted(agent_memory, tmp_path: Path) -> None:
    """Pattern containing project-specific paths should NOT be promoted."""
    project_path = str(tmp_path)
    # Pattern references a file in THIS project
    pattern = f"avoid editing {project_path}/src/config.py directly"

    for _ in range(3):
        agent_memory.append(project_path, "pitfalls.md", pattern)

    from superharness.engine.agent_memory import promote_to_global

    with tempfile.TemporaryDirectory() as global_override:
        result = promote_to_global(
            project_path, "pitfalls.md", global_override=global_override
        )
        assert result is False  # project-specific, not promoted


def test_already_promoted_pattern_not_duplicated(agent_memory, tmp_path: Path) -> None:
    """Already-promoted patterns should not be duplicated in global memory."""
    pattern = "2026-05-20: always use uv, never pip"

    for _ in range(3):
        agent_memory.append(str(tmp_path), "pitfalls.md", pattern)

    from superharness.engine.agent_memory import promote_to_global

    with tempfile.TemporaryDirectory() as global_override:
        # First promotion
        result1 = promote_to_global(
            str(tmp_path), "pitfalls.md", global_override=global_override
        )
        assert result1 is True

        # Second promotion attempt — should be no-op
        result2 = promote_to_global(
            str(tmp_path), "pitfalls.md", global_override=global_override
        )
        assert result2 is False  # already exists


# ── RED: cross-project learning ───────────────────────────────────────────────

def test_cross_project_injects_global_memory(tmp_path: Path) -> None:
    """When project A promotes a pattern, project B's dispatch should include it."""
    from superharness.engine.agent_memory import (
        ensure_global_memory,
        get_dispatch_memory_context,
    )

    # Write to global memory (simulating project A's promotion)
    gdir = ensure_global_memory()
    gpath = os.path.join(gdir, "pitfalls.md")
    with open(gpath, "a") as f:
        f.write("2026-05-20: SIGKILL leaves stale watcher lock dirs\n")

    # Project B's dispatch context should include this
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    context = get_dispatch_memory_context(str(project_b))
    assert "SIGKILL leaves stale" in context
    assert "Global Learning" in context
