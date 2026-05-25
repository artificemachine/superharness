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
    """Return handoffs from SQLite, optionally filtered by phase (plan|report|done)."""
    try:
        from superharness.engine import state_reader as _sr
        rows = _sr.get_handoffs(project_path)
        if phase:
            rows = [r for r in rows if str(r.get("phase", "")) == phase]
        return rows
    except Exception:
        return []


def write_handoff(
    project_path: str,
    *,
    task_id: str,
    phase: str,
    content: dict[str, Any],
) -> str:
    """Write a handoff to SQLite (source of truth). YAML export is optional.
    Returns the YAML export file path for backward compat."""
    # ── SQLite is the source of truth (mandatory). ──
    from superharness.engine.state_writer import write_handoff_to_db
    write_handoff_to_db(project_path, content, task_id=task_id, phase=phase)

    # Optional YAML export — best-effort, never blocks the write path.
    d = _handoffs_dir(project_path)
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    fname = f"{task_id}-{phase}-{ts}-mcp.yaml"
    path = os.path.join(d, fname)
    try:
        with open(path, "w", encoding="utf-8") as f:
            if yaml:
                yaml.dump(content, f, allow_unicode=True, default_flow_style=False)
            else:
                import json
                f.write(json.dumps(content, indent=2))
    except OSError:
        pass  # export-only; failure is non-fatal

    return path
