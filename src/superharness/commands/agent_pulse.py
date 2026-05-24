"""agent-pulse — write/read agent liveness signal.

Agents call `shux agent-pulse write` periodically while running a task.
Operators and morpheme call `shux agent-pulse read` to check last-seen time.

File: .superharness/agent-pulse.yaml
Schema: AgentPulse (engine/schemas.py)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


_PULSE_FILENAME = "agent-pulse.yaml"


def _pulse_path(project_dir: str) -> Path:
    return Path(project_dir) / ".superharness" / _PULSE_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_seconds(iso_ts: str) -> float:
    try:
        dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def _write_pulse(project_dir: str, task_id: str, agent: str,
                 status: str = "running", message: str | None = None) -> None:
    pulse_path = _pulse_path(project_dir)
    if not pulse_path.parent.exists():
        print(f"agent-pulse: .superharness/ not found at {project_dir}", file=sys.stderr)
        sys.exit(1)

    pid = os.getpid()
    last_seen = _now_iso()

    # SQLite primary — source of truth
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            agent_pulse_dao.upsert(
                conn,
                agent=agent,
                task_id=task_id,
                status=status,
                pid=pid,
                message=message,
                last_seen=last_seen,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"agent-pulse: SQLite write failed (continuing with YAML): {e}", file=sys.stderr)

    # YAML mirror — skipped in sqlite_only mode (SQLite is SoT)
    skip_yaml = False
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        skip_yaml = is_sqlite_only(project_dir=project_dir)
    except Exception as e:
        print(f"agent-pulse: is_sqlite_only check failed, writing YAML mirror: {e}", file=sys.stderr)

    if not skip_yaml:
        data: dict = {
            "task_id": task_id,
            "agent": agent,
            "status": status,
            "last_seen": last_seen,
            "pid": pid,
        }
        if message:
            data["message"] = message

        pulse_path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    print(f"agent-pulse: wrote pulse for task={task_id} status={status} pid={pid}")


def _read_pulse(project_dir: str, stale_minutes: int = 10) -> int:
    # SQLite primary — source of truth
    data: dict = {}
    found_in_sqlite = False
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = agent_pulse_dao.get_latest(conn)
        finally:
            conn.close()
        if row is not None:
            data = {
                "task_id": row.task_id,
                "agent": row.agent,
                "status": row.status,
                "last_seen": row.last_seen,
                "pid": row.pid,
                "message": row.message,
            }
            found_in_sqlite = True
    except Exception as e:
        print(f"agent-pulse: SQLite read failed, falling back to YAML: {e}", file=sys.stderr)

    # YAML fallback (legacy)
    if not found_in_sqlite:
        pulse_path = _pulse_path(project_dir)
        if not pulse_path.exists():
            print("agent-pulse: no pulse file found — no agent currently running")
            return 0
        try:
            data = yaml.safe_load(pulse_path.read_text(encoding="utf-8")) or {}  # noqa: state-read — YAML fallback when SQLite empty (legacy projects)
        except Exception as e:
            print(f"agent-pulse: could not read pulse file: {e}", file=sys.stderr)
            return 1

    task_id = data.get("task_id", "unknown")
    agent = data.get("agent", "unknown")
    status = data.get("status", "unknown")
    last_seen = data.get("last_seen", "")
    message = data.get("message")
    pid = data.get("pid")

    age = _age_seconds(last_seen)
    age_min = int(age // 60)

    stale = age > stale_minutes * 60

    print(f"task:       {task_id}")
    print(f"agent:      {agent}")
    print(f"status:     {status}")
    print(f"last_seen:  {last_seen}  ({age_min}m ago)")
    if pid:
        print(f"pid:        {pid}")
    if message:
        print(f"message:    {message}")
    if stale:
        print(f"\nWARNING: pulse is stale (>{stale_minutes}m). Agent may have crashed or finished.")
        return 2  # distinct exit code for stale — callers can detect

    return 0


def _clear_pulse(project_dir: str) -> None:
    # SQLite primary — clear all rows (single-active model)
    cleared = False
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            n = agent_pulse_dao.delete_all(conn)
            conn.commit()
            cleared = n > 0
        finally:
            conn.close()
    except Exception as e:
        print(f"agent-pulse: SQLite clear failed: {e}", file=sys.stderr)

    # YAML mirror
    pulse_path = _pulse_path(project_dir)
    if pulse_path.exists():
        pulse_path.unlink()
        cleared = True

    print("agent-pulse: cleared" if cleared else "agent-pulse: nothing to clear")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="agent-pulse",
        description="Write/read agent liveness signal (.superharness/agent-pulse.yaml).",
    )
    parser.add_argument("-p", "--project", default=None,
                        help="Project directory (default: cwd)")
    sub = parser.add_subparsers(dest="subcommand")

    # write
    p_write = sub.add_parser("write", help="Write a pulse (call periodically from a running agent)")
    p_write.add_argument("--task", required=True, help="Task ID being worked on")
    p_write.add_argument("--agent", default="claude-code",
                         help="Agent name (default: claude-code)")
    p_write.add_argument("--status", default="running",
                         choices=["running", "waiting_input", "paused"],
                         help="Agent status (default: running)")
    p_write.add_argument("--message", default=None,
                         help="Optional human-readable note")

    # read
    p_read = sub.add_parser("read", help="Read and display the current pulse")
    p_read.add_argument("--stale-minutes", type=int, default=10,
                        help="Minutes after which pulse is considered stale (default: 10)")

    # clear
    sub.add_parser("clear", help="Remove the pulse file (call on task completion)")

    opts = parser.parse_args(argv)
    project = os.path.realpath(opts.project or os.getcwd())

    if opts.subcommand == "write":
        _write_pulse(project, opts.task, opts.agent, opts.status, opts.message)
    elif opts.subcommand == "read":
        rc = _read_pulse(project, opts.stale_minutes)
        sys.exit(rc)
    elif opts.subcommand == "clear":
        _clear_pulse(project)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
