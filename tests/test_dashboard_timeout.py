import os
import subprocess
import sys
import time
import requests
import pytest
import signal
from pathlib import Path

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
        url = f"http://127.0.0.1:{port}/api/status"
        start_wait = time.time()
        connected = False
        while time.time() - start_wait < 10:
            if proc.poll() is not None:
                pytest.fail(f"Dashboard exited prematurely with code {proc.returncode}")
            try:
                resp = requests.get(url, timeout=2)
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
        url_ping = f"http://127.0.0.1:{port}/api/ping"
        
        # Wait until healthy
        start_wait = time.time()
        connected = False
        while time.time() - start_wait < 10:
            try:
                if requests.get(url_ping, timeout=2).status_code == 200:
                    connected = True
                    break
            except:
                time.sleep(1)
        
        assert connected, "Dashboard failed to start"

        # Ping periodically for 8 seconds (longer than the 5s timeout)
        for _ in range(4):
            resp = requests.get(url_ping, timeout=2)
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
