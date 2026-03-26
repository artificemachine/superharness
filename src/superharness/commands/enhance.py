"""Module marketplace — enable, disable, list integrations."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from superharness.modules.registry import (
    available_modules,
    disable_module,
    enable_module,
    enabled_modules,
    module_info,
)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """Module marketplace — enable, disable, list integrations."""
    if ctx.invoked_subcommand is None:
        # Default: list available modules
        ctx.invoke(list_modules)


@main.command("list")
@click.option(
    "--project",
    "-p",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Project directory (default: current directory)",
)
def list_modules(project):
    """List available and enabled modules."""
    project_dir = Path(project or os.getcwd())

    available = available_modules()
    enabled = enabled_modules(project_dir)

    click.echo("superharness — modules")
    click.echo("=" * 40)
    click.echo()

    if enabled:
        click.echo(click.style("✓ Enabled modules:", fg="green", bold=True))
        for name in enabled:
            click.echo(f"  • {name}")
        click.echo()

    available_not_enabled = [m for m in available if m not in enabled]
    if available_not_enabled:
        click.echo(click.style("◻ Available modules:", fg="cyan"))
        for name in available_not_enabled:
            click.echo(f"  • {name}")
        click.echo()

    click.echo("Run 'shux enhance enable <name>' to enable a module")
    click.echo("Run 'shux enhance info <name>' for details")


@main.command("enable")
@click.argument("name")
@click.option(
    "--project",
    "-p",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Project directory (default: current directory)",
)
def enable(name, project):
    """Enable a module by name."""
    project_dir = Path(project or os.getcwd())

    if enable_module(name, project_dir):
        click.echo(click.style(f"✓ Module '{name}' enabled", fg="green"))
    else:
        click.echo(click.style(f"✗ Failed to enable module '{name}'", fg="red"))
        sys.exit(1)


@main.command("disable")
@click.argument("name")
@click.option(
    "--project",
    "-p",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Project directory (default: current directory)",
)
def disable(name, project):
    """Disable a module by name."""
    project_dir = Path(project or os.getcwd())

    if disable_module(name, project_dir):
        click.echo(click.style(f"✓ Module '{name}' disabled", fg="green"))
    else:
        click.echo(click.style(f"✗ Failed to disable module '{name}'", fg="red"))
        sys.exit(1)


@main.command("info")
@click.argument("name")
@click.option(
    "--project",
    "-p",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Project directory (default: current directory)",
)
def info(name, project):
    """Show detailed information about a module."""
    project_dir = Path(project or os.getcwd())

    data = module_info(name, project_dir)
    if data is None:
        click.echo(click.style(f"✗ Module '{name}' not found", fg="red"))
        sys.exit(1)

    click.echo(f"Module: {click.style(data.get('name', name), fg='cyan', bold=True)}")
    click.echo()

    desc = data.get("description", "No description")
    click.echo(f"Description: {desc}")
    click.echo()

    enabled_status = data.get("enabled", False)
    status_str = click.style("enabled", fg="green") if enabled_status else click.style("disabled", fg="yellow")
    click.echo(f"Status: {status_str}")
    click.echo()

    detect = data.get("detect", {})
    if detect:
        click.echo("Detection:")
        for key, value in detect.items():
            click.echo(f"  {key}: {value}")
        click.echo()

    hooks = data.get("hooks", {})
    if hooks:
        click.echo("Lifecycle hooks:")
        for hook_name in hooks:
            click.echo(f"  • {hook_name}")
        click.echo()

    settings = data.get("settings", {})
    if settings:
        click.echo("Settings:")
        for key, value in settings.items():
            click.echo(f"  {key}: {value}")


if __name__ == "__main__":
    main()
