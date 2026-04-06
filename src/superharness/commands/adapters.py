"""shux adapters — list, inspect, and validate agent runtime adapters."""
from __future__ import annotations

import json
import os
import sys

import click

from superharness.engine.adapter_registry import (
    AdapterValidationError,
    adapter_info,
    list_adapters,
    validate_adapter,
)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """List, inspect, and validate agent runtime adapters."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd)


@main.command("list")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
def list_cmd(as_json):
    """List installed adapter manifests."""
    names = list_adapters()

    if as_json:
        rows = []
        for name in names:
            try:
                info = adapter_info(name)
                rows.append({"name": name, "valid": info["valid"], "issues": info["issues"]})
            except AdapterValidationError as e:
                rows.append({"name": name, "valid": False, "issues": [str(e)]})
        click.echo(json.dumps(rows, indent=2))
        return

    click.echo("superharness — adapters")
    click.echo("=" * 40)
    click.echo()

    if not names:
        click.echo(click.style("No adapter manifests found.", fg="yellow"))
        return

    for name in names:
        try:
            info = adapter_info(name)
            if info["valid"]:
                status = click.style("✓", fg="green")
            else:
                status = click.style("✗", fg="red")
            click.echo(f"  {status} {name}  — {info['description']}")
        except AdapterValidationError as e:
            click.echo(f"  {click.style('✗', fg='red')} {name}  — {e}")

    click.echo()
    click.echo("Run 'shux adapters info <name>' for details")
    click.echo("Run 'shux adapters test <name>' to validate an adapter")


@main.command("info")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
def info_cmd(name, as_json):
    """Show details for a specific adapter."""
    try:
        info = adapter_info(name)
    except AdapterValidationError as e:
        click.echo(click.style(f"✗ {e}", fg="red"), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(info, indent=2))
        return

    click.echo(f"Adapter: {click.style(info['name'], fg='cyan', bold=True)}")
    click.echo(f"Version: {info['version']}")
    click.echo(f"Type:    {info['type']}")
    click.echo()
    click.echo(f"Description: {info['description']}")
    click.echo()
    click.echo(f"Launcher: {info['launcher_script']}")
    click.echo()

    caps = info.get("capabilities") or []
    if caps:
        click.echo("Capabilities:")
        for cap in caps:
            click.echo(f"  • {cap}")
        click.echo()

    tiers = info.get("model_tiers") or {}
    if tiers:
        click.echo("Model tiers:")
        for tier, model in tiers.items():
            click.echo(f"  {tier:10s} → {model}")
        click.echo()

    requires = info.get("requires") or {}
    required_bin = requires.get("bin")
    if required_bin:
        click.echo(f"Requires binary: {required_bin}")
        click.echo()

    if info["valid"]:
        click.echo(click.style("✓ Adapter is valid and ready", fg="green"))
    else:
        click.echo(click.style("✗ Adapter has issues:", fg="red"))
        for issue in info["issues"]:
            click.echo(f"  • {issue}")


@main.command("test")
@click.argument("name")
def test_cmd(name):
    """Validate an adapter (check binary, env vars, manifest)."""
    try:
        manifest = validate_adapter(name)
        click.echo(click.style(f"✓ Adapter '{name}' is valid", fg="green"))
        click.echo(f"  Type:     {manifest.adapter_type}")
        click.echo(f"  Launcher: {manifest.launcher_script}")
        click.echo(f"  Version:  {manifest.version}")
        sys.exit(0)
    except AdapterValidationError as e:
        click.echo(click.style(f"✗ Adapter '{name}' failed validation:", fg="red"), err=True)
        click.echo(f"  {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
