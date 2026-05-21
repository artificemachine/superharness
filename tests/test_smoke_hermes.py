"""E2E smoke tests for Hermes self-improvement mechanisms.

Verifies the full cycle: agent writes memory → watcher injects → loop detected →
task blocked → pattern promoted → cross-project learning.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


# ── Memory Cycle: agent writes → watcher injects → context includes it ─────

def test_memory_cycle_end_to_end(tmp_path: Path) -> None:
    """Full cycle: agent writes memory, watcher injects into dispatch context."""
    from superharness.engine.agent_memory import (
        append,
        ensure_project_memory,
        get_dispatch_memory_context,
    )

    project_dir = str(tmp_path)
    ensure_project_memory(project_dir)

    # Agent writes a learning
    append(project_dir, "conventions.md", "always run tests before committing")
    append(project_dir, "decisions.md", "chose SQLite for state persistence")

    # Watcher reads memory context for next dispatch
    context = get_dispatch_memory_context(project_dir)

    assert "always run tests before committing" in context
    assert "chose SQLite for state persistence" in context
    assert "Project Memory" in context


def test_memory_context_injected_into_hint(tmp_path: Path) -> None:
    """Memory context appears in build_context_hint output."""
    from superharness.engine.agent_memory import append, ensure_project_memory
    from superharness.engine.context_hint import build_context_hint

    project_dir = str(tmp_path)
    ensure_project_memory(project_dir)
    append(project_dir, "conventions.md", "this project uses ruff, not black")

    task = {"id": "test.e2e", "acceptance_criteria": ["format code consistently"]}
    hint = build_context_hint(project_dir, task)

    assert "ruff, not black" in hint


# ── Loop Guard Cycle: log with loops → detected → task blocked ────────────

def test_loop_guard_cycle_end_to_end() -> None:
    """Full cycle: create log with loops, detect, guard escalates to block."""
    from superharness.engine.loop_detector import detect_loop, LoopGuard

    with tempfile.TemporaryDirectory() as td:
        # Create a log file simulating an agent stuck in a loop
        log_path = os.path.join(td, "agent-loop.log")
        log_content = "\n".join(["Tool: read_file"] * 6)
        Path(log_path).write_text(log_content)

        # Watcher detects loop in log
        result = detect_loop(log_path)
        assert result["loop_detected"] is True
        assert result["block"] is True
        assert result["pattern"] == "read_file"

        # LoopGuard escalates across cycles
        guard = LoopGuard(td)
        warn_result = {
            "loop_detected": True, "warn": True, "block": False,
            "failure_loop": False, "pattern": "grep", "count": 3,
            "reason": "grep called 3 consecutive times",
        }

        # Cycle 1: warn
        a1 = guard.check("task-loop-1", warn_result)
        assert a1["action"] == "warn"

        # Cycle 2: warn
        a2 = guard.check("task-loop-1", warn_result)
        assert a2["action"] == "warn"

        # Cycle 3: block (escalation)
        a3 = guard.check("task-loop-1", warn_result)
        assert a3["action"] == "block"

        # Verify guard state is persisted
        guard2 = LoopGuard(td)
        state = guard2._state
        assert "task-loop-1" not in state  # popped after block


def test_clean_log_does_not_trigger_guard() -> None:
    """Normal log (no loops) should not trigger the guard."""
    from superharness.engine.loop_detector import detect_loop, LoopGuard

    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "normal.log")
        log_content = "Tool: read_file\nTool: grep\nTool: write\nTool: test\n"
        Path(log_path).write_text(log_content)

        result = detect_loop(log_path)
        assert result["loop_detected"] is False

        guard = LoopGuard(td)
        action = guard.check("task-clean", result)
        assert action["action"] == "allow"


# ── Promotion Cycle: project → global → cross-project learning ─────────────

def test_promotion_cycle_end_to_end(tmp_path: Path) -> None:
    """Full cycle: project A learns pattern → promoted → project B sees it."""
    from superharness.engine.agent_memory import (
        append,
        ensure_project_memory,
        promote_to_global,
        get_dispatch_memory_context,
    )

    # Project A discovers a pattern and writes it 3 times
    project_a = tmp_path / "project_a"
    project_a.mkdir()
    ensure_project_memory(str(project_a))

    pattern = "2026-05-20: SIGKILL on macOS leaves stale watcher lock dirs"
    for _ in range(3):
        append(str(project_a), "pitfalls.md", pattern)

    # Promote to global
    with tempfile.TemporaryDirectory() as global_override:
        result = promote_to_global(
            str(project_a), "pitfalls.md", global_override=global_override
        )
        assert result is True

        # Verify it's in global memory
        gpath = os.path.join(global_override, "pitfalls.md")
        assert os.path.isfile(gpath)
        assert "SIGKILL on macOS" in Path(gpath).read_text()

        # Project B should now see this via global memory injection
        # (even though project B never encountered this pattern)
        project_b = tmp_path / "project_b"
        project_b.mkdir()

        # Simulate watcher injecting global memory into project B's dispatch
        # Use a monkeypatched global dir
        import superharness.engine.agent_memory as am
        original = am.GLOBAL_MEMORY_DIR
        try:
            am.GLOBAL_MEMORY_DIR = global_override
            context = get_dispatch_memory_context(str(project_b))
            assert "SIGKILL on macOS" in context
            assert "Global Learning" in context
        finally:
            am.GLOBAL_MEMORY_DIR = original


def test_promotion_excludes_project_specific_patterns(tmp_path: Path) -> None:
    """Patterns referencing local paths should not be promoted to global."""
    from superharness.engine.agent_memory import (
        append,
        ensure_project_memory,
        promote_to_global,
    )

    project_dir = str(tmp_path)
    ensure_project_memory(project_dir)

    # Pattern with project-specific path
    local_pattern = f"avoid editing {project_dir}/src/config.py directly"
    for _ in range(3):
        append(project_dir, "pitfalls.md", local_pattern)

    with tempfile.TemporaryDirectory() as global_override:
        result = promote_to_global(
            project_dir, "pitfalls.md", global_override=global_override
        )
        assert result is False  # project-specific, not promoted


# ── Integration: all mechanisms work together ───────────────────────────────

def test_full_self_improvement_cycle(tmp_path: Path) -> None:
    """End-to-end: agent writes → watcher detects → promotes → cross-project."""
    from superharness.engine.agent_memory import (
        append,
        ensure_project_memory,
        promote_to_global,
        get_dispatch_memory_context,
    )
    from superharness.engine.loop_detector import detect_loop, LoopGuard

    project_dir = str(tmp_path)

    # 1. Agent writes to memory
    ensure_project_memory(project_dir)
    append(project_dir, "pitfalls.md", "never use subprocess with shell=True")

    # 2. Simulate tool loop detection
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("\n".join(["Tool: subprocess"] * 5))
        log_path = f.name
    try:
        result = detect_loop(log_path)
        assert result["loop_detected"] is True

        guard = LoopGuard(str(tmp_path))
        action = guard.check("task-integration", result)
        assert action["action"] == "block"

        # Agent writes another learning about the blocked pattern
        append(project_dir, "pitfalls.md",
               "subprocess called 5 consecutive times — blocked by watcher")
        append(project_dir, "pitfalls.md",
               "subprocess called 5 consecutive times — blocked by watcher")
        append(project_dir, "pitfalls.md",
               "subprocess called 5 consecutive times — blocked by watcher")

        # 3. Promote to global (3 occurrences)
        with tempfile.TemporaryDirectory() as global_override:
            result = promote_to_global(
                project_dir, "pitfalls.md", global_override=global_override
            )
            assert result is True

            # 4. Cross-project: another project sees the promoted pattern
            import superharness.engine.agent_memory as am
            original = am.GLOBAL_MEMORY_DIR
            try:
                am.GLOBAL_MEMORY_DIR = global_override
                project_b = tmp_path / "project_b"
                project_b.mkdir()
                context = get_dispatch_memory_context(str(project_b))
                assert "subprocess" in context
                assert "Global Learning" in context
            finally:
                am.GLOBAL_MEMORY_DIR = original
    finally:
        os.unlink(log_path)


def test_cross_project_promotion_multiple_projects(tmp_path: Path) -> None:
    """Pattern seen once each across 3 different projects should promote."""
    from superharness.engine.agent_memory import (
        append, ensure_project_memory, _count_pattern_across_sibling_projects,
        PROMOTION_THRESHOLD, promote_to_global,
    )

    pattern = "2026-05-20: cross-project pattern — use async/await for I/O"

    # 3 projects each see the same pattern once
    for i in range(PROMOTION_THRESHOLD):
        proj = tmp_path / f"project_{i}"
        proj.mkdir()
        ensure_project_memory(str(proj))
        append(str(proj), "pitfalls.md", pattern)

    # Cross-project sibling count should be 3 (3 sibling projects with pattern)
    proj_a = tmp_path / "project_0"
    total = _count_pattern_across_sibling_projects(str(proj_a), "pitfalls.md", pattern)
    assert total >= PROMOTION_THRESHOLD, f"Expected >=3 across siblings, got {total}"

    # Promotion — use real global dir via monkeypatch to avoid pollution
    import superharness.engine.agent_memory as am
    with tempfile.TemporaryDirectory() as global_override:
        original = am.GLOBAL_MEMORY_DIR
        try:
            am.GLOBAL_MEMORY_DIR = global_override
            result = promote_to_global(str(proj_a), "pitfalls.md")
            assert result is True, f"Cross-project promotion should work (count={total})"
        finally:
            am.GLOBAL_MEMORY_DIR = original
