"""MCP handoff tools — Iteration 7."""
from __future__ import annotations

import os
import time
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def _handoffs_dir(project_path: str) -> str:
    return os.path.join(project_path, ".superharness", "handoffs")


def get_handoffs(project_path: str, phase: str | None = None) -> list[dict]:
    """List handoff YAML files, optionally filtered by phase (plan|report|done)."""
    d = _handoffs_dir(project_path)
    if not os.path.isdir(d):
        return []
    results = []
    for fname in sorted(os.listdir(d)):
        if not fname.endswith(".yaml") and not fname.endswith(".yml"):
            continue
        if phase and f"-{phase}-" not in fname:
            continue
        results.append({"filename": fname, "path": os.path.join(d, fname)})
    return results


def write_handoff(
    project_path: str,
    *,
    task_id: str,
    phase: str,
    content: dict[str, Any],
) -> str:
    """Write a handoff YAML file. Returns the file path."""
    d = _handoffs_dir(project_path)
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    fname = f"{task_id}-{phase}-{ts}-mcp.yaml"
    path = os.path.join(d, fname)
    with open(path, "w", encoding="utf-8") as f:
        if yaml:
            yaml.dump(content, f, allow_unicode=True, default_flow_style=False)
        else:
            import json
            f.write(json.dumps(content, indent=2))
    return path
