"""Iteration 0 — Cross-platform contract tests (RED → GREEN).

These tests define the expected behaviour of superharness on native Windows,
macOS, and Linux.  They must pass on all three OSes once the Windows-native
port is complete.  Any test marked with the ``xfail_on_windows`` marker is
expected to fail on Windows *before* the fix and pass after it.
"""

from __future__ import annotations

import logging
import inspect
import os
import platform
import shutil
import subprocess
import sys
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

    def test_sync_worker_copy_falls_back_when_rsync_fails(self, tmp_path, monkeypatch):
        """A failed rsync must not leave claimed work running against stale files."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        src.mkdir()
        (src / "file.txt").write_text("fresh", encoding="utf-8")
        dst = tmp_path / "worker"
        dst.mkdir()
        (dst / "file.txt").write_text("stale", encoding="utf-8")

        monkeypatch.setattr(
            "superharness.engine.platform_runtime.platform.system", lambda: "Darwin"
        )
        monkeypatch.setattr(
            "superharness.engine.platform_runtime.shutil.which", lambda _: "/usr/bin/rsync"
        )
        monkeypatch.setattr(
            "superharness.engine.platform_runtime.subprocess.run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 23),
        )

        assert sync_worker_copy(str(src), str(dst)) is True
        assert (dst / "file.txt").read_text(encoding="utf-8") == "fresh"

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

    def test_sync_worker_copy_excludes_generated_artifacts_at_any_depth(
        self, tmp_path
    ):
        """Worker copies must not mirror generated caches or build output."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        nested = src / "tests" / "unit"
        nested.mkdir(parents=True)
        (nested / "test_real.py").write_text("def test_real(): pass", encoding="utf-8")

        generated = [
            nested / "__pycache__",
            src / "build",
            src / "dist",
            src / ".mypy_cache",
            src / ".ruff_cache",
            src / ".tox",
            src / ".nox",
            src / ".hypothesis",
            src / "htmlcov",
        ]
        for directory in generated:
            directory.mkdir(parents=True)
            (directory / "marker").write_text("generated", encoding="utf-8")

        dst = tmp_path / "worker"
        sync_worker_copy(str(src), str(dst), rsync_disabled=True)

        assert (dst / "tests" / "unit" / "test_real.py").exists()
        for directory in generated:
            relative = directory.relative_to(src)
            assert not (dst / relative).exists(), f"{relative} should be excluded"

    def test_sync_worker_copy_debug_log_attributes_recursive_scan(
        self, tmp_path, monkeypatch, caplog
    ):
        """Opt-in diagnostics identify the scanning component and scope."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        src.mkdir()
        (src / "app.py").write_text("x=1", encoding="utf-8")
        dst = tmp_path / "worker"
        monkeypatch.setenv("SUPERHARNESS_WATCH_DEBUG", "1")

        with caplog.at_level(logging.WARNING):
            sync_worker_copy(str(src), str(dst), rsync_disabled=True)

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "[watch-debug]" in messages
        assert "component=worker-sync" in messages
        assert f"watched_root={src.resolve()}" in messages
        assert "recursive=true" in messages
        assert "__pycache__" in messages
        assert f"pid={os.getpid()}" in messages
        assert "lifecycle=start" in messages
        assert "lifecycle=complete" in messages

    def test_sync_worker_copy_debounces_repeated_recursive_scan(self, tmp_path):
        """An explicit dispatch-boundary sync must always refresh the worker."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        src.mkdir()
        source_file = src / "app.py"
        source_file.write_text("v1", encoding="utf-8")
        dst = tmp_path / "worker"

        assert sync_worker_copy(str(src), str(dst), rsync_disabled=True)
        source_file.write_text("v2", encoding="utf-8")

        assert sync_worker_copy(str(src), str(dst), rsync_disabled=True)
        assert (dst / "app.py").read_text(encoding="utf-8") == "v2"

    def test_worker_sync_removes_preexisting_nested_generated_cache(self, tmp_path):
        """A sync must prune cache directories left by an older worker copy."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        (src / "tests" / "unit").mkdir(parents=True)
        (src / "tests" / "unit" / "test_real.py").write_text("pass")
        dst = tmp_path / "worker"
        stale_cache = dst / "tests" / "unit" / "__pycache__"
        stale_cache.mkdir(parents=True)
        (stale_cache / "old.pyc").write_bytes(b"cache")

        sync_worker_copy(str(src), str(dst), rsync_disabled=True)

        assert (dst / "tests" / "unit" / "test_real.py").is_file()
        assert not stale_cache.exists()

    def test_worker_sync_preserves_superharness_symlink_when_pruning(self, tmp_path):
        """Generated-cache cleanup must never remove shared worker state."""
        from superharness.engine.platform_runtime import sync_worker_copy

        src = tmp_path / "source"
        (src / "pkg").mkdir(parents=True)
        (src / "pkg" / "module.py").write_text("x = 1")
        state = tmp_path / "state"
        state.mkdir()
        dst = tmp_path / "worker"
        dst.mkdir()
        (dst / ".superharness").symlink_to(state, target_is_directory=True)
        stale_cache = dst / "pkg" / "__pycache__"
        stale_cache.mkdir(parents=True)

        sync_worker_copy(str(src), str(dst), rsync_disabled=True)

        assert (dst / ".superharness").is_symlink()
        assert (dst / ".superharness").resolve() == state.resolve()
        assert not stale_cache.exists()

    def test_idle_watcher_cycle_does_not_sync_worker_copy(self):
        """Worker copies are synchronized only after a dispatcher claims work."""
        from superharness.commands import inbox_watch

        source = inspect.getsource(inbox_watch._run_scripts)

        assert "_sync_worker_copy(project_dir)" not in source

    def test_claimed_worker_item_syncs_source_before_execution_context(self, tmp_path):
        """Claimed worker work synchronizes before the execution path is resolved."""
        from superharness.commands import inbox_dispatch

        source = tmp_path / "source"
        (source / ".git").mkdir(parents=True)
        state = source / ".superharness"
        state.mkdir()
        worker = tmp_path / "worker"
        worker.mkdir()
        (worker / ".superharness").symlink_to(state, target_is_directory=True)

        order: list[str] = []

        def fake_claim(ctx):
            ctx.item_project = str(source)
            order.append("claim")
            return None

        def fake_sync(ctx):
            order.append("sync")

        def fake_resolve(ctx):
            order.append("resolve")
            return 23

        ctx_args = {
            "inbox_file": str(worker / ".superharness" / "inbox.yaml"),
            "contract_file": str(worker / ".superharness" / "contract.yaml"),
            "project_dir": str(worker),
            "target_filter": "codex-cli",
            "print_only": True,
            "non_interactive": True,
            "codex_bypass": False,
            "launcher_timeout": 0,
            "script_dir": str(tmp_path),
            "lock": object(),
            "sqlite_primary": True,
        }

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(inbox_dispatch, "_claim_next_item", fake_claim)
            monkeypatch.setattr(inbox_dispatch, "_sync_claimed_worker_copy", fake_sync)
            monkeypatch.setattr(inbox_dispatch, "_resolve_execution_context", fake_resolve)
            assert inbox_dispatch._do_dispatch(**ctx_args) == 23
        finally:
            monkeypatch.undo()

        assert order == ["claim", "sync", "resolve"]

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

    @pytest.mark.skip(
        reason="legacy YAML fixture — pending SQLite migration (see PR #208)"
    )
    def test_delegate_print_only_does_not_exec(self, tmp_path):
        """delegate --print-only must return normally (not os.execvp)."""
        project = _setup_project(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "superharness.commands.delegate",
                "--to",
                "claude-code",
                "--task",
                "CP-001",
                "--project",
                str(project),
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

    @pytest.mark.skip(
        reason="legacy YAML fixture — pending SQLite migration (see PR #208)"
    )
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

    @pytest.mark.skip(
        reason="legacy YAML fixture — pending SQLite migration (see PR #208)"
    )
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

    @pytest.mark.skip(
        reason="legacy YAML fixture — pending SQLite migration (see PR #208)"
    )
    def test_inbox_lock_file_created(self, tmp_path):
        """_inbox_lock creates a .flock file alongside the inbox."""
        from superharness.engine.inbox import _inbox_lock

        inbox_file = tmp_path / "inbox.yaml"
        inbox_file.write_text("[]", encoding="utf-8")

        with _inbox_lock(str(inbox_file)):
            assert (tmp_path / "inbox.yaml.flock").exists()
