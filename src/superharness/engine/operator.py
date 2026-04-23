"""Superharness Operator - Guardian of the autonomous engine."""
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
        self.heartbeat_file = self.harness_dir / "watcher.heartbeat"
        self.processes: dict[str, subprocess.Popen] = {}
        self._stopping = False

    def start_stack(self, dashboard_port: int = 8787):
        """Start the full Superharness stack."""
        from superharness.engine.trace import trace_event
        
        # Patch: Try to reclaim the port if it is held by a stale dashboard FROM THIS PROJECT
        self._reclaim_port_if_zombie(dashboard_port)
        
        actual_port = self._find_available_port(dashboard_port)
        
        if actual_port != dashboard_port:
            trace_event(self.project_dir, "port_arbitration", {
                "requested": dashboard_port,
                "assigned": actual_port,
                "reason": "port_busy"
            })

        self._spawn_watcher()
        self._spawn_dashboard(actual_port)
        self._write_daemon_info(actual_port)

    def _reclaim_port_if_zombie(self, port: int):
        """If the port is busy by a stale dashboard FROM THIS PROJECT, kill it."""
        import subprocess
        try:
            cmd = ["lsof", "-t", f"-i:{port}"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            pids = res.stdout.strip().split()
            for pid_str in pids:
                pid = int(pid_str)
                check_cmd = ["ps", "-p", str(pid), "-o", "command="]
                proc_info = subprocess.run(check_cmd, capture_output=True, text=True).stdout.lower()
                
                # Only kill if it matches our specific project path
                if "python" in proc_info and "dashboard-ui" in proc_info:
                    if str(self.project_dir).lower() in proc_info:
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(1)
        except Exception:
            pass

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
        self.processes["watcher"] = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )

    def _spawn_dashboard(self, port: int):
        """Launch the dashboard UI."""
        cmd = [
            sys.executable, "-m", "superharness.scripts.dashboard-ui",
            "--port", str(port),
            "--project", str(self.project_dir)
        ]
        self.processes["dashboard"] = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )

    def monitor_and_recover(self, poll_interval: int = 5):
        """Loop forever, restarting any crashed components."""
        from superharness.engine.trace import trace_event
        try:
            while not self._stopping:
                for name, proc in list(self.processes.items()):
                    if proc.poll() is not None:
                        exit_code = proc.returncode
                        trace_event(self.project_dir, "process_recovery", {
                            "component": name, "exit_code": exit_code, "action": "restart"
                        })
                        if name == "watcher": self._spawn_watcher()
                        elif name == "dashboard": 
                            # Re-read port from metadata if dashboard crashed
                            self._spawn_dashboard(8787)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.stop_all()

    def stop_all(self):
        """Gracefully terminate all managed processes."""
        self._stopping = True
        for name, proc in self.processes.items():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.processes.clear()
        daemon_file = self.harness_dir / "daemon.pid.json"
        if daemon_file.exists():
            daemon_file.unlink()

    def check_watcher_health(self, stale_threshold_sec: int = 120) -> HealthStatus:
        """Check if the background watcher is alive."""
        hb_yaml = self.harness_dir / "watcher.heartbeat.yaml"
        hb_txt = self.harness_dir / "watcher.heartbeat"
        if hb_yaml.exists():
            try:
                import yaml
                data = yaml.safe_load(hb_yaml.read_text())
                ts_str = data.get("written_at")
                if ts_str: return self._check_ts_age(ts_str, "watcher (yaml)", stale_threshold_sec)
            except Exception: pass
        if hb_txt.exists():
            try:
                ts_str = hb_txt.read_text().strip()
                if ts_str: return self._check_ts_age(ts_str, "watcher (txt)", stale_threshold_sec)
            except Exception: pass
        return HealthStatus(False, "watcher", "Heartbeat missing")

    def _check_ts_age(self, ts_str: str, label: str, threshold: int) -> HealthStatus:
        """Helper to parse ISO timestamp and check age."""
        from datetime import datetime, timezone
        try:
            hb_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            hb_ts = hb_dt.timestamp()
            diff = time.time() - hb_ts
            if diff > threshold:
                return HealthStatus(False, "watcher", f"Watcher stale ({int(diff)}s ago)", last_heartbeat=hb_ts)
            return HealthStatus(True, "watcher", f"Watcher healthy ({label})", last_heartbeat=hb_ts)
        except Exception as e:
            return HealthStatus(False, "watcher", f"Error: {str(e)}")

    def check_resource_conflicts(self) -> list[HealthStatus]:
        """Check for zombie processes."""
        conflicts = []
        lock_file = self.harness_dir / "inbox.lock"
        if lock_file.exists():
            try:
                pid = int(lock_file.read_text().strip())
                if not self._is_pid_alive(pid):
                    conflicts.append(HealthStatus(False, "lock", f"Stale lock (PID {pid} dead)"))
            except Exception:
                conflicts.append(HealthStatus(False, "lock", "Malformed lock"))
        return conflicts

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process is alive."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def get_summary(self) -> dict[str, Any]:
        """Get full health report."""
        watcher = self.check_watcher_health()
        conflicts = self.check_resource_conflicts()
        return {
            "project": str(self.project_dir),
            "healthy": watcher.is_healthy and len(conflicts) == 0,
            "components": {
                "watcher": {"ok": watcher.is_healthy, "message": watcher.message, "last_pulse": watcher.last_heartbeat},
                "conflicts": [{"component": c.component, "message": c.message} for c in conflicts]
            }
        }
