"""Path and port resolution for multi-profile isolation.

Borrows the CLAUDE_MEM_DATA_DIR / port-override pattern from claude-mem.
Lets a single machine run multiple isolated superharness profiles
(e.g. work vs scratch) without cd-juggling.

These helpers are pure: no filesystem access, no DB access. Existing call
sites are not refactored to use them yet. They opt in over time.
"""
from __future__ import annotations

import hashlib
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
    """Return the active state DB path for project_dir.

    Delegates to resolve_active_state_db_path so there is one resolver of record.
    Callers that previously assumed the legacy .superharness/state.sqlite3 path
    should switch to resolve_active_state_db_path directly.
    """
    return resolve_active_state_db_path(project_dir)


def resolve_state_dir() -> str:
    """Return the superharness state directory.

    Precedence: SUPERHARNESS_STATE_DIR > XDG_STATE_HOME/superharness >
    ~/.local/state/superharness.
    """
    override = _read_env("SUPERHARNESS_STATE_DIR")
    if override:
        return override
    xdg = _read_env("XDG_STATE_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "superharness")


def resolve_config_dir() -> str:
    """Return the superharness config directory.

    Precedence: SUPERHARNESS_CONFIG_DIR > XDG_CONFIG_HOME/superharness >
    ~/.config/superharness.
    """
    override = _read_env("SUPERHARNESS_CONFIG_DIR")
    if override:
        return override
    xdg = _read_env("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "superharness")


def project_hash(project_path: str) -> str:
    """Return a stable 12-char hex digest for a project directory path.

    Different absolute paths produce different hashes, so parallel worktrees
    get separate state directories without collision.
    """
    digest = hashlib.sha256(os.path.abspath(project_path).encode()).hexdigest()
    return digest[:12]


def is_project_initialized(project_path: str) -> bool:
    """Return True if a state db exists at the XDG path or the legacy path.

    Use this as the guard at command entry points instead of inline
    os.path.exists(.superharness/state.sqlite3) checks.

    Honors SUPERHARNESS_STATE_PROJECT: when set (worktree dispatch), the
    original project path is used for initialization checks so that a
    worktree path does not appear uninitialized.
    """
    state_project = os.environ.get("SUPERHARNESS_STATE_PROJECT", "").strip()
    check_path = os.path.realpath(state_project if state_project else project_path)
    return (
        os.path.isfile(resolve_xdg_state_db_path(check_path))
        or os.path.isfile(
            os.path.join(check_path, ".superharness", "state.sqlite3")
        )
    )


def resolve_xdg_state_db_path(project_path: str) -> str:
    """Return the XDG-compliant state.db path for a project.

    Combines resolve_state_dir() with project_hash(project_path) so each
    project gets an isolated directory outside the repo. No filesystem access.

    Example: ~/.local/state/superharness/<12-char-hash>/state.db
    """
    return os.path.join(resolve_state_dir(), project_hash(project_path), "state.db")


def resolve_active_state_db_path(project_path: str) -> str:
    """Return the path to the active state db for a project.

    Resolution order mirrors get_connection:
      1. XDG path if it exists on disk
      2. Legacy .superharness/state.sqlite3 if it exists on disk
      3. .superharness/ directory exists → legacy path (backward-compat for
         projects initialized via shux init before XDG seeding was added)
      4. XDG path (truly new project with no .superharness/)
    """
    project_path = os.path.realpath(project_path)
    xdg = resolve_xdg_state_db_path(project_path)
    legacy = os.path.join(project_path, ".superharness", "state.sqlite3")
    if os.path.isfile(xdg):
        return xdg
    if os.path.isfile(legacy):
        return legacy
    if os.path.isdir(os.path.join(project_path, ".superharness")):
        return legacy
    return xdg


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
