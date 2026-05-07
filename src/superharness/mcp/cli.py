"""shux mcp CLI subcommands — Iteration 10."""
from __future__ import annotations

import json
import os
import sys
import signal

import click


@click.group(name="mcp")
def cmd_mcp():
    """Manage the superharness MCP server (start / stop / status)."""


@cmd_mcp.command(name="start")
@click.option("--port", "-p", type=int, default=7474, show_default=True,
              help="Port to listen on.")
@click.option("--project", "project_path", default=None,
              help="Project directory (default: cwd).")
@click.option("--transport", default="streamable-http", show_default=True,
              help="FastMCP transport: streamable-http or sse.")
def cmd_mcp_start(port: int, project_path: str | None, transport: str) -> None:
    """Start the superharness MCP server."""
    project_dir = os.path.realpath(project_path or os.getcwd())
    from superharness.mcp.server import run_server
    run_server(project_dir, port=port, transport=transport)


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
        # Check if process is alive
        try:
            os.kill(pid, 0)
            click.echo(f"MCP server: running  pid={pid}  port={port}")
            click.echo(f"  project: {project_dir}")
            click.echo(f"  url: http://127.0.0.1:{port}/mcp")
        except (ProcessLookupError, OSError):
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
            except Exception:
                pass
        else:
            click.echo("No PID in state file — cannot stop")
    except Exception as e:
        click.echo(f"Failed to stop: {e}", err=True)
        sys.exit(1)
