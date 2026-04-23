"""Superharness Operator — the guardian of the autonomous engine.

Monitors system health, manages component lifecycles (Watcher/Dashboard),
and resolves resource conflicts automatically.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class HealthStatus:
    is_healthy: bool
    component: str
    message: str
    last_heartbeat: float | None = None


class Operator:
    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.harness_dir = self.project_dir / ".superharness"
        self.heartbeat_file = self.harness_dir / "agent-pulse.yaml"
        self.processes: dict[str, subprocess.Popen] = {}
        self._stopping = False

    def start_stack(self, dashboard_port: int = 8787):
        """Start the full Superharness stack (Watcher + Dashboard)."""
        actual_port = self._find_available_port(dashboard_port)
        
        print(f"Operator: Starting stack for {self.project_dir}")
        self._spawn_watcher()
        self._spawn_dashboard(actual_port)
        
        # Persist daemon metadata
        self._write_daemon_info(actual_port)

    def _find_available_port(self, start_port: int) -> int:
        """Find the next available TCP port."""
        port = start_port
        while port < start_port + 100:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1
        return start_port

    def _write_daemon_info(self, port: int):
        """Record the active operator/dashboard state to disk."""
        info = {
            "operator_pid": os.getpid(),
            "dashboard_port": port,
            "started_at": time.time(),
            "project": str(self.project_dir)
        }
        daemon_file = self.harness_dir / "daemon.pid.json"
        with open(daemon_file, "w") as f:
            json.dump(info, f, indent=2)

    def _spawn_watcher(self):
        """Launch the background watcher."""
        cmd = [
            sys.executable, "-m", "superharness.commands.inbox_watch",
            "--project", str(self.project_dir),
            "--interval", "15"
        ]
        print("Operator: Spawning Watcher...")
        self.processes["watcher"] = subprocess.Popen(
            cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def _spawn_dashboard(self, port: int):
        """Launch the dashboard UI."""
        cmd = [
            sys.executable, "-m", "superharness.scripts.dashboard-ui",
            "--port", str(port),
            "--project", str(self.project_dir)
        ]
        print(f"Operator: Spawning Dashboard on port {port}...")
        self.processes["dashboard"] = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def monitor_and_recover(self, poll_interval: int = 5):
        """Loop forever, restarting any crashed components."""
        try:
            while not self._stopping:
                for name, proc in list(self.processes.items()):
                    if proc.poll() is not None:
                        print(f"Operator: WARNING - {name} crashed (exit code {proc.returncode}). Recovering...")
                        if name == "watcher": self._spawn_watcher()
                        elif name == "dashboard": self._spawn_dashboard(8787)
                
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.stop_all()

    def stop_all(self):
        """Gracefully terminate all managed processes."""
        self._stopping = True
        print("\nOperator: Shutting down stack...")
        for name, proc in self.processes.items():
            print(f"Operator: Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.processes.clear()
        
        # Clean up daemon info
        daemon_file = self.harness_dir / "daemon.pid.json"
        if daemon_file.exists():
            daemon_file.unlink()

    def check_watcher_health(self, stale_threshold_sec: int = 60) -> HealthStatus:
        """Check if the background watcher is alive based on its heartbeat."""
        if not self.heartbeat_file.exists():
            return HealthStatus(False, "watcher", "Heartbeat file missing")

        try:
            with open(self.heartbeat_file, "r") as f:
                data = yaml.safe_load(f)
            
            ts = data.get("timestamp")
            if not ts:
                return HealthStatus(False, "watcher", "Invalid heartbeat data")

            from datetime import datetime, timezone
            hb_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hb_ts = hb_dt.timestamp()
            now = time.time()
            diff = now - hb_ts

            if diff > stale_threshold_sec:
                return HealthStatus(
                    False, 
                    "watcher", 
                    f"Watcher heartbeat is stale ({int(diff)}s ago)",
                    last_heartbeat=hb_ts
                )
            
            return HealthStatus(True, "watcher", "Watcher is healthy", last_heartbeat=hb_ts)

        except Exception as e:
            return HealthStatus(False, "watcher", f"Error reading heartbeat: {str(e)}")

    def check_resource_conflicts(self) -> list[HealthStatus]:
        """Check for zombie processes or locked resources."""
        conflicts = []
        lock_file = self.harness_dir / "inbox.lock"
        
        if lock_file.exists():
            try:
                pid = int(lock_file.read_text().strip())
                if not self._is_pid_alive(pid):
                    conflicts.append(HealthStatus(
                        False, "lock", f"Stale lock detected (PID {pid} is dead)"
                    ))
            except Exception:
                conflicts.append(HealthStatus(False, "lock", "Malformed lock file"))
        
        return conflicts

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process is alive."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def get_summary(self) -> dict[str, Any]:
        """Get a full health report of the Superharness stack."""
        watcher = self.check_watcher_health()
        conflicts = self.check_resource_conflicts()
        
        return {
            "project": str(self.project_dir),
            "healthy": watcher.is_healthy and len(conflicts) == 0,
            "components": {
                "watcher": {
                    "ok": watcher.is_healthy,
                    "message": watcher.message,
                    "last_pulse": watcher.last_heartbeat
                },
                "conflicts": [
                    {"component": c.component, "message": c.message} 
                    for c in conflicts
                ]
            }
        }
