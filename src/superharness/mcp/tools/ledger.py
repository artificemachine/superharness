"""MCP ledger tools — Iteration 7."""
from __future__ import annotations

import os
from datetime import datetime, timezone


def _ledger_path(project_path: str) -> str:
    return os.path.join(project_path, ".superharness", "ledger.md")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_ledger(project_path: str, n: int = 50) -> list[str]:
    """Return the last *n* lines from ledger.md."""
    path = _ledger_path(project_path)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [l.rstrip("\n") for l in f.readlines() if l.strip()]
    return lines[-n:]


def append_ledger(project_path: str, entry: str) -> None:
    """Append a timestamped entry to ledger.md (append-only)."""
    path = _ledger_path(project_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = f"- {_now()}: {entry}\n" if not entry.startswith("-") else f"{entry}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
