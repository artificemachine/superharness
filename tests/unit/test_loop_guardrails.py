"""TDD: tool-loop guardrails — warn → block for repeated failing tool calls.

Hermes pattern: detect repeated same tool call (idempotent loop) and
repeated same failing tool call, emit warn then block after threshold.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_log(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "launcher.log"
    p.write_text("\n".join(lines) + "\n")
    return p


def _tool_lines(tool: str, n: int) -> list[str]:
    return [f"Tool: {tool}(path='foo.py')" for _ in range(n)]


def _fail_lines(tool: str, n: int) -> list[str]:
    result = []
    for _ in range(n):
        result.append(f"Tool: {tool}(path='foo.py')")
        result.append(f"Tool error: {tool} returned non-zero exit code 1")
    return result


# ---------------------------------------------------------------------------
# 1. Thresholds: warn vs block
# ---------------------------------------------------------------------------

class TestLoopThresholds:
    def test_below_warn_threshold_is_clean(self, tmp_path):
        """2 consecutive same tool calls — below threshold, no warn."""
        from superharness.engine.loop_detector import detect_loop
        log = _write_log(tmp_path, _tool_lines("Read", 2))
        result = detect_loop(str(log))
        assert result["loop_detected"] is False
        assert result.get("warn") is False
        assert result.get("block") is False

    def test_at_warn_threshold_emits_warn(self, tmp_path):
        """3 consecutive same tool calls → warn (not block)."""
        from superharness.engine.loop_detector import detect_loop, LOOP_WARN_THRESHOLD
        log = _write_log(tmp_path, _tool_lines("Read", LOOP_WARN_THRESHOLD))
        result = detect_loop(str(log))
        assert result["warn"] is True
        assert result["block"] is False
        assert result["loop_detected"] is True

    def test_at_block_threshold_emits_block(self, tmp_path):
        """5 consecutive same tool calls → block."""
        from superharness.engine.loop_detector import detect_loop, LOOP_BLOCK_THRESHOLD
        log = _write_log(tmp_path, _tool_lines("Read", LOOP_BLOCK_THRESHOLD))
        result = detect_loop(str(log))
        assert result["block"] is True
        assert result["loop_detected"] is True

    def test_mixed_tools_no_loop(self, tmp_path):
        """Alternating tools — no loop."""
        from superharness.engine.loop_detector import detect_loop
        lines = ["Tool: Read(path='a.py')", "Tool: Write(path='b.py')"] * 5
        log = _write_log(tmp_path, lines)
        result = detect_loop(str(log))
        assert result["loop_detected"] is False

    def test_empty_log_is_clean(self, tmp_path):
        """Empty log — no loop."""
        from superharness.engine.loop_detector import detect_loop
        log = _write_log(tmp_path, [])
        result = detect_loop(str(log))
        assert result["loop_detected"] is False

    def test_missing_log_is_clean(self, tmp_path):
        """Missing log file — no crash, returns clean."""
        from superharness.engine.loop_detector import detect_loop
        result = detect_loop(str(tmp_path / "nonexistent.log"))
        assert result["loop_detected"] is False


# ---------------------------------------------------------------------------
# 2. Failure loop detection
# ---------------------------------------------------------------------------

class TestFailureLoop:
    def test_failure_loop_detected(self, tmp_path):
        """Same tool failing 3 times in a row → failure_loop=True."""
        from superharness.engine.loop_detector import detect_loop, FAIL_LOOP_THRESHOLD
        log = _write_log(tmp_path, _fail_lines("Bash", FAIL_LOOP_THRESHOLD))
        result = detect_loop(str(log))
        assert result.get("failure_loop") is True

    def test_failure_loop_reason_mentions_tool(self, tmp_path):
        """failure_loop result includes tool name in reason."""
        from superharness.engine.loop_detector import detect_loop, FAIL_LOOP_THRESHOLD
        log = _write_log(tmp_path, _fail_lines("Bash", FAIL_LOOP_THRESHOLD))
        result = detect_loop(str(log))
        assert "Bash" in result.get("reason", "")

    def test_no_failure_loop_on_single_error(self, tmp_path):
        """One error after tool call — not a failure loop."""
        from superharness.engine.loop_detector import detect_loop
        log = _write_log(tmp_path, _fail_lines("Bash", 1))
        result = detect_loop(str(log))
        assert result.get("failure_loop") is not True

    def test_failure_loop_triggers_block(self, tmp_path):
        """failure_loop implies block=True — agent is stuck."""
        from superharness.engine.loop_detector import detect_loop, FAIL_LOOP_THRESHOLD
        log = _write_log(tmp_path, _fail_lines("Bash", FAIL_LOOP_THRESHOLD))
        result = detect_loop(str(log))
        assert result["block"] is True


# ---------------------------------------------------------------------------
# 3. LoopGuard — stateful warn → block across dispatch cycles
# ---------------------------------------------------------------------------

class TestLoopGuard:
    def test_clean_result_returns_allow(self, tmp_path):
        """No loop detected → action=allow."""
        from superharness.engine.loop_detector import LoopGuard
        guard = LoopGuard(state_dir=str(tmp_path))
        action = guard.check("task-1", {"loop_detected": False, "warn": False, "block": False,
                                         "failure_loop": False, "pattern": "", "count": 0, "reason": ""})
        assert action["action"] == "allow"

    def test_warn_result_returns_warn_first_time(self, tmp_path):
        """First warn → action=warn (don't block yet)."""
        from superharness.engine.loop_detector import LoopGuard
        guard = LoopGuard(state_dir=str(tmp_path))
        action = guard.check("task-1", {"loop_detected": True, "warn": True, "block": False,
                                         "failure_loop": False, "pattern": "Read", "count": 3, "reason": ""})
        assert action["action"] == "warn"

    def test_repeated_warn_escalates_to_block(self, tmp_path):
        """Warn on consecutive cycles → escalates to block."""
        from superharness.engine.loop_detector import LoopGuard
        guard = LoopGuard(state_dir=str(tmp_path))
        warn_result = {"loop_detected": True, "warn": True, "block": False,
                       "failure_loop": False, "pattern": "Read", "count": 3, "reason": ""}
        guard.check("task-1", warn_result)  # first warn
        guard.check("task-1", warn_result)  # second warn
        action = guard.check("task-1", warn_result)  # third warn → block
        assert action["action"] == "block"

    def test_block_result_always_blocks(self, tmp_path):
        """block=True in detect_loop → always block regardless of prior state."""
        from superharness.engine.loop_detector import LoopGuard
        guard = LoopGuard(state_dir=str(tmp_path))
        action = guard.check("task-1", {"loop_detected": True, "warn": False, "block": True,
                                         "failure_loop": False, "pattern": "Read", "count": 5, "reason": ""})
        assert action["action"] == "block"

    def test_state_persists_across_guard_instances(self, tmp_path):
        """Warn count persists when a new LoopGuard instance is created (file-backed)."""
        from superharness.engine.loop_detector import LoopGuard
        warn_result = {"loop_detected": True, "warn": True, "block": False,
                       "failure_loop": False, "pattern": "Read", "count": 3, "reason": ""}
        LoopGuard(state_dir=str(tmp_path)).check("task-1", warn_result)
        LoopGuard(state_dir=str(tmp_path)).check("task-1", warn_result)
        action = LoopGuard(state_dir=str(tmp_path)).check("task-1", warn_result)
        assert action["action"] == "block"

    def test_clean_result_resets_warn_count(self, tmp_path):
        """A clean dispatch resets the warn counter for a task."""
        from superharness.engine.loop_detector import LoopGuard
        guard = LoopGuard(state_dir=str(tmp_path))
        warn_result = {"loop_detected": True, "warn": True, "block": False,
                       "failure_loop": False, "pattern": "Read", "count": 3, "reason": ""}
        clean_result = {"loop_detected": False, "warn": False, "block": False,
                        "failure_loop": False, "pattern": "", "count": 0, "reason": ""}
        guard.check("task-1", warn_result)
        guard.check("task-1", clean_result)   # reset
        action = guard.check("task-1", warn_result)
        assert action["action"] == "warn"     # back to first warn, not block


# ---------------------------------------------------------------------------
# 4. Constants are sane
# ---------------------------------------------------------------------------

class TestConstants:
    def test_warn_threshold_less_than_block(self):
        from superharness.engine.loop_detector import LOOP_WARN_THRESHOLD, LOOP_BLOCK_THRESHOLD
        assert LOOP_WARN_THRESHOLD < LOOP_BLOCK_THRESHOLD

    def test_fail_threshold_is_positive(self):
        from superharness.engine.loop_detector import FAIL_LOOP_THRESHOLD
        assert FAIL_LOOP_THRESHOLD >= 2

    def test_warn_escalation_threshold_positive(self):
        from superharness.engine.loop_detector import WARN_ESCALATION_COUNT
        assert WARN_ESCALATION_COUNT >= 2
