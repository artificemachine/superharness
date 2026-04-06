"""shux explain — zero-setup one-screen pitch for superharness.

Answers "what is this and why does it exist?" in under 10 seconds.
Works before init, before install, requires nothing.
"""
from __future__ import annotations

import click

_TEXT = """\
superharness — multi-agent task coordination

  The problem
    You delegate work to AI agents (Claude Code, Codex CLI, etc.).
    They forget context between sessions. They clash on shared files.
    Work gets lost, duplicated, or silently dropped.

  The fix
    contract.yaml   — single source of truth for all tasks
    handoffs/       — context passed between agents (nothing lost)
    inbox + watcher — tasks queued, dispatched, tracked, closed

  The flow
    task → delegate → agent works → handoff → verify → close

  5 commands
    shux init        bootstrap this project
    shux delegate    hand a task to an agent
    shux contract    see all tasks and their status
    shux dashboard   open the browser dashboard
    shux close       mark a task done

  Ready?         shux onboard
  Just looking?  shux demo
"""


@click.command(name="explain")
def cmd_explain():
    """Why does superharness exist? (10-second answer)"""
    click.echo(_TEXT, nl=False)
