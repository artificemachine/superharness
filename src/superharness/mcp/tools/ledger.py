"""MCP ledger tools — Iteration 7."""
from __future__ import annotations

import os
from datetime import datetime, timezone


def _ledger_path(project_path: str) -> str:
    return os.path.join(project_path, ".superharness", "ledger.md")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_ledger(project_path: str, n: int = 50) -> list[str]:
    """Return the last *n* ledger entries from SQLite, oldest-first (matches ledger.md layout)."""
    try:
        from superharness.engine import state_reader as _sr
        entries = _sr.get_ledger_entries(project_path, limit=n)
        # get_ledger_entries returns newest-first; reverse so callers get oldest-first.
        return [
            f"- {e.get('created_at', '')}: {e.get('agent', 'system')} — {e.get('action', '')}"
            for e in reversed(entries)
        ]
    except Exception:
        return []


def append_ledger(project_path: str, entry: str) -> None:
    """Append a timestamped entry to ledger.md and SQLite (dual-write for compatibility)."""
    path = _ledger_path(project_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = f"- {_now()}: {entry}\n" if not entry.startswith("-") else f"{entry}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
    # Dual-write to SQLite (source of truth) so get_ledger() returns it.
    try:
        from superharness.engine.db import managed_connection, now_iso
        from superharness.engine import ledger_dao
        with managed_connection(project_path) as conn:
            ledger_dao.record(conn, action=entry.lstrip("- "), agent="mcp", now=now_iso())
    except Exception:
        pass  # best-effort; ledger.md write already succeeded
