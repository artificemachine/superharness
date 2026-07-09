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

import logging
logger = logging.getLogger(__name__)

_OPERATOR_STATE_FILE = ".superharness/operator-state.json"


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
        self._python = self._resolve_python()
        self._dashboard_port: int | None = None  # track port for reuse on restart
        self._use_dashboard = False  # only spawn dashboard if True (Opt-in)
        self._restart_history: dict[str, list[float]] = {}  # component → restart timestamps
        self._max_restarts = 5  # circuit breaker: max restarts per component in window
        self._restart_window = 600  # 10-minute window for restart counting
        self._circuit_open_until: dict[str, float] = {}  # component → cooldown deadline (epoch seconds)

    @staticmethod
    def _resolve_python() -> str:
        """Resolve a stable Python that has superharness installed.
        
        sys.executable can become stale after pipx reinstall (venv is replaced).
        Fall back to shutil.which for resilience.
        """
        import shutil
        if os.path.isfile(sys.executable):
            return sys.executable
        for candidate in ("python3", "python"):
            path = shutil.which(candidate)
            if path:
                return path
        return sys.executable  # last resort

    def _check_singleton(self) -> bool:
        """Return True if an operator is already running for this project.

        Reads operator-state.json, checks the stored PID. If the PID is still
        alive this is a duplicate invocation — the caller must abort. Stale
        state files (dead PID) are silently removed so a fresh start proceeds.
        """
        op_file = self.project_dir / _OPERATOR_STATE_FILE
        if not op_file.exists():
            return False
        try:
            with open(op_file) as f:
                state = json.load(f)
            pid = int(state.get("operator_pid", 0))
            if pid and self._is_pid_alive(pid):
                return True
            # Stale file — dead PID; remove so the fresh start writes cleanly.
            op_file.unlink(missing_ok=True)
        except Exception:
            pass
        return False

    def _ensure_db_initialized(self):
        """Verify the SQLite state database is healthy.

        If the DB file is 0 bytes (empty / never initialized), delete and
        re-create so heartbeat writes don't silently fail. Logs any issues.
        (Fix: BUGREPORT watcher-silent-death-no-recovery, root cause #3.)
        """
        import sqlite3
        from pathlib import Path

        # Resolve the DB path using the same logic as get_connection().
        try:
            from superharness.engine.db import resolve_xdg_state_db_path
        except ImportError:
            return  # db module not available; not critical

        state_project = os.environ.get("SUPERHARNESS_STATE_PROJECT", "").strip() or str(self.project_dir)
        xdg_path = Path(resolve_xdg_state_db_path(state_project))
        legacy_path = Path(self.project_dir) / ".superharness" / "state.sqlite3"

        for db_file in (xdg_path, legacy_path):
            if db_file.exists() and db_file.stat().st_size == 0:
                try:
                    db_file.unlink()
                    logger.warning(
                        "operator.py: deleted 0-byte SQLite DB %s (never initialized) — "
                        "will be re-created on first write",
                        db_file,
                    )
                except OSError as e:
                    logger.error(
                        "operator.py: failed to delete 0-byte SQLite DB %s: %s",
                        db_file, e,
                    )

        # Try to initialize the DB to ensure tables exist.
        try:
            from superharness.engine.db import get_connection, init_db
            conn = get_connection(str(self.project_dir))
            try:
                init_db(conn)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(
                "operator.py: failed to initialize SQLite DB for %s: %s",
                self.project_dir, e, exc_info=True,
            )

    def start_stack(self, dashboard_port: int = 8787, no_open: bool = False, use_dashboard: bool = False):
        """Start the Superharness stack (Watcher, optional Dashboard)."""
        from superharness.engine.trace import trace_event

        self._use_dashboard = use_dashboard

        # Ensure the state database is healthy before spawning components
        # that depend on it (watcher heartbeats write to SQLite).
        self._ensure_db_initialized()

        if self._check_singleton():
            op_file = self.project_dir / _OPERATOR_STATE_FILE
            try:
                with open(op_file) as f:
                    state = json.load(f)
                existing_pid = state.get("operator_pid", "?")
                existing_port = state.get("dashboard_port", "?")
            except Exception:
                existing_pid = "?"
                existing_port = "?"
            print(
                f"[operator] already running (pid={existing_pid}, port={existing_port}). "
                "Refusing to start a second instance. "
                "Run 'shux operator stop' first if you want to restart.",
                file=sys.stderr,
            )
            sys.exit(0)

        self._spawn_watcher()
        
        actual_port = dashboard_port
        if self._use_dashboard:
            # Patch: Try to reclaim the port if it is held by a stale dashboard FROM THIS PROJECT
            self._reclaim_port_if_zombie(dashboard_port)
            actual_port = self._find_available_port(dashboard_port)

            if actual_port != dashboard_port:
                trace_event(self.project_dir, "port_arbitration", {
                    "requested": dashboard_port,
                    "assigned": actual_port,
                    "reason": "port_busy"
                })
            self._spawn_dashboard(actual_port, no_open=no_open)
            
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
        except Exception as e:
            logger.warning("operator.py unexpected error: %s", e, exc_info=True)
            pass
    def _find_available_port(self, start_port: int) -> int:
        """Find the next available TCP port."""
        port = start_port
        while port < start_port + 100:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # SO_REUSEADDR lets us see through TIME_WAIT so a recently-killed
                # dashboard on this port doesn't cause us to skip to the next one.
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1
        raise RuntimeError(
            f"no free TCP port in range [{start_port}, {start_port + 100})"
        )

    def _write_daemon_info(self, port: int):
        """Record the active operator/dashboard state to disk."""
        self._dashboard_port = port  # track for reuse on restart
        info = {
            "operator_pid": os.getpid(),
            "dashboard_port": port,
            "started_at": time.time(),
            "project": str(self.project_dir)
        }
        op_file = self.project_dir / _OPERATOR_STATE_FILE
        with open(op_file, "w") as f:
            json.dump(info, f, indent=2)

    def _spawn_watcher(self):
        """Launch the background watcher."""
        cmd = [
            self._python, "-m", "superharness.commands.inbox_watch",
            "--project", str(self.project_dir),
            "--interval", "15",
            "--non-interactive",
        ]
        self.processes["watcher"] = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )

    def _spawn_dashboard(self, port: int, no_open: bool = False):
        """Launch the dashboard UI."""
        cmd = [
            self._python, "-m", "superharness.scripts.dashboard-ui",
            "--port", str(port),
            "--project", str(self.project_dir)
        ]
        if no_open:
            cmd.append("--no-open")
        self.processes["dashboard"] = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process is alive without waiting on it (safe from forked child)."""
        import sys

        if sys.platform == "win32":
            # os.kill(pid, 0) on Windows sends CTRL_C_EVENT (signal 0 == CTRL_C_EVENT)
            # to the process group, which triggers KeyboardInterrupt in the calling
            # process when pid == os.getpid(). Use OpenProcess instead.
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            alive = bool(
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))  # type: ignore[attr-defined]
                and exit_code.value == STILL_ACTIVE
            )
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return alive
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True  # process exists but we lack signal permission
        except OSError:
            return False  # ESRCH on Unix; various codes on Windows = not alive

    def monitor_and_recover(self, poll_interval: int = 5):
        """Loop forever, restarting any crashed components.

        Called by operator_start after daemonizing (fork+setsid). Runs in
        the forked child process. Uses proc.poll() which reaps zombies
        safely. The watcher is intentionally one-shot, so it exits after
        every tick; the monitor is what keeps it cycling.

        Any unhandled exception in the loop body is caught and logged so
        the daemon keeps running instead of dying silently. (Fix: BUGREPORT
        watcher-silent-death-no-recovery, root cause #2.)

        Before restarting a component, the old subprocess is terminated and
        waited to prevent orphan accumulation. Dashboard ports are reused
        rather than allocated fresh on every restart. (Fix: process-leak
        with 403 orphans at load 373.)
        """
        from superharness.engine.trace import trace_event
        try:
            while not self._stopping:
                try:
                    for name, proc in list(self.processes.items()):
                        # Circuit breaker cooldown: if the circuit is open
                        # (tripped for this component), skip entirely until
                        # the cooldown expires. Prevents log-spam looping where
                        # a tripped component retriggers the error every 5s.
                        # Fix: BUG-2026-06-04-operator-orphans-pytest-swap-storm
                        cooldown_until = self._circuit_open_until.get(name, 0)
                        if time.time() < cooldown_until:
                            continue

                        if proc.poll() is not None:
                            trace_event(self.project_dir, "process_recovery", {
                                "component": name, "pid": proc.pid,
                                "exit_code": proc.returncode, "action": "restart"
                            })
                            # Circuit breaker: only count non-zero exits (actual
                            # crashes). The watcher is designed as a one-shot
                            # process — it exits after every tick and the monitor
                            # restarts it. Normal exits must not accumulate toward
                            # the circuit breaker threshold or the watcher gets
                            # permanently disabled after 6 normal cycles.
                            # Fix: BUG-2026-06-04-operator-orphans-pytest-swap-storm
                            # (watcher was being circuit-broken for normal exits)
                            if proc.returncode == 0:
                                self._kill_process(proc, name)
                                if name == "watcher":
                                    self._spawn_watcher()
                                elif name == "dashboard" and self._use_dashboard:
                                    if self._dashboard_port is None:
                                        self._dashboard_port = self._find_available_port(8787)
                                    self._spawn_dashboard(self._dashboard_port, no_open=True)
                                continue
                            # Non-zero exit: count toward circuit breaker
                            now_ts = time.time()
                            history = self._restart_history.setdefault(name, [])
                            history[:] = [t for t in history if now_ts - t < self._restart_window]
                            history.append(now_ts)
                            if len(history) > self._max_restarts:
                                logger.error(
                                    "operator.py: circuit breaker TRIPPED for %s — "
                                    "%d restarts in %ds. Pausing restarts for %ds.",
                                    name, len(history), self._restart_window,
                                    self._restart_window,
                                )
                                trace_event(self.project_dir, "circuit_breaker_trip", {
                                    "component": name,
                                    "restarts": len(history),
                                    "window_seconds": self._restart_window,
                                })
                                # Clear history and set cooldown so we don't
                                # re-trigger every 5s. The component will not
                                # be restarted until cooldown expires.
                                self._restart_history[name] = []
                                self._circuit_open_until[name] = now_ts + self._restart_window
                                # Still kill the old process group so orphans
                                # don't accumulate while the circuit is open.
                                self._kill_process(proc, name)
                                continue
                            # Kill old process before replacing — prevents
                            # orphan accumulation when subprocesses are slow
                            # to exit (DB connections, HTTP keep-alive, etc.)
                            self._kill_process(proc, name)
                            if name == "watcher":
                                self._spawn_watcher()
                            elif name == "dashboard" and self._use_dashboard:
                                # Reuse the last known port instead of finding
                                # a new one. Port inflation (8787→8796) was
                                # caused by the old dashboard not releasing
                                # the port before the new one bound.
                                if self._dashboard_port is None:
                                    self._dashboard_port = self._find_available_port(8787)
                                self._spawn_dashboard(self._dashboard_port, no_open=True)
                except Exception as exc:
                    logger.error(
                        "operator.py monitor_and_recover: unhandled exception in loop — "
                        "continuing in %ss to avoid silent daemon death: %s",
                        poll_interval, exc, exc_info=True
                    )
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.stop_all()

    def _kill_process(self, proc: subprocess.Popen, name: str = "") -> None:
        """Terminate a subprocess and ALL its children (process group).

        On Unix: uses os.killpg to send SIGTERM to the entire process group,
        then SIGKILL if any survivors remain. This prevents orphaned
        grandchildren (e.g. pytest, bridge_worker.js spawned by the
        watcher) from accumulating as PPID=1 zombies.

        On Windows: falls back to proc.terminate() + proc.kill() since
        os.killpg and process groups are Unix-only concepts.

        Fix: BUG-2026-06-04-operator-orphans-pytest-swap-storm — 10.7 GB
        orphaned pytest survived because only the direct child was killed.
        """
        # Unix: kill the entire process group
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            pgid = None
            try:
                pgid = os.getpgid(proc.pid)
            except (OSError, ProcessLookupError):
                pass  # already dead

            if pgid is not None and pgid != os.getpid():
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            "operator.py _kill_process: process group %d for %s did not exit "
                            "after SIGKILL; abandoning", pgid, name
                        )
                return

        # Fallback: Windows, or process already dead / no pgid available
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except (OSError, ProcessLookupError):
            pass  # already dead

    def stop_all(self):
        """Gracefully terminate all managed processes and their children.

        Unix: sends SIGTERM to each process group (since watcher/dashboard
        use start_new_session=True), then force-kills survivors. This
        ensures no orphaned grandchildren leak when the operator shuts down.

        Windows: falls back to proc.terminate() + proc.kill().
        """
        self._stopping = True
        has_pg = hasattr(os, "killpg") and hasattr(os, "getpgid")
        for name, proc in self.processes.items():
            try:
                if has_pg:
                    pgid = os.getpgid(proc.pid)
                    if pgid != os.getpid():
                        os.killpg(pgid, signal.SIGTERM)
                    else:
                        proc.terminate()
                else:
                    proc.terminate()
            except (OSError, ProcessLookupError):
                continue
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    if has_pg:
                        pgid = os.getpgid(proc.pid)
                        if pgid != os.getpid():
                            os.killpg(pgid, signal.SIGKILL)
                        else:
                            proc.kill()
                    else:
                        proc.kill()
                except (OSError, ProcessLookupError):
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self.processes.clear()
        op_file = self.project_dir / _OPERATOR_STATE_FILE
        if op_file.exists():
            op_file.unlink()

    def check_watcher_health(self, stale_threshold_sec: int = 120) -> HealthStatus:
        """Check if the background watcher is alive."""
        # SQLite primary — source of truth
        try:
            from superharness.engine.heartbeat_contract import read_heartbeat_db
            hb = read_heartbeat_db(str(self.project_dir), "watcher")
            if hb is not None and hb.written_at:
                return self._check_ts_age(hb.written_at, "watcher (sqlite)", stale_threshold_sec)
        except Exception as e:
            logger.warning("operator.py: failed to read watcher heartbeat from SQLite: %s", e, exc_info=True)

        # YAML fallback (legacy projects)
        hb_yaml = self.harness_dir / "watcher.heartbeat.yaml"
        hb_txt = self.harness_dir / "watcher.heartbeat"
        if hb_yaml.exists():
            try:
                import yaml
                data = yaml.safe_load(hb_yaml.read_text())  # noqa: state-read — YAML fallback when SQLite empty (legacy projects)
                ts_str = data.get("written_at")
                if ts_str: return self._check_ts_age(ts_str, "watcher (yaml)", stale_threshold_sec)
            except Exception as e:
                logger.warning("operator.py: failed to read watcher yaml heartbeat: %s", e, exc_info=True)
        if hb_txt.exists():
            try:
                ts_str = hb_txt.read_text().strip()
                if ts_str: return self._check_ts_age(ts_str, "watcher (txt)", stale_threshold_sec)
            except Exception as e:
                logger.warning("operator.py: failed to read watcher txt heartbeat: %s", e, exc_info=True)
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
            except Exception as e:
                logger.warning("operator.py unexpected error: %s", e, exc_info=True)
                conflicts.append(HealthStatus(False, "lock", "Malformed lock"))
        return conflicts

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
