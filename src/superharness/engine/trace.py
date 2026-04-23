"""Structured Trace Ledger — machine-readable diagnostic log for AI agents."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def trace_event(project_dir: str | Path, event_type: str, data: dict[str, Any]):
    """Append a structured diagnostic event to the trace ledger."""
    project_path = Path(project_dir).resolve()
    trace_file = project_path / ".superharness" / "trace.jsonl"
    
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": event_type,
        **data
    }
    
    try:
        os.makedirs(trace_file.parent, exist_ok=True)
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass # Never block the engine for a log write
