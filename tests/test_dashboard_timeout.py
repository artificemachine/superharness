import os
import subprocess
import sys
import time
import requests
import pytest
import signal
from pathlib import Path


def _read_auth_token(project_dir: Path, proc: subprocess.Popen, timeout_s: float = 10) -> str:
    """Read the dashboard's per-project auth token, waiting for it to appear.

    Added alongside the read-route auth gate in dashboard-ui.py (PR #58,
    2026-07-21, `_verify_read_auth`) — GET /api/status and /api/ping now
    require `X-Superharness-Token`, so an unauthenticated `requests.get()`
    gets `{"error": "forbidden"}` (403) instead of ever reaching this test's
    assertions. The token is written to `.superharness/.dashboard_auth_token`
    (chmod 0o600) shortly after the dashboard subprocess starts listening.

    Checks `proc` liveness on every poll so a subprocess that dies early
    (e.g. port already in use) fails with its real exit code instead of a
    misleading "token never appeared" after the full timeout.
    """
    token_file = project_dir / ".superharness" / ".dashboard_auth_token"
    start = time.time()
    while time.time() - start < timeout_s:
        if proc.poll() is not None:
            pytest.fail(f"Dashboard exited prematurely with code {proc.returncode} "
                        f"while waiting for the auth token")
        try:
            token = token_file.read_text().strip()
            if len(token) >= 16:
                return token
        except OSError:
            pass
        time.sleep(0.2)
    pytest.fail(f"auth token file never appeared: {token_file}")


def test_dashboard_timeout_exit():
    """Verify that dashboard-ui exits after the idle timeout is exceeded."""
    project_dir = Path(__file__).parent.parent.resolve()
    script_path = project_dir / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    
    port = 9972
    
    # Start with a 5-second timeout to give more room for startup
    cmd = [
        sys.executable, str(script_path),
        "--project", str(project_dir),
        "--port", str(port),
        "--timeout", "5",
        "--no-open"
    ]
    
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_dir / "src")
    
    proc = subprocess.Popen(cmd, env=env)

    try:
        token = _read_auth_token(project_dir, proc)
        headers = {"X-Superharness-Token": token}
        url = f"http://127.0.0.1:{port}/api/status"
        start_wait = time.time()
        connected = False
        while time.time() - start_wait < 10:
            if proc.poll() is not None:
                pytest.fail(f"Dashboard exited prematurely with code {proc.returncode}")
            try:
                resp = requests.get(url, headers=headers, timeout=2)
                if resp.status_code == 200:
                    connected = True
                    break
            except:
                time.sleep(1)

        assert connected, "Dashboard failed to respond to /api/status"
        
        # Wait for timeout (5s) + buffer (10s)
        time.sleep(15)
        
        # Check if the process has exited
        exit_code = proc.poll()
        assert exit_code is not None, "Dashboard process should have exited after timeout"
        
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()

def test_dashboard_keep_alive():
    """Verify that /api/ping resets the idle timer."""
    project_dir = Path(__file__).parent.parent.resolve()
    script_path = project_dir / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    
    port = 9973
    
    # Start with a 5-second timeout
    cmd = [
        sys.executable, str(script_path),
        "--project", str(project_dir),
        "--port", str(port),
        "--timeout", "5",
        "--no-open"
    ]
    
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_dir / "src")
    
    proc = subprocess.Popen(cmd, env=env)

    try:
        token = _read_auth_token(project_dir, proc)
        headers = {"X-Superharness-Token": token}
        url_ping = f"http://127.0.0.1:{port}/api/ping"

        # Wait until healthy
        start_wait = time.time()
        connected = False
        while time.time() - start_wait < 10:
            try:
                if requests.get(url_ping, headers=headers, timeout=2).status_code == 200:
                    connected = True
                    break
            except:
                time.sleep(1)

        assert connected, "Dashboard failed to start"

        # Ping periodically for 8 seconds (longer than the 5s timeout)
        for _ in range(4):
            resp = requests.get(url_ping, headers=headers, timeout=2)
            assert resp.status_code == 200
            time.sleep(2)
            
        # The process should still be alive because we kept pinging it
        assert proc.poll() is None, "Dashboard should be alive after periodic pings"
        
        # Now stop pinging and wait for it to die (timeout 5s + buffer 10s)
        time.sleep(15)
        assert proc.poll() is not None, "Dashboard should have exited after pings stopped"
        
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
