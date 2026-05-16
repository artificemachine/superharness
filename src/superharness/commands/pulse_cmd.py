"""shux pulse — register agent liveness in the SQLite agent_heartbeats table.

Usage:
    shux pulse --agent claude-code [--task <id>] [--status alive|paused|done]
    shux pulse --list
    shux pulse --list --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_dir(opts_project: str | None) -> str:
    return os.path.realpath(opts_project or os.getcwd())


def cmd_pulse(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="shux pulse",
        description="Register agent liveness in SQLite (agent_heartbeats table).",
    )
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--agent", "-a", default=None,
                   help="Agent name to register (e.g. claude-code, codex-cli)")
    p.add_argument("--task", "-t", default=None, help="Active task ID")
    p.add_argument("--status", "-s", default="alive",
                   choices=["alive", "paused", "done"],
                   help="Liveness status (default: alive)")
    p.add_argument("--pid", type=int, default=None, help="Process ID")
    p.add_argument("--list", "-l", action="store_true", help="List all heartbeats")
    p.add_argument("--json", action="store_true", help="Output as JSON (use with --list)")

    opts = p.parse_args(argv if argv is not None else sys.argv[1:])
    project = _project_dir(opts.project)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import heartbeat_dao

    conn = get_connection(project)
    try:
        init_db(conn)

        if opts.list:
            rows = heartbeat_dao.get_all(conn)
            if opts.json:
                from dataclasses import asdict
                print(json.dumps([asdict(r) for r in rows], indent=2))
            else:
                if not rows:
                    print("No heartbeats registered.")
                    return
                print(f"{'AGENT':<20} {'TASK':<20} {'STATUS':<10} {'UPDATED'}")
                for r in rows:
                    task = r.task_id or "-"
                    print(f"{r.agent:<20} {task:<20} {r.status:<10} {r.updated_at}")
            return

        agent = opts.agent
        if not agent:
            # Default to the current agent from env, or prompt
            agent = os.environ.get("SUPERHARNESS_AGENT_NAME", "")
            if not agent:
                print("pulse: --agent is required (or set SUPERHARNESS_AGENT_NAME)", file=sys.stderr)
                sys.exit(1)

        pid = opts.pid or os.getpid()
        now = _now_utc()
        row = heartbeat_dao.upsert(
            conn,
            agent=agent,
            task_id=opts.task,
            status=opts.status,
            pid=pid,
            now=now,
        )
        conn.commit()
        if opts.json:
            from dataclasses import asdict
            print(json.dumps(asdict(row)))
        else:
            print(f"pulse: {agent} → {row.status} (task={row.task_id or '-'}, pid={row.pid})")
    finally:
        conn.close()
