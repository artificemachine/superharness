"""Tests for tool-loop guardrails — RED tests for Hermes self-improvement Iteration 2.

Wire detect_loop + LoopGuard into watcher log analyzer.
When a tool loop is detected, escalate task to blocked.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ── RED: detect_loop on launcher log ──────────────────────────────────────────

def test_detect_loop_finds_error_loop() -> None:
    """detect_loop should detect same tool erroring 3x consecutively."""
    from superharness.engine.loop_detector import detect_loop

    log_content = """Tool: read_file
Tool error: read_file — FileNotFoundError
Tool: read_file
Tool error: read_file — FileNotFoundError
Tool: read_file
Tool error: read_file — FileNotFoundError
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(log_content)
        log_path = f.name

    try:
        result = detect_loop(log_path)
        assert result["loop_detected"] is True
        assert result["failure_loop"] is True
        assert result["block"] is True
        assert result["pattern"] == "read_file"
        assert "3 consecutive times" in result["reason"]
    finally:
        os.unlink(log_path)


def test_detect_loop_finds_repetition_loop() -> None:
    """detect_loop should detect same tool called 5x consecutively."""
    from superharness.engine.loop_detector import detect_loop

    log_content = "\n".join(["Tool: grep"] * 5)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(log_content)
        log_path = f.name

    try:
        result = detect_loop(log_path)
        assert result["loop_detected"] is True
        assert result["block"] is True
        assert result["pattern"] == "grep"
    finally:
        os.unlink(log_path)


def test_detect_loop_no_loop_clean_log() -> None:
    """detect_loop should return clean result for normal log."""
    from superharness.engine.loop_detector import detect_loop

    log_content = """Tool: read_file
Tool: grep
Tool: write
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(log_content)
        log_path = f.name

    try:
        result = detect_loop(log_path)
        assert result["loop_detected"] is False
    finally:
        os.unlink(log_path)


# ── RED: LoopGuard escalation ────────────────────────────────────────────────

def test_loop_guard_warn_escalates_to_block() -> None:
    """LoopGuard should escalate from warn to block after WARN_ESCALATION_COUNT cycles."""
    from superharness.engine.loop_detector import LoopGuard, LOOP_WARN_THRESHOLD

    with tempfile.TemporaryDirectory() as td:
        guard = LoopGuard(td)

        # Simulate warn results (tool called LOOP_WARN_THRESHOLD times but not BLOCK)
        warn_result = {"loop_detected": True, "warn": True, "block": False,
                       "failure_loop": False, "pattern": "grep", "count": 3,
                       "reason": "grep called 3 consecutive times"}

        # First two cycles: warn only
        action1 = guard.check("task-1", warn_result)
        assert action1["action"] == "warn"

        action2 = guard.check("task-1", warn_result)
        assert action2["action"] == "warn"

        # Third cycle: escalation to block
        action3 = guard.check("task-1", warn_result)
        assert action3["action"] == "block"
        assert "escalated" in action3["reason"]


def test_loop_guard_clean_resets_counter() -> None:
    """LoopGuard should reset counter when a clean result comes in."""
    from superharness.engine.loop_detector import LoopGuard

    with tempfile.TemporaryDirectory() as td:
        guard = LoopGuard(td)

        warn_result = {"loop_detected": True, "warn": True, "block": False,
                       "failure_loop": False, "pattern": "grep", "count": 3,
                       "reason": "grep called 3 consecutive times"}
        clean_result = {"loop_detected": False, "warn": False, "block": False,
                        "failure_loop": False, "pattern": "", "count": 0, "reason": ""}

        guard.check("task-1", warn_result)  # warn #1
        guard.check("task-1", clean_result)  # clean → reset
        action = guard.check("task-1", warn_result)  # should be warn #1 again
        assert action["action"] == "warn"


def test_loop_guard_direct_block() -> None:
    """LoopGuard should block immediately on a block-level result."""
    from superharness.engine.loop_detector import LoopGuard

    with tempfile.TemporaryDirectory() as td:
        guard = LoopGuard(td)

        block_result = {"loop_detected": True, "warn": False, "block": True,
                        "failure_loop": True, "pattern": "write",
                        "count": 3, "reason": "write failed 3 consecutive times"}

        action = guard.check("task-1", block_result)
        assert action["action"] == "block"


# ── RED: watcher log analyzer integration ─────────────────────────────────────

def test_log_analyzer_detects_loop_in_log(tmp_path: Path) -> None:
    """The watcher log analyzer function should detect loops in launcher logs."""
    from superharness.engine.loop_detector import detect_loop

    # Create a log with a detectable loop
    log_dir = tmp_path / ".superharness" / "launcher-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "test-task_claude-code.log"
    log_content = "\n".join(["Tool: grep"] * 6)
    log_path.write_text(log_content)

    result = detect_loop(str(log_path))
    assert result["block"] is True
