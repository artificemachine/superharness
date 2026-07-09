"""MCP HTTP server — Iteration 9.

Exposes superharness as a FastMCP server so any MCP-compatible agent
can call contract, inbox, ledger, handoff, and skill tools natively.

Start with:
    shux mcp start [--port 7474] [--project PATH]
"""
from __future__ import annotations

import os
import sys
import json
import signal
from typing import Optional

try:
    import fastmcp
    _FASTMCP_AVAILABLE = True
except ImportError:
    _FASTMCP_AVAILABLE = False

from superharness.mcp.session import SessionManager
from superharness.mcp.hooks import HookRegistry
from superharness.mcp.approval import ApprovalGate, ApprovalPending, ApprovalRejected
from superharness.mcp.events import EventStream
from superharness.mcp import tools

import logging
logger = logging.getLogger(__name__)


def _make_app(project_path: str, port: int = 7474):
    """Build and return the FastMCP app for a given project."""
    if not _FASTMCP_AVAILABLE:
        raise ImportError("fastmcp is required. Install with: pip install fastmcp")

    sessions = SessionManager()
    hooks = HookRegistry()
    gate = ApprovalGate()
    events = EventStream()
    hooks.load_hooks_dir(project_path)

    from superharness.engine import db as _db
    conn = _db.get_connection(project_path)
    _db.init_db(conn, project_path)

    mcp = fastmcp.FastMCP(
        "superharness",
        instructions=(
            "superharness MCP server — task coordination for multi-agent projects. "
            f"Project: {project_path}"
        ),
    )

    # ── Contract tools ────────────────────────────────────────────────────────

    @mcp.tool()
    def list_tasks() -> list[dict]:
        """Return all tasks in the project contract."""
        from superharness.mcp.tools.contract import get_contract
        return get_contract(conn)

    @mcp.tool()
    def get_task(task_id: str) -> Optional[dict]:
        """Return a single task by ID."""
        from superharness.mcp.tools.contract import get_task as _get
        return _get(conn, task_id)

    @mcp.tool()
    def create_task(id: str, title: str, owner: str, status: str = "todo") -> dict:
        """Create a new task in the contract."""
        from superharness.mcp.tools.contract import create_task as _create
        return _create(conn, id=id, title=title, owner=owner, status=status)

    @mcp.tool()
    def update_task_status(task_id: str, status: str, actor: str, summary: str = "") -> dict:
        """Update a task's status. Fires lifecycle hooks."""
        from superharness.mcp.tools.contract import update_status
        return update_status(conn, task_id=task_id, status=status, actor=actor,
                             summary=summary, hook_registry=hooks, project_path=project_path)

    # ── Inbox tools ───────────────────────────────────────────────────────────

    @mcp.tool()
    def list_inbox(status_filter: Optional[list[str]] = None) -> list[dict]:
        """Return inbox items, optionally filtered by status."""
        from superharness.mcp.tools.inbox import get_inbox
        return get_inbox(conn, status_filter=status_filter)

    @mcp.tool()
    def enqueue(task_id: str, target: str, conn_id: str = "mcp-anon") -> dict:
        """Enqueue a task for agent dispatch."""
        from superharness.mcp.tools.inbox import enqueue_task
        return enqueue_task(conn, task_id=task_id, target=target,
                            project_path=project_path,
                            gate=gate, conn_id=conn_id, hook_registry=hooks)

    # ── Ledger tools ──────────────────────────────────────────────────────────

    @mcp.tool()
    def get_ledger(n: int = 50) -> list[str]:
        """Return the last N ledger entries."""
        from superharness.mcp.tools.ledger import get_ledger as _get
        return _get(project_path, n=n)

    @mcp.tool()
    def append_ledger_entry(entry: str) -> str:
        """Append a timestamped entry to the ledger."""
        from superharness.mcp.tools.ledger import append_ledger
        append_ledger(project_path, entry)
        return f"Appended: {entry}"

    # ── Handoff tools ─────────────────────────────────────────────────────────

    @mcp.tool()
    def list_handoffs(phase: Optional[str] = None) -> list[dict]:
        """List handoff files, optionally filtered by phase (plan|report|done)."""
        from superharness.mcp.tools.handoffs import get_handoffs
        return get_handoffs(project_path, phase=phase)

    @mcp.tool()
    def write_handoff(task_id: str, phase: str, content: dict) -> str:
        """Write a handoff YAML file for a task."""
        from superharness.mcp.tools.handoffs import write_handoff as _write
        return _write(project_path, task_id=task_id, phase=phase, content=content)

    # ── Skills tool ───────────────────────────────────────────────────────────

    @mcp.tool()
    def get_skills(tag: Optional[str] = None) -> list[dict]:
        """List available agent skill manifests, optionally filtered by tag."""
        from superharness.mcp.tools.skills import get_skills as _get
        return _get(tag=tag)

    # ── Event tools ───────────────────────────────────────────────────────────

    @mcp.tool()
    def get_events(n: int = 50) -> list[dict]:
        """Return the last N events from the project event stream."""
        return events.get_events(project_path, n=n)

    # ── Hygiene tool ──────────────────────────────────────────────────────────

    @mcp.tool()
    def run_hygiene() -> dict:
        """Run shux hygiene check and return results."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "superharness.engine.validate", project_path],
            capture_output=True, text=True,
        )
        return {"returncode": result.returncode, "output": result.stdout + result.stderr}

    # ── Contract summary ──────────────────────────────────────────────────────

    @mcp.tool()
    def get_contract_summary() -> dict:
        """Return an aggregate summary of the project contract state."""
        from superharness.mcp.tools.contract import get_contract
        tasks = get_contract(conn)
        by_status: dict[str, int] = {}
        for t in tasks:
            st = str(t.get("status", "unknown"))
            by_status[st] = by_status.get(st, 0) + 1
        return {
            "total": len(tasks),
            "by_status": by_status,
            "project": project_path,
        }

    return mcp


def run_server(project_path: str, port: int = 7474, transport: str = "streamable-http",
               host: str = "127.0.0.1") -> None:
    """Start the MCP server and block until stopped."""
    if not _FASTMCP_AVAILABLE:
        print("fastmcp is required. Install with: pip install fastmcp", file=sys.stderr)
        sys.exit(1)

    harness_dir = os.path.join(project_path, ".superharness")
    if not os.path.isdir(harness_dir):
        print(f"Error: {harness_dir} not found. Run 'shux init' first.", file=sys.stderr)
        sys.exit(1)

    mcp = _make_app(project_path, port)

    # Write PID + port for status checks
    state_path = os.path.join(harness_dir, "mcp.json")
    with open(state_path, "w") as f:
        json.dump({"pid": os.getpid(), "port": port, "host": host, "project": project_path}, f)

    def _cleanup(*_):
        try:
            os.unlink(state_path)
        except Exception as e:
            logger.warning("server.py unexpected error: %s", e, exc_info=True)
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    print(f"superharness MCP server starting on {host}:{port}")
    print(f"project: {project_path}")
    print("Press Ctrl+C to stop.")

    try:
        mcp.run(transport=transport, host=host, port=port)
    finally:
        _cleanup()
