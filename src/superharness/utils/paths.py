"""Path and port resolution for multi-profile isolation.

Borrows the CLAUDE_MEM_DATA_DIR / port-override pattern from claude-mem.
Lets a single machine run multiple isolated superharness profiles
(e.g. work vs scratch) without cd-juggling.

Most helpers are pure and none opens a database. The active-state resolver and
initialization guard inspect path existence so they can preserve compatibility
and fail closed on an explicit state-root conflict.
"""
from __future__ import annotations

import hashlib
import os


_DATA_DIR_ENV = "SUPERHARNESS_DATA_DIR"
_STATE_DIR_ENV = "SUPERHARNESS_STATE_DIR"
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
    override = _read_env(_STATE_DIR_ENV)
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


def resolve_state_project_path(project_path: str) -> str:
    """Return the project path whose state should be used.

    Worktree dispatch sets SUPERHARNESS_STATE_PROJECT to the original project.
    Keeping that override here prevents individual connection surfaces from
    hashing or opening the ephemeral worktree independently.
    """
    override = _read_env("SUPERHARNESS_STATE_PROJECT")
    return os.path.realpath(override if override else project_path)


def is_project_initialized(project_path: str) -> bool:
    """Return True if a state db exists at the XDG path or the legacy path.

    Use this as the guard at command entry points instead of inline
    os.path.exists(.superharness/state.sqlite3) checks.

    Honors SUPERHARNESS_STATE_PROJECT: when set (worktree dispatch), the
    original project path is used for initialization checks so that a
    worktree path does not appear uninitialized.
    """
    return os.path.isfile(resolve_active_state_db_path(project_path))


def resolve_xdg_state_db_path(project_path: str) -> str:
    """Return the XDG-compliant state.db path for a project.

    Combines resolve_state_dir() with project_hash(project_path) so each
    project gets an isolated directory outside the repo. No filesystem access.

    Example: ~/.local/state/superharness/<12-char-hash>/state.db
    """
    return os.path.join(resolve_state_dir(), project_hash(project_path), "state.db")


class StateDatabaseConflictError(RuntimeError):
    """Raised when an explicit state root would split an existing project state."""


def _resolve_ambient_xdg_state_db_path(project_path: str) -> str:
    """Return the normal XDG state path, ignoring SUPERHARNESS_STATE_DIR."""
    xdg_home = _read_env("XDG_STATE_HOME")
    base = (
        xdg_home
        if xdg_home
        else os.path.join(os.path.expanduser("~"), ".local", "state")
    )
    return os.path.join(base, "superharness", project_hash(project_path), "state.db")


def resolve_active_state_db_path(project_path: str) -> str:
    """Return the path to the active state db for a project.

    When SUPERHARNESS_STATE_DIR is explicit, it is authoritative even before
    its per-project database exists.  To prevent a silent split-brain, however,
    resolution fails closed if a legacy or ambient-XDG database already exists.
    This function never creates a directory or database.

    Without an explicit override, the existing compatibility order remains:
    XDG database, legacy database, legacy directory, then XDG for a new project.
    """
    project_path = resolve_state_project_path(project_path)
    xdg = resolve_xdg_state_db_path(project_path)
    legacy = os.path.join(project_path, ".superharness", "state.sqlite3")

    if _read_env(_STATE_DIR_ENV):
        ambient_xdg = _resolve_ambient_xdg_state_db_path(project_path)
        target_real = os.path.realpath(xdg)
        alternatives = []
        for candidate in (ambient_xdg, legacy):
            if (
                os.path.realpath(candidate) != target_real
                and os.path.isfile(candidate)
            ):
                alternatives.append(candidate)
        if alternatives:
            joined = ", ".join(alternatives)
            raise StateDatabaseConflictError(
                f"{_STATE_DIR_ENV} selects {xdg}, but existing state database(s) "
                f"for the same project were found at: {joined}. Refusing to "
                "create or open another state database; migrate or archive the "
                "existing state explicitly first."
            )
        return xdg

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
