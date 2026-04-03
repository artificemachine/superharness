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
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Directories to skip when syncing a project tree to a worker copy.
_SYNC_EXCLUDES: frozenset[str] = frozenset(
    {".git", ".superharness", ".venv", "node_modules", ".pytest_cache"}
)


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


def _copy_tree(src: Path, dst: Path) -> None:
    """Recursively copy *src* to *dst* skipping :data:`_SYNC_EXCLUDES`."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in _SYNC_EXCLUDES:
            continue
        target = dst / item.name
        if item.is_symlink():
            link_target = os.readlink(item)
            if target.exists() or target.is_symlink():
                target.unlink()
            os.symlink(link_target, target)
        elif item.is_dir():
            _copy_tree(item, target)
        else:
            shutil.copy2(str(item), str(target))


def _remove_stale(dst: Path) -> None:
    """Remove items from *dst* that should no longer be there (sync --delete)."""
    # We don't have the source list here; callers handle incremental delete
    # by passing an existing dst that we write over.  Full delete is done in
    # the caller when rsync is disabled.
    pass


def sync_worker_copy(src: str, dst: str, *, rsync_disabled: bool = False) -> None:
    """Copy *src* project tree to *dst* worker directory.

    On macOS/Linux, ``rsync`` is preferred for efficiency.  If *rsync_disabled*
    is ``True`` (Windows or rsync not found), falls back to a pure-Python
    implementation.

    Both source-trailing-slash and non-trailing-slash forms are accepted.

    Args:
        src: Absolute path to the source project root.
        dst: Absolute path to the destination worker directory.
        rsync_disabled: Force the Python fallback (e.g. on Windows or in tests).
    """
    src_path = Path(src).resolve()
    dst_path = Path(dst)

    use_rsync = (
        not rsync_disabled
        and platform.system() != "Windows"
        and shutil.which("rsync") is not None
    )

    if use_rsync:
        exclude_args: list[str] = []
        for name in sorted(_SYNC_EXCLUDES):
            exclude_args += [f"--exclude={name}"]
        subprocess.run(
            ["rsync", "-a", "--delete"] + exclude_args + [f"{src_path}/", f"{dst_path}/"],
            check=False,
            capture_output=True,
        )
        return

    # Python fallback — safe on Windows
    dst_path.mkdir(parents=True, exist_ok=True)

    # Delete items in dst that are no longer in src (mirror rsync --delete)
    src_names = {item.name for item in src_path.iterdir()} - _SYNC_EXCLUDES
    for existing in list(dst_path.iterdir()):
        if existing.name == ".superharness":
            continue  # never remove the shared state symlink/dir
        if existing.name not in src_names:
            if existing.is_dir() and not existing.is_symlink():
                shutil.rmtree(str(existing))
            else:
                existing.unlink(missing_ok=True)

    _copy_tree(src_path, dst_path)


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


def launch_agent(cmd: list[str], *, cwd: str) -> int:
    """Launch *cmd* as a subprocess and return its exit code.

    This replaces ``os.execvp()`` calls so that:
    - The caller receives the exit code (required by the watcher dispatch loop).
    - The function works correctly on Windows (``os.execvp`` on Windows does
      not replace the current process — it spawns a child *and* continues the
      parent, which breaks the single-dispatch guarantee).

    Args:
        cmd: Command and arguments, e.g. ``["claude", "-p", "--...", prompt]``.
        cwd: Working directory for the subprocess.

    Returns:
        Exit code of the launched process (0 = success).
    """
    expand_agent_path()
    result = subprocess.run(cmd, cwd=cwd, check=False)
    return result.returncode
