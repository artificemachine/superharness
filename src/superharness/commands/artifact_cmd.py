"""shux artifact — manage task artifacts in the SQLite task_artifacts table.

Usage:
    shux artifact add --task <id> --type <type> <path>
    shux artifact list --task <id> [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import logging
logger = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_dir(opts_project: str | None) -> str:
    return os.path.realpath(opts_project or os.getcwd())


def _hash_file(path: str) -> tuple[str | None, int | None]:
    """Return (sha256_hex, size_bytes) for a file, or (None, None) if unreadable."""
    try:
        h = hashlib.sha256()
        total = 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
                total += len(chunk)
        return h.hexdigest(), total
    except Exception as e:
        logger.warning("artifact_cmd.py unexpected error: %s", e, exc_info=True)
        return None, None


def cmd_artifact(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="shux artifact",
        description="Manage task artifacts (files produced by agents).",
    )
    p.add_argument("--project", "-p", default=None)
    sub = p.add_subparsers(dest="subcmd")

    # artifact add
    p_add = sub.add_parser("add", help="Register a file artifact for a task.")
    p_add.add_argument("--task", "-t", required=True, help="Task ID")
    p_add.add_argument("--type", dest="artifact_type", default="file",
                       choices=["code", "image", "test_report", "binary", "file"],
                       help="Artifact type (default: file)")
    p_add.add_argument("--agent", "-a", default=None, help="Agent that produced the artifact")
    p_add.add_argument("--no-hash", action="store_true", help="Skip hashing the file")
    p_add.add_argument("path", help="File path to register")

    # artifact list
    p_list = sub.add_parser("list", help="List artifacts for a task.")
    p_list.add_argument("--task", "-t", required=True, help="Task ID")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    opts = p.parse_args(argv if argv is not None else sys.argv[1:])
    project = _project_dir(opts.project)

    if not opts.subcmd:
        p.print_help()
        sys.exit(1)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import artifacts_dao

    conn = get_connection(project)
    try:
        init_db(conn)

        if opts.subcmd == "add":
            file_hash, size = (None, None) if opts.no_hash else _hash_file(opts.path)
            agent = opts.agent or os.environ.get("SUPERHARNESS_AGENT_NAME")
            row = artifacts_dao.add(
                conn,
                task_id=opts.task,
                path=opts.path,
                agent=agent,
                type=opts.artifact_type,
                hash=file_hash,
                size_bytes=size,
                now=_now_utc(),
            )
            conn.commit()
            if hasattr(opts, "json") and opts.json:
                from dataclasses import asdict
                print(json.dumps(asdict(row)))
            else:
                size_str = f" ({size} bytes)" if size else ""
                print(f"artifact: registered {opts.path}{size_str} for task {opts.task}")

        elif opts.subcmd == "list":
            rows = artifacts_dao.get_for_task(conn, opts.task)
            if getattr(opts, "json", False):
                from dataclasses import asdict
                print(json.dumps([asdict(r) for r in rows], indent=2))
            else:
                if not rows:
                    print(f"No artifacts for task {opts.task}.")
                    return
                print(f"{'TYPE':<14} {'SIZE':>10}  PATH")
                for r in rows:
                    size_str = str(r.size_bytes) if r.size_bytes is not None else "-"
                    print(f"{r.type:<14} {size_str:>10}  {r.path}")
    finally:
        conn.close()
