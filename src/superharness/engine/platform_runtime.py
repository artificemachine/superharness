"""Cross-platform runtime utilities for superharness.

This module centralises every platform-specific decision so that the rest of
the codebase stays OS-agnostic.  Import from here instead of scattering
``if platform.system() == ...`` checks throughout command modules.

Public API
----------
watcher_lock_path(project_dir)  -> str
    Return a stable, platform-appropriate lock path for the given project.

tmp_dir() -> str
    Return a writable temp directory (never /tmp on Windows).

sync_worker_copy(src, dst, *, rsync_disabled=False)
    Copy a project tree to a worker directory, excluding standard noise dirs.

launch_agent(cmd, *, cwd)  -> int
    Launch an agent process and return its exit code.  Uses subprocess on all
    platforms (no os.execvp, which behaves differently on Windows).

expand_agent_path()
    Augment os.environ['PATH'] with common user-local bin directories so that
    agent CLIs (claude, codex) are discoverable from launchd / Task Scheduler
    environments that start with a stripped PATH.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)

# Directories to skip when syncing a project tree to a worker copy.
_SYNC_EXCLUDES: frozenset[str] = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".superharness",
        ".superharness-sync.stamp",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
    }
)
_PROTECTED_WORKER_NAMES: frozenset[str] = frozenset(
    {".git", ".superharness", ".superharness-sync.stamp"}
)
_GENERATED_ARTIFACT_NAMES: frozenset[str] = _SYNC_EXCLUDES - _PROTECTED_WORKER_NAMES
_WATCH_DEBUG_ENV = "SUPERHARNESS_WATCH_DEBUG"


def watch_debug_enabled() -> bool:
    return os.environ.get(_WATCH_DEBUG_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Compatibility alias for callers that predate the public diagnostics seam.
_watch_debug_enabled = watch_debug_enabled


def _log_watch_debug(**fields: object) -> None:
    """Emit one structured, opt-in filesystem activity record."""
    if not watch_debug_enabled():
        return
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.warning("[watch-debug] %s", details)


# ---------------------------------------------------------------------------
# Temp / lock paths
# ---------------------------------------------------------------------------


def tmp_dir() -> str:
    """Return a platform-appropriate writable temp directory.

    On Windows ``tempfile.gettempdir()`` returns something like
    ``C:\\Users\\<user>\\AppData\\Local\\Temp``, not ``/tmp``.
    On Unix it returns ``/tmp`` (or ``$TMPDIR`` if set).
    """
    return tempfile.gettempdir()


def watcher_lock_path(project_dir: str) -> str:
    """Return a stable lock path for a watcher instance.

    The lock is a *directory* (created with ``os.mkdir``) for atomicity on
    all platforms.  The path is placed under :func:`tmp_dir` so that it is
    always writable and never under ``/tmp`` on Windows.

    Args:
        project_dir: Absolute path to the project root.

    Returns:
        Absolute path of the lock directory (not yet created).
    """
    key = hashlib.sha1(os.path.realpath(project_dir).encode()).hexdigest()
    return os.path.join(tmp_dir(), f"superharness-inbox-watch-{key}.lock")


# ---------------------------------------------------------------------------
# Worker tree sync
# ---------------------------------------------------------------------------


def _remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory from a worker tree."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _prune_generated_artifacts(dst: Path) -> None:
    """Remove excluded generated output without touching shared worker state."""
    if not dst.is_dir() or dst.is_symlink():
        return
    for item in list(dst.iterdir()):
        if item.name in _PROTECTED_WORKER_NAMES:
            continue
        if item.name in _GENERATED_ARTIFACT_NAMES:
            _remove_path(item)
        elif item.is_dir() and not item.is_symlink():
            _prune_generated_artifacts(item)


def _copy_tree(src: Path, dst: Path) -> None:
    """Mirror *src* to *dst* while preserving protected worker state."""
    dst.mkdir(parents=True, exist_ok=True)
    source_names: set[str] = set()
    for item in src.iterdir():
        source_names.add(item.name)
        if item.name in _SYNC_EXCLUDES:
            target = dst / item.name
            if item.name in _GENERATED_ARTIFACT_NAMES:
                _remove_path(target)
            continue
        target = dst / item.name
        if item.is_symlink():
            link_target = os.readlink(item)
            if target.exists() or target.is_symlink():
                _remove_path(target)
            os.symlink(link_target, target)
        elif item.is_dir():
            if target.exists() and not target.is_dir():
                _remove_path(target)
            _copy_tree(item, target)
        else:
            if target.is_dir() and not target.is_symlink():
                _remove_path(target)
            shutil.copy2(str(item), str(target))
    for existing in list(dst.iterdir()):
        if existing.name in _PROTECTED_WORKER_NAMES:
            continue
        if (
            existing.name in _GENERATED_ARTIFACT_NAMES
            or existing.name not in source_names
        ):
            _remove_path(existing)


def sync_worker_copy(
    src: str,
    dst: str,
    *,
    rsync_disabled: bool = False,
) -> bool:
    """Copy *src* project tree to *dst* worker directory.

    On macOS/Linux, ``rsync`` is preferred for efficiency.  If *rsync_disabled*
    is ``True`` (Windows or rsync not found), falls back to a pure-Python
    implementation.

    Both source-trailing-slash and non-trailing-slash forms are accepted.

    Args:
        src: Absolute path to the source project root.
        dst: Absolute path to the destination worker directory.
        rsync_disabled: Force the Python fallback (e.g. on Windows or in tests).
    Returns:
        ``True`` when the sync completes.
    """
    src_path = Path(src).resolve()
    dst_path = Path(dst)
    dst_path.mkdir(parents=True, exist_ok=True)
    excludes = ",".join(sorted(_SYNC_EXCLUDES))

    started = time.monotonic()
    _log_watch_debug(
        lifecycle="start",
        component="worker-sync",
        mode="recursive-scan",
        watched_root=src_path,
        destination=dst_path,
        recursive="true",
        excludes=excludes,
        pid=os.getpid(),
    )

    use_rsync = (
        not rsync_disabled
        and platform.system() != "Windows"
        and shutil.which("rsync") is not None
    )

    if use_rsync:
        _prune_generated_artifacts(dst_path)
        exclude_args: list[str] = []
        for name in sorted(_SYNC_EXCLUDES):
            exclude_args += [f"--exclude={name}"]
        result = subprocess.run(
            ["rsync", "-a", "--delete"]
            + exclude_args
            + [f"{src_path}/", f"{dst_path}/"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            _log_watch_debug(
                lifecycle="complete",
                component="worker-sync",
                mode="recursive-scan",
                watched_root=src_path,
                destination=dst_path,
                recursive="true",
                excludes=excludes,
                pid=os.getpid(),
                returncode=result.returncode,
                duration_ms=f"{(time.monotonic() - started) * 1000:.1f}",
            )
            return True
        logger.warning(
            "worker sync rsync failed with exit code %s; falling back to Python copy",
            result.returncode,
        )

    # Python fallback — safe on Windows.
    _copy_tree(src_path, dst_path)
    _log_watch_debug(
        lifecycle="complete",
        component="worker-sync",
        mode="recursive-scan",
        watched_root=src_path,
        destination=dst_path,
        recursive="true",
        excludes=excludes,
        pid=os.getpid(),
        returncode=0,
        duration_ms=f"{(time.monotonic() - started) * 1000:.1f}",
    )
    return True


# ---------------------------------------------------------------------------
# Process launch
# ---------------------------------------------------------------------------


def expand_agent_path() -> None:
    """Augment PATH with common user-local bin directories.

    ``launchd`` and Windows Task Scheduler both start processes with a stripped
    PATH.  This function adds the directories where agent CLIs (``claude``,
    ``codex``) are commonly installed so that :func:`launch_agent` can find
    them.
    """
    extra: list[str] = [
        os.path.expanduser("~/.local/bin"),
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ]
    # Windows: AppData\Local\Programs\Python and pipx
    if platform.system() == "Windows":
        appdata = os.environ.get("LOCALAPPDATA", "")
        if appdata:
            extra += [
                os.path.join(appdata, "Programs", "Python"),
                os.path.join(appdata, "Programs", "Python", "Scripts"),
            ]
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            extra += [
                os.path.join(userprofile, ".local", "bin"),
                os.path.join(userprofile, "AppData", "Roaming", "Python", "Scripts"),
            ]

    current = os.environ.get("PATH", "")
    current_parts = current.split(os.pathsep)
    additions = [p for p in extra if p and p not in current_parts and os.path.isdir(p)]
    if additions:
        os.environ["PATH"] = current + os.pathsep + os.pathsep.join(additions)


def _forward_child_output(output: str | None, stream: TextIO) -> None:
    """Write captured child output to its matching parent stream once."""
    if output:
        stream.write(output)
        stream.flush()


def launch_agent(cmd: list[str], *, cwd: str) -> int:
    """Launch *cmd* as a subprocess and return its exit code.

    This replaces ``os.execvp()`` calls so that:
    - The caller receives the exit code (required by the watcher dispatch loop).
    - The function works correctly on Windows (``os.execvp`` on Windows does
      not replace the current process — it spawns a child *and* continues the
      parent, which breaks the single-dispatch guarantee).
    - A non-zero exit persists a redacted stderr excerpt to the audit log
      so the next session can diagnose dispatch failures (HANDOFF 2026-08-07).

    Args:
        cmd: Command and arguments, e.g. ``["claude", "-p", "--...", prompt]``.
        cwd: Working directory for the subprocess.

    Returns:
        Exit code of the launched process (0 = success).
    """
    expand_agent_path()
    # On Windows, CreateProcess cannot execute .cmd/.bat script wrappers
    # directly — only PE executables (.exe/.com).  Resolve through shutil.which
    # (which honours PATHEXT) and prepend `cmd /c` for script files.
    if sys.platform == "win32":
        resolved = shutil.which(cmd[0])
        if resolved:
            ext = os.path.splitext(resolved)[1].lower()
            if ext in (".cmd", ".bat"):
                cmd = ["cmd", "/c", resolved] + list(cmd[1:])
            else:
                cmd = [resolved] + list(cmd[1:])
    # Capture stderr (and stdout, cheap to keep) so a non-zero exit can be
    # diagnosed from the audit log instead of disappearing silently.
    # 4000 chars keeps the audit channel usable even on verbose failures.
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    _forward_child_output(result.stdout, sys.stdout)
    _forward_child_output(result.stderr, sys.stderr)
    if result.returncode != 0:
        from superharness.logging_utils import get_audit_logger, redact

        audit = get_audit_logger()
        stderr_excerpt = (result.stderr or "").strip()[:4000]
        audit.warning(
            "launch_agent: cmd=%s exit=%d stderr=%s",
            cmd[0],
            result.returncode,
            redact(stderr_excerpt) if stderr_excerpt else "<empty>",
        )
    return result.returncode
