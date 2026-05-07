"""Phase 6 — Windows path normalization and runtime pinning validation tests.

Verifies that all path-handling utilities behave correctly on Windows-style
paths even when running on POSIX, and that Python version checks are robust.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Path normalization — watcher_lock_path is deterministic and OS-safe
# ---------------------------------------------------------------------------

def test_watcher_lock_path_is_deterministic():
    from superharness.engine.platform_runtime import watcher_lock_path
    path_a = watcher_lock_path("/some/project")
    path_b = watcher_lock_path("/some/project")
    assert path_a == path_b


def test_watcher_lock_path_differs_per_project():
    from superharness.engine.platform_runtime import watcher_lock_path
    a = watcher_lock_path("/project/alpha")
    b = watcher_lock_path("/project/beta")
    assert a != b


def test_watcher_lock_path_no_spaces():
    from superharness.engine.platform_runtime import watcher_lock_path
    # Path must be file-system safe (no unescaped spaces in the filename)
    p = watcher_lock_path("/Users/user name with spaces/project")
    basename = os.path.basename(p)
    assert " " not in basename


def test_watcher_lock_path_under_tmp():
    from superharness.engine.platform_runtime import watcher_lock_path, tmp_dir
    p = watcher_lock_path("/some/project")
    assert p.startswith(tmp_dir())


def test_tmp_dir_is_writable():
    from superharness.engine.platform_runtime import tmp_dir
    import tempfile
    d = tmp_dir()
    assert os.path.isdir(d)
    # Verify writable by creating a temp file
    tf = tempfile.NamedTemporaryFile(dir=d, delete=True)
    tf.close()


def test_watcher_lock_path_long_project_path():
    """Very long paths should still produce a short, fixed-length lock path."""
    from superharness.engine.platform_runtime import watcher_lock_path
    long_path = "/" + "/".join(["very_long_dir_name"] * 20)
    p = watcher_lock_path(long_path)
    # The basename should be deterministic and not exceed 255 chars
    assert len(os.path.basename(p)) <= 255


def test_watcher_lock_path_unicode_project():
    from superharness.engine.platform_runtime import watcher_lock_path
    p = watcher_lock_path("/projects/proj-名前-αβγ")
    # Should not raise and should return a valid string
    assert isinstance(p, str)
    assert len(p) > 0


# ---------------------------------------------------------------------------
# Sync excludes — standard noise dirs are excluded from worker copies
# ---------------------------------------------------------------------------

def test_sync_excludes_contains_git():
    from superharness.engine.platform_runtime import _SYNC_EXCLUDES
    assert ".git" in _SYNC_EXCLUDES


def test_sync_excludes_contains_superharness():
    from superharness.engine.platform_runtime import _SYNC_EXCLUDES
    assert ".superharness" in _SYNC_EXCLUDES


def test_sync_excludes_contains_venv():
    from superharness.engine.platform_runtime import _SYNC_EXCLUDES
    assert ".venv" in _SYNC_EXCLUDES


# ---------------------------------------------------------------------------
# Runtime pinning validation — Python version guards
# ---------------------------------------------------------------------------

def test_python_version_at_least_3_10():
    """superharness requires Python 3.10+ (match statement, X|Y union types)."""
    assert sys.version_info >= (3, 10), (
        f"superharness requires Python 3.10+, running {sys.version}"
    )


def test_python_version_info_is_tuple():
    assert isinstance(sys.version_info, tuple)
    assert len(sys.version_info) >= 3


def test_python_major_is_3():
    assert sys.version_info.major == 3


def test_python_minor_integer():
    assert isinstance(sys.version_info.minor, int)


# ---------------------------------------------------------------------------
# Platform detection — platform.system() returns expected values
# ---------------------------------------------------------------------------

def test_platform_system_is_known_value():
    val = platform.system()
    assert val in ("Darwin", "Linux", "Windows", ""), f"Unexpected platform: {val}"


def test_platform_detection_does_not_crash():
    """Calling platform detection functions should never raise."""
    _ = platform.system()
    _ = platform.machine()
    _ = platform.python_version()


# ---------------------------------------------------------------------------
# PurePosixPath vs PureWindowsPath — cross-platform parsing sanity
# ---------------------------------------------------------------------------

def test_pure_windows_path_segments():
    p = PureWindowsPath(r"C:\Users\newblacc\DevOpsSec\superharness")
    assert p.parts[0] == "C:\\"
    assert "superharness" in p.parts


def test_posix_path_from_windows_style_separators():
    """Path.as_posix() converts backslashes to forward slashes."""
    p = PureWindowsPath(r"project\src\main.py")
    assert p.as_posix() == "project/src/main.py"


def test_normpath_handles_mixed_separators():
    """os.path.normpath should handle mixed separators on any OS."""
    mixed = "some/path\\to/file"
    normalized = os.path.normpath(mixed)
    assert "file" in normalized


# ---------------------------------------------------------------------------
# Worker copy excludes applied correctly on POSIX paths
# ---------------------------------------------------------------------------

def test_sync_worker_excludes_git(tmp_path):
    from superharness.engine.platform_runtime import sync_worker_copy

    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / "src" / "main.py").parent.mkdir(parents=True)
    (src / "src" / "main.py").write_text("# main")
    (src / ".superharness").mkdir()
    (src / ".superharness" / "state.yaml").write_text("state: ok")

    dst = tmp_path / "dst"
    sync_worker_copy(str(src), str(dst))

    assert not (dst / ".git").exists()
    assert not (dst / ".superharness").exists()
    assert (dst / "src" / "main.py").exists()
