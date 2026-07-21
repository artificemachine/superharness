"""shux mcp CLI subcommands — Iteration 10."""
from __future__ import annotations

import json
import logging
import os
import sys
import signal

import click

from superharness.engine.process import pid_alive as _seam_pid_alive

logger = logging.getLogger(__name__)


def _pid_alive(pid: int | None) -> bool:
    """Non-destructive liveness probe. Delegates to the single seam in
    engine/process.py (see that module's docstring for the Windows
    mechanism this guards against)."""
    if not pid:
        return False
    return _seam_pid_alive(int(pid))


@click.group(name="mcp")
def cmd_mcp():
    """Manage the superharness MCP server (start / stop / status)."""


@cmd_mcp.command(name="start")
@click.option("--port", "-p", type=int, default=7474, show_default=True,
              help="Port to listen on.")
@click.option("--host", "-H", default="127.0.0.1", show_default=True,
              help="Address to bind. Use 0.0.0.0 to accept LAN connections from other hosts.")
@click.option("--project", "project_path", default=None,
              help="Project directory (default: cwd).")
@click.option("--transport", default="streamable-http", show_default=True,
              help="FastMCP transport: streamable-http or sse.")
def cmd_mcp_start(port: int, host: str, project_path: str | None, transport: str) -> None:
    """Start the superharness MCP server."""
    project_dir = os.path.realpath(project_path or os.getcwd())
    from superharness.mcp.server import run_server
    run_server(project_dir, port=port, transport=transport, host=host)


@cmd_mcp.command(name="status")
@click.option("--project", "project_path", default=None,
              help="Project directory (default: cwd).")
def cmd_mcp_status(project_path: str | None) -> None:
    """Show running MCP server status."""
    project_dir = os.path.realpath(project_path or os.getcwd())
    state_path = os.path.join(project_dir, ".superharness", "mcp.json")
    if not os.path.isfile(state_path):
        click.echo("MCP server: not running")
        return
    try:
        with open(state_path) as f:
            data = json.load(f)
        pid = data.get("pid")
        port = data.get("port", 7474)
        host = data.get("host", "127.0.0.1")
        # Check if process is alive
        if _pid_alive(pid):
            click.echo(f"MCP server: running  pid={pid}  port={port}")
            click.echo(f"  project: {project_dir}")
            click.echo(f"  url: http://{host}:{port}/mcp")
        else:
            click.echo("MCP server: stopped (stale state file)")
            os.unlink(state_path)
    except Exception as e:
        click.echo(f"MCP server: error reading state — {e}")


@cmd_mcp.command(name="stop")
@click.option("--project", "project_path", default=None,
              help="Project directory (default: cwd).")
def cmd_mcp_stop(project_path: str | None) -> None:
    """Stop the running MCP server."""
    project_dir = os.path.realpath(project_path or os.getcwd())
    state_path = os.path.join(project_dir, ".superharness", "mcp.json")
    if not os.path.isfile(state_path):
        click.echo("MCP server: not running")
        return
    try:
        with open(state_path) as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid:
            os.kill(pid, signal.SIGTERM)
            click.echo(f"Sent SIGTERM to pid {pid}")
            try:
                os.unlink(state_path)
            except Exception as e:
                logger.warning("cli.py unexpected error: %s", e, exc_info=True)
                pass
        else:
            click.echo("No PID in state file — cannot stop")
    except Exception as e:
        click.echo(f"Failed to stop: {e}", err=True)
        sys.exit(1)
