"""Iteration 0 — Cross-platform contract tests (RED → GREEN).

These tests define the expected behaviour of superharness on native Windows,
macOS, and Linux.  They must pass on all three OSes once the Windows-native
port is complete.  Any test marked with the ``xfail_on_windows`` marker is
expected to fail on Windows *before* the fix and pass after it.
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

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]


def _setup_project(tmp_path: Path) -> Path:
    """Bootstrap a minimal .superharness/ project directory."""
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "status: active\n"
        "goal: cross-platform test\n"
        "tasks:\n"
        "  - id: CP-001\n"
        "    title: cross-platform task\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        "    workflow: quick\n"
        "    project_path: .\n"
        "    acceptance_criteria: []\n"
        "    test_types: [unit]\n",
        encoding="utf-8",
    )
    (harness / "inbox.yaml").write_text(
        "# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n[]\n",
        encoding="utf-8",
    )
    (harness / "handoffs").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Iteration 0 — Temp / lock path tests
# ---------------------------------------------------------------------------


class TestTempAndLockPaths:
    """Lock paths and temp dirs must never contain /tmp on Windows."""

    def test_watcher_lock_path_avoids_slash_tmp_on_windows(self):
        """platform_runtime.watcher_lock_path() must not start with /tmp on Windows."""
        from superharness.engine.platform_runtime import watcher_lock_path

        path = watcher_lock_path("/some/project")
        if sys.platform == "win32":
            assert not Path(path).resolve().is_relative_to(Path("/tmp")), (
                "Lock path must not use /tmp on Windows; got: " + path
            )
        # On all platforms the path must be non-empty
        assert path

    def test_watcher_lock_path_is_deterministic(self):
        """Same project dir must always produce the same lock path."""
        from superharness.engine.platform_runtime import watcher_lock_path

        p1 = watcher_lock_path("/my/project")
        p2 = watcher_lock_path("/my/project")
        assert p1 == p2

    def test_watcher_lock_path_differs_per_project(self):
        """Different projects must get different lock paths."""
        from superharness.engine.platform_runtime import watcher_lock_path

        assert watcher_lock_path("/proj/a") != watcher_lock_path("/proj/b")

    def test_temp_dir_is_writable(self):
        """platform_runtime.tmp_dir() must return a writable directory."""
        from superharness.engine.platform_runtime import tmp_dir

        d = tmp_dir()
        assert os.path.isdir(d)
        probe = os.path.join(d, ".probe-write")
        try:
            Path(probe).write_text("ok", encoding="utf-8")
        finally:
            try:
                os.unlink(probe)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Iteration 0 — Worker sync (no rsync assumption)
# ---------------------------------------------------------------------------


class TestWorkerSync:
    """Worker sync must work on Windows where rsync is unavailable."""

    def test_sync_worker_copy_works_without_rsync(self, tmp_path):
        """Worker copy falls back to Python shutil when rsync is absent."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        src.mkdir()
        (src / "file.txt").write_text("hello", encoding="utf-8")
        (src / ".git").mkdir()  # should be excluded
        (src / ".superharness").mkdir()  # should be excluded

        dst = tmp_path / "worker"

        # Simulate Windows: pass rsync_disabled=True
        sync_worker_copy(str(src), str(dst), rsync_disabled=True)

        assert (dst / "file.txt").exists()
        assert (dst / "file.txt").read_text(encoding="utf-8") == "hello"
        assert not (dst / ".git").exists()
        assert not (dst / ".superharness").exists()

    def test_sync_worker_copy_excludes_venv_and_cache(self, tmp_path):
        """sync_worker_copy must exclude .venv, node_modules, .pytest_cache."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        src.mkdir()
        (src / "app.py").write_text("x=1", encoding="utf-8")
        for excluded in [".venv", "node_modules", ".pytest_cache"]:
            (src / excluded).mkdir()
            (src / excluded / "marker").write_text("x", encoding="utf-8")

        dst = tmp_path / "worker"
        sync_worker_copy(str(src), str(dst), rsync_disabled=True)

        for excluded in [".venv", "node_modules", ".pytest_cache"]:
            assert not (dst / excluded).exists(), f"{excluded} should be excluded"

    def test_sync_worker_copy_updates_changed_files(self, tmp_path):
        """Re-running sync_worker_copy updates changed files."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        src.mkdir()
        f = src / "data.txt"
        f.write_text("v1", encoding="utf-8")

        dst = tmp_path / "worker"
        sync_worker_copy(str(src), str(dst), rsync_disabled=True)
        assert (dst / "data.txt").read_text(encoding="utf-8") == "v1"

        f.write_text("v2", encoding="utf-8")
        sync_worker_copy(str(src), str(dst), rsync_disabled=True)
        assert (dst / "data.txt").read_text(encoding="utf-8") == "v2"


