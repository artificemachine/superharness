"""Tests for dashboard autohealth version-mismatch restart.

RED → GREEN → REFACTOR for feat.dashboard-auto-restart-on-upgrade.

Acceptance criteria:
- autohealth_loop detects version mismatch at each heartbeat
- Restarts the dashboard subprocess when mismatch detected
- Logs restart with old and new version to ledger
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch


def _load_dashboard_module(repo_root: Path):
    script = repo_root / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    spec = importlib.util.spec_from_file_location("dashboard_ui_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# _get_installed_version helper
# ---------------------------------------------------------------------------

def test_get_installed_version_returns_string(repo_root):
    """_get_installed_version must return a non-empty string for an installed package."""
    mod = _load_dashboard_module(repo_root)
    assert hasattr(mod, "_get_installed_version"), (
        "_get_installed_version not defined in dashboard-ui.py"
    )
    version = mod._get_installed_version()
    assert isinstance(version, str)
    assert len(version) > 0


def test_get_installed_version_unknown_on_missing_package(repo_root):
    """_get_installed_version must return 'unknown' when the package is not found."""
    mod = _load_dashboard_module(repo_root)
    with patch("importlib.metadata.version", side_effect=Exception("not found")):
        version = mod._get_installed_version()
    assert version == "unknown"


# ---------------------------------------------------------------------------
# _append_ledger helper
# ---------------------------------------------------------------------------

def test_append_ledger_writes_line(repo_root, tmp_path):
    """_append_ledger must append the given line to .superharness/ledger.md."""
    mod = _load_dashboard_module(repo_root)
    assert hasattr(mod, "_append_ledger"), (
        "_append_ledger not defined in dashboard-ui.py"
    )
    harness = tmp_path / ".superharness"
    harness.mkdir()
    ledger = harness / "ledger.md"
    ledger.write_text("# Ledger\n")

    mod._append_ledger(str(tmp_path), "- 2026-04-23T00:00:00Z — test line\n")
    content = ledger.read_text()
    assert "test line" in content


def test_append_ledger_creates_ledger_if_missing(repo_root, tmp_path):
    """_append_ledger must create ledger.md if it does not exist."""
    mod = _load_dashboard_module(repo_root)
    harness = tmp_path / ".superharness"
    harness.mkdir()
    # Do NOT create ledger.md

    mod._append_ledger(str(tmp_path), "- 2026-04-23T00:00:00Z — first entry\n")
    ledger = harness / "ledger.md"
    assert ledger.exists()
    assert "first entry" in ledger.read_text()


# ---------------------------------------------------------------------------
# autohealth_loop — version mismatch detection
# ---------------------------------------------------------------------------

def _make_fake_proc(alive: bool = True) -> MagicMock:
    proc = MagicMock()
    proc.pid = 12345
    proc.poll.return_value = None if alive else 0
    return proc


def test_autohealth_restarts_on_version_mismatch(repo_root, tmp_path):
    """autohealth_loop must restart the subprocess when the installed version changes."""
    mod = _load_dashboard_module(repo_root)

    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "ledger.md").write_text("# Ledger\n")

    procs = [_make_fake_proc(), _make_fake_proc()]
    popen_seq = iter(procs)

    # Call order for _get_installed_version:
    #   0 (before loop): "1.0.0"  → sets running_version
    #   1 (iter 0 body): "1.0.0"  → no mismatch
    #   2 (iter 1 body): "1.1.0"  → MISMATCH → restart, continue
    # sleep raises on the 3rd call (iter 2), after the mismatch was handled.
    version_seq = iter(["1.0.0", "1.0.0", "1.1.0"])
    iteration = [0]

    def fake_sleep(_seconds):
        iteration[0] += 1
        if iteration[0] >= 3:
            raise SystemExit(0)

    with (
        patch.object(mod, "_get_installed_version", side_effect=version_seq),
        patch.object(mod, "autohealth_check", return_value=True),
        patch("subprocess.Popen", side_effect=popen_seq),
        patch("time.sleep", side_effect=fake_sleep),
        patch("signal.signal"),
    ):
        try:
            mod.autohealth_loop(
                project_dir=str(tmp_path),
                port=9999,
                host="127.0.0.1",
                interval=1,
                max_restarts=10,
            )
        except SystemExit:
            pass

    # First proc should have been terminated (version mismatch restart)
    procs[0].terminate.assert_called()


def test_autohealth_no_restart_when_version_unchanged(repo_root, tmp_path):
    """autohealth_loop must NOT restart when the installed version stays the same."""
    mod = _load_dashboard_module(repo_root)

    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "ledger.md").write_text("# Ledger\n")

    started_procs = []

    def fake_popen(*_args, **_kwargs):
        p = _make_fake_proc()
        started_procs.append(p)
        return p

    iteration = [0]

    def fake_sleep(_seconds):
        iteration[0] += 1
        if iteration[0] >= 2:
            raise SystemExit(0)

    with (
        patch.object(mod, "_get_installed_version", return_value="1.0.0"),
        patch.object(mod, "autohealth_check", return_value=True),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("time.sleep", side_effect=fake_sleep),
        patch("signal.signal"),
    ):
        try:
            mod.autohealth_loop(
                project_dir=str(tmp_path),
                port=9999,
                host="127.0.0.1",
                interval=1,
                max_restarts=10,
            )
        except SystemExit:
            pass

    # Only the initial start — no extra Popen calls for version mismatch
    assert len(started_procs) == 1, (
        f"Expected 1 process start, got {len(started_procs)}"
    )


def test_autohealth_version_mismatch_logged_to_ledger(repo_root, tmp_path):
    """autohealth_loop must write old→new version info to ledger on restart."""
    mod = _load_dashboard_module(repo_root)

    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "ledger.md").write_text("# Ledger\n")

    # Same ordering as test_autohealth_restarts_on_version_mismatch:
    # call 0 → "0.9.0" (before loop), call 1 → "0.9.0" (iter 0), call 2 → "1.0.0" (iter 1 MISMATCH)
    version_seq = iter(["0.9.0", "0.9.0", "1.0.0"])
    iteration = [0]

    def fake_sleep(_seconds):
        iteration[0] += 1
        if iteration[0] >= 3:
            raise SystemExit(0)

    with (
        patch.object(mod, "_get_installed_version", side_effect=version_seq),
        patch.object(mod, "autohealth_check", return_value=True),
        patch("subprocess.Popen", return_value=_make_fake_proc()),
        patch("time.sleep", side_effect=fake_sleep),
        patch("signal.signal"),
    ):
        try:
            mod.autohealth_loop(
                project_dir=str(tmp_path),
                port=9999,
                host="127.0.0.1",
                interval=1,
                max_restarts=10,
            )
        except SystemExit:
            pass

    ledger_content = (harness / "ledger.md").read_text()
    assert "auto-restart" in ledger_content
    assert "0.9.0" in ledger_content
    assert "1.0.0" in ledger_content


def test_append_ledger_helper_format(repo_root, tmp_path):
    """_append_ledger line for version restart must include required fields."""
    mod = _load_dashboard_module(repo_root)
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "ledger.md").write_text("# Ledger\n")

    # Directly test the ledger line written during a version mismatch
    line = "- 2026-04-23T10:00:00Z — auto-restart — version mismatch: 1.0.0 -> 1.1.0\n"
    mod._append_ledger(str(tmp_path), line)

    content = (harness / "ledger.md").read_text()
    assert "auto-restart" in content
    assert "version mismatch" in content
    assert "1.0.0 -> 1.1.0" in content
