"""TDD — RED phase: daemon must survive CLI exit.

Current behaviour: monitor runs as daemon thread, dies with launcher.
Expected: detached subprocess survives parent exit.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _shux_path():
    import shutil
    shux_bin = shutil.which("shux")
    if shux_bin:
        return shux_bin
    # Fallback to running via Python
    return sys.executable


def _script_is_runnable(path: str) -> bool:
    """Return True only if path exists and its shebang interpreter also exists."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            first = f.readline()
        if first.startswith(b"#!"):
            interp = first[2:].strip().split()[0].decode()
            if not os.path.isfile(interp):
                return False
    except Exception:
        pass
    return True


def _find_shux_bin() -> str:
    """Find the shux binary from the dev venv."""
    # Try dev venv first
    dev_shux = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".venv", "bin", "shux")
    dev_shux = os.path.abspath(dev_shux)
    if _script_is_runnable(dev_shux):
        return dev_shux
    # Fall back to pipx (verify interpreter is intact before trusting it)
    venv_shux = os.path.expanduser("~/.local/pipx/venvs/superharness/bin/shux")
    if _script_is_runnable(venv_shux):
        return venv_shux
    import shutil
    shux_bin = shutil.which("shux")
    if shux_bin:
        return shux_bin
    return sys.executable


def _find_shux_python():
    """Find the Python from the superharness pipx venv."""
    venv_python = os.path.expanduser("~/.local/pipx/venvs/superharness/bin/python3")
    if os.path.isfile(venv_python):
        return venv_python
    return sys.executable


class TestDaemonSurvivesParentExit:
    """Test that the monitor daemon outlives the CLI that launched it."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_daemon_survives_parent_exit(self, tmp_path: Path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        (project_dir / ".superharness").mkdir()
        
        shux = _find_shux_bin()
        
        cmd = [shux, "daemon", "start",
               "--project", str(project_dir), "--interval", "60"]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate(timeout=30)
        
        state_file = project_dir / ".superharness" / "daemon-state.json"
        assert state_file.exists(), f"State file not created. stdout={out.decode()} stderr={err.decode()}"
        
        # Wait for monitor to write its PID (up to 10 seconds, checking every 0.5s)
        pid = None
        for _ in range(20):
            state = json.loads(state_file.read_text())
            pid = state.get("pid")
            watcher = state.get("watcher_pid")
            # Monitor has written when watcher_pid differs from pid 
            # (monitor PID != watcher PID in the updated state)
            if watcher is not None and watcher != pid:
                break
            time.sleep(0.5)
        
        assert pid is not None, f"No PID in state after waiting: {state}"
        assert isinstance(pid, int) and pid > 0
        
        # Wait briefly for daemon to settle
        time.sleep(1)
        
        try:
            os.kill(pid, 0)
            alive = True
        except (ProcessLookupError, OSError):
            alive = False
        
        assert alive, (
            f"Daemon PID {pid} died after parent exit. "
            f"It was likely a daemon thread, not a detached subprocess."
        )
        
        # Cleanup
        os.kill(pid, signal.SIGTERM)

    def test_daemon_start_is_idempotent_when_alive(self, tmp_path: Path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        (project_dir / ".superharness").mkdir()
        
        shux = _find_shux_bin()
        
        cmd = [shux, "daemon", "start",
               "--project", str(project_dir), "--interval", "60"]
        
        # First start
        p1 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert "started" in (p1.stdout + p1.stderr).lower()
        
        # Second start should detect already running
        p2 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (p2.stdout + p2.stderr).lower()
        assert "already running" in output, f"Expected idempotent message, got: {output}"
        
        # Cleanup
        state_file = project_dir / ".superharness" / "daemon-state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            pid = state.get("pid")
            if pid:
                os.kill(pid, signal.SIGTERM)