# ---------------------------------------------------------------------------
# Iteration 0 — Dispatch (no PTY / shell wrapper assumption)
# ---------------------------------------------------------------------------


class TestDispatchNoBashAssumption:
    """Dispatch must not require bash or PTY on Windows."""

    def test_inbox_watch_lock_path_uses_platform_runtime(self, tmp_path):
        """inbox_watch uses platform_runtime.watcher_lock_path, not /tmp directly."""
        project = _setup_project(tmp_path)
        from superharness.engine.platform_runtime import watcher_lock_path

        lock = watcher_lock_path(str(project))
        assert lock  # non-empty
        if sys.platform == "win32":
            assert not Path(lock).resolve().is_relative_to(Path("/tmp"))

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_delegate_print_only_does_not_exec(self, tmp_path):
        """delegate --print-only must return normally (not os.execvp)."""
        project = _setup_project(tmp_path)
        result = subprocess.run(
            [
                sys.executable, "-m", "superharness.commands.delegate",
                "--to", "claude-code",
                "--task", "CP-001",
                "--project", str(project),
                "--print-only",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
        )
        # Must exit cleanly — no exec() swallowing the process
        assert result.returncode == 0
        assert "Generated prompt" in result.stdout


# ---------------------------------------------------------------------------
# Iteration 0 — Service installation (no launchd / no bash assumption)
# ---------------------------------------------------------------------------


class TestServiceInstaller:
    """Service install must route to the correct OS backend."""

    def test_service_installer_detects_current_os(self):
        """service_installer.detect_backend() must return a valid string."""
        from superharness.engine.service_installer import detect_backend

        backend = detect_backend()
        assert backend in ("launchd", "systemd", "winsvc", "foreground")

    def test_service_installer_returns_launchd_on_darwin(self):
        """detect_backend() returns 'launchd' on macOS."""
        from superharness.engine.service_installer import detect_backend

        if platform.system() == "Darwin":
            assert detect_backend() == "launchd"

    def test_service_installer_returns_systemd_on_linux(self):
        """detect_backend() returns 'systemd' on Linux."""
        from superharness.engine.service_installer import detect_backend

        if platform.system() == "Linux":
            assert detect_backend() == "systemd"

    def test_service_installer_returns_winsvc_on_windows(self):
        """detect_backend() returns 'winsvc' on Windows."""
        from superharness.engine.service_installer import detect_backend

        if platform.system() == "Windows":
            assert detect_backend() == "winsvc"


# ---------------------------------------------------------------------------
# Iteration 0 — Python runtime probe (no interpreter mismatch)
# ---------------------------------------------------------------------------


class TestRuntimeProbe:
    """runtime_probe must identify the correct interpreter and fail fast if deps missing."""

    def test_probe_returns_current_interpreter(self):
        """probe_runtime() returns a usable Python interpreter path."""
        from superharness.engine.runtime_probe import probe_runtime

        interp = probe_runtime()
        assert interp
        assert os.path.isfile(interp) or shutil.which(interp)

    def test_probe_required_modules_pass_for_installed_package(self):
        """probe_required_modules() does not raise when superharness is installed."""
        from superharness.engine.runtime_probe import probe_required_modules

        # Should not raise — superharness is installed in this test env
        probe_required_modules(["superharness.engine.inbox"])

    def test_probe_required_modules_raises_on_missing(self):
        """probe_required_modules() raises ImportError for a non-existent module."""
        from superharness.engine.runtime_probe import probe_required_modules

        with pytest.raises((ImportError, ModuleNotFoundError)):
            probe_required_modules(["superharness._does_not_exist_xyz"])


# ---------------------------------------------------------------------------
# Iteration 0 — Lock semantics cross-platform
# ---------------------------------------------------------------------------


class TestInboxLockCrossPlatform:
    """_inbox_lock must work on both Unix (fcntl) and Windows (msvcrt)."""

    def test_inbox_lock_acquires_and_releases(self, tmp_path):
        """_inbox_lock context manager acquires and releases without error."""
        from superharness.engine.inbox import _inbox_lock

        inbox_file = tmp_path / "inbox.yaml"
        inbox_file.write_text("[]", encoding="utf-8")

        with _inbox_lock(str(inbox_file)):
            # Within context: lock held, no exception
            assert True

        # After context: lock file exists (harmless), no error on re-acquire
        with _inbox_lock(str(inbox_file)):
            assert True

    def test_inbox_lock_file_created(self, tmp_path):
        """_inbox_lock creates a .flock file alongside the inbox."""
        from superharness.engine.inbox import _inbox_lock

        inbox_file = tmp_path / "inbox.yaml"
        inbox_file.write_text("[]", encoding="utf-8")

        with _inbox_lock(str(inbox_file)):
            assert (tmp_path / "inbox.yaml.flock").exists()
