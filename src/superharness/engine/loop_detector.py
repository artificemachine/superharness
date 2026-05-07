"""Loop detector — detects agent tool-call loops in launcher logs.

Used by the watcher to auto-block tasks when an agent loops on the same
tool without making progress (from Hermes agent patterns).
"""
from __future__ import annotations

import json
import re
from pathlib import Path


LOOP_WARN_THRESHOLD = 3
LOOP_BLOCK_THRESHOLD = 5
FAIL_LOOP_THRESHOLD = 3
WARN_ESCALATION_COUNT = 3

_TOOL_RE = re.compile(r"^Tool:\s*(\w+)")
_FAIL_RE = re.compile(r"^Tool error:\s*(\w+)")


def detect_loop(log_path: str, window: int | None = None) -> dict:
    """Detect repeated or failing tool calls in a launcher log.

    Args:
        log_path: Path to the launcher log file.
        window: Unused — kept for backward compatibility. Thresholds come from
                LOOP_WARN_THRESHOLD / LOOP_BLOCK_THRESHOLD constants.

    Returns:
        dict with keys:
            loop_detected (bool), warn (bool), block (bool),
            failure_loop (bool), pattern (str), count (int), reason (str)
    """
    _clean = {"loop_detected": False, "warn": False, "block": False,
               "failure_loop": False, "pattern": "", "count": 0, "reason": ""}

    try:
        text = Path(log_path).read_text(errors="replace")
    except (FileNotFoundError, OSError):
        return _clean

    lines = text.splitlines()

    # Parse tool call and error lines in order
    events: list[tuple[str, str]] = []  # (kind, tool_name): kind = "call" | "error"
    for line in lines:
        m = _TOOL_RE.match(line)
        if m:
            events.append(("call", m.group(1)))
            continue
        m = _FAIL_RE.match(line)
        if m:
            events.append(("error", m.group(1)))

    if not events:
        return _clean

    # --- Failure loop detection ---
    # Look for same tool erroring FAIL_LOOP_THRESHOLD times consecutively
    # (interleaved call+error pairs)
    fail_tool: str | None = None
    fail_run = 0
    i = 0
    while i < len(events):
        kind, name = events[i]
        if kind == "call" and i + 1 < len(events):
            nk, nn = events[i + 1]
            if nk == "error" and nn == name:
                if fail_tool == name:
                    fail_run += 1
                else:
                    fail_tool = name
                    fail_run = 1
                if fail_run >= FAIL_LOOP_THRESHOLD:
                    return {
                        "loop_detected": True, "warn": False, "block": True,
                        "failure_loop": True, "pattern": name,
                        "count": fail_run,
                        "reason": f"{name} failed {fail_run} consecutive times",
                    }
                i += 2
                continue
        fail_tool = None
        fail_run = 0
        i += 1

    # --- Consecutive repetition detection (calls only) ---
    calls = [name for kind, name in events if kind == "call"]
    if not calls:
        return _clean

    # Count the longest consecutive run of the same tool
    best_tool = ""
    best_run = 0
    cur_tool = calls[0]
    cur_run = 1
    for name in calls[1:]:
        if name == cur_tool:
            cur_run += 1
        else:
            if cur_run > best_run:
                best_run = cur_run
                best_tool = cur_tool
            cur_tool = name
            cur_run = 1
    if cur_run > best_run:
        best_run = cur_run
        best_tool = cur_tool

    if best_run >= LOOP_BLOCK_THRESHOLD:
        return {
            "loop_detected": True, "warn": False, "block": True,
            "failure_loop": False, "pattern": best_tool,
            "count": best_run,
            "reason": f"{best_tool} called {best_run} consecutive times",
        }
    if best_run >= LOOP_WARN_THRESHOLD:
        return {
            "loop_detected": True, "warn": True, "block": False,
            "failure_loop": False, "pattern": best_tool,
            "count": best_run,
            "reason": f"{best_tool} called {best_run} consecutive times",
        }

    return _clean


class LoopGuard:
    """Stateful warn→block escalation across dispatch cycles.

    Tracks per-task warn counts in a file-backed JSON store.  A clean
    dispatch resets the counter; WARN_ESCALATION_COUNT consecutive warns
    escalate to block.
    """

    def __init__(self, state_dir: str) -> None:
        self._path = Path(state_dir) / "loop_guard_state.json"
        self._state: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._state))

    def check(self, task_id: str, loop_result: dict) -> dict:
        """Evaluate a detect_loop result and return an action decision.

        Args:
            task_id: Unique task identifier for state tracking.
            loop_result: dict from detect_loop().

        Returns:
            dict with keys: action ("allow" | "warn" | "block"), reason (str)
        """
        if loop_result.get("block"):
            self._state.pop(task_id, None)
            self._save()
            return {"action": "block", "reason": loop_result.get("reason", "block threshold reached")}

        if loop_result.get("loop_detected") and loop_result.get("warn"):
            count = self._state.get(task_id, 0) + 1
            self._state[task_id] = count
            self._save()
            if count >= WARN_ESCALATION_COUNT:
                return {"action": "block", "reason": f"warn escalated after {count} cycles"}
            return {"action": "warn", "reason": loop_result.get("reason", "loop warn")}

        # Clean result — reset counter
        self._state.pop(task_id, None)
        self._save()
        return {"action": "allow", "reason": ""}
