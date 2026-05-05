"""Loop detector — detects agent tool-call loops in launcher logs.

Used by the watcher to auto-block tasks when an agent loops on the same
tool without making progress (from Hermes agent patterns).
"""
from __future__ import annotations

import re
from collections import Counter


def detect_loop(log_path: str, window: int = 5) -> dict:
    """Detect repeated tool calls in a launcher log.

    Args:
        log_path: Path to the launcher log file.
        window: Number of consecutive identical tool calls to trigger detection.

    Returns:
        dict with keys: loop_detected (bool), pattern (str), count (int)
    """
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return {"loop_detected": False, "pattern": "", "count": 0}

    # Extract tool calls: "Tool: function_name(args)"
    tool_re = re.compile(r"Tool:\s*(\w+)")
    tools = []
    for line in lines:
        m = tool_re.search(line)
        if m:
            tools.append(m.group(1))

    if len(tools) < window:
        return {"loop_detected": False, "pattern": "", "count": 0}

    # Check for consecutive repeated tools using a sliding window
    for i in range(len(tools) - window + 1):
        segment = tools[i : i + window]
        if len(set(segment)) == 1:
            return {
                "loop_detected": True,
                "pattern": segment[0],
                "count": len([t for t in tools if t == segment[0]]),
            }

    return {"loop_detected": False, "pattern": "", "count": 0}
