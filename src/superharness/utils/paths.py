"""Path and port resolution for multi-profile isolation.

Borrows the CLAUDE_MEM_DATA_DIR / port-override pattern from claude-mem.
Lets a single machine run multiple isolated superharness profiles
(e.g. work vs scratch) without cd-juggling.

These helpers are pure: no filesystem access, no DB access. Existing call
sites are not refactored to use them yet. They opt in over time.
"""
from __future__ import annotations

import os


_DATA_DIR_ENV = "SUPERHARNESS_DATA_DIR"
_DASHBOARD_PORT_ENV = "SUPERHARNESS_DASHBOARD_PORT"

_PORT_MIN = 1024
_PORT_MAX = 65535


def _read_env(name: str) -> str | None:
    val = os.environ.get(name)
    return val if val else None


def resolve_project_dir(default: str) -> str:
    """Return SUPERHARNESS_DATA_DIR if set, otherwise default."""
    override = _read_env(_DATA_DIR_ENV)
    return override if override else default


def resolve_state_db_path(project_dir: str) -> str:
    """Return the conventional state DB path under project_dir."""
    return os.path.join(project_dir.rstrip("/\\"), ".superharness", "state.sqlite3")


def resolve_dashboard_port(default: int) -> int:
    """Return SUPERHARNESS_DASHBOARD_PORT if set, otherwise default.

    Validates the result is in [1024, 65535]. Raises ValueError otherwise,
    including when the env var is non-numeric or the default itself is out
    of range.
    """
    raw = _read_env(_DASHBOARD_PORT_ENV)
    if raw is None:
        port = default
    else:
        try:
            port = int(raw)
        except ValueError as exc:
            raise ValueError(
                f"{_DASHBOARD_PORT_ENV} must be an integer, got {raw!r}"
            ) from exc

    if not (_PORT_MIN <= port <= _PORT_MAX):
        raise ValueError(
            f"port {port} out of range [{_PORT_MIN}, {_PORT_MAX}]"
        )
    return port
