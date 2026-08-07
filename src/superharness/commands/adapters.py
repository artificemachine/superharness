"""shux adapters — list, inspect, and validate agent runtime adapters.

Iteration 6 of PLAN-dynamic-model-selection.md adds ``--probe``: run model
discovery across every adapter and report which models are available per
agent (from the model-discovery cache or a fresh probe).
"""

from __future__ import annotations

import json
import sys

import click

from superharness.engine.adapter_registry import (
    AdapterValidationError,
    adapter_info,
    list_adapters,
    validate_adapter,
)


def _probe_available_models(project_dir: str | None) -> dict[str, list[str]]:
    """Return {adapter_name: [model ids]} for every adapter.

    Reads the model-discovery cache first; on a miss, runs harness
    discovery and persists the result (so a second call is cache-only).
    Never raises — failures surface as empty lists per adapter.
    """
    import sqlite3

    from superharness.engine.model_discovery import ModelDiscoveryCache
    from superharness.engine.model_router import (
        _discover_for_agent,
        _model_discovery_cache_path,
        detect_auth_mode_for_agent,
    )

    db_path = _model_discovery_cache_path(project_dir)
    result: dict[str, list[str]] = {}
    for name in list_adapters():
        auth_mode = detect_auth_mode_for_agent(name)
        cached = None
        if db_path:
            try:
                cache = ModelDiscoveryCache(db_path)
                cached = cache.get(project_dir, name, auth_mode)
            except (sqlite3.Error, OSError, ValueError):
                cached = None
        if cached:
            result[name] = [cached.id]
            continue
        try:
            discovered = _discover_for_agent(name, auth_mode)
        except (RuntimeError, OSError, KeyError, TypeError):
            result[name] = []
            continue
        if discovered:
            result[name] = [m.id for m in discovered]
            if db_path:
                try:
                    cache = ModelDiscoveryCache(db_path)
                    for m in discovered:
                        cache.set(project_dir, name, m)
                except (sqlite3.Error, OSError, ValueError):
                    pass
        else:
            result[name] = []
    return result


@click.group(invoke_without_command=True)
@click.option("--project", "-p", type=str, default=None, help="Project directory for cache lookup")
@click.option("--probe", "probe_flag", is_flag=True, default=False, help="Run model discovery across adapters")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
@click.pass_context
def main(ctx, project, probe_flag, as_json):
    """List, inspect, and validate agent runtime adapters."""
    if ctx.invoked_subcommand is None:
        if probe_flag:
            _probe_cmd(project, as_json)
        else:
            ctx.invoke(list_cmd)


def _probe_cmd(project: str | None, as_json: bool) -> None:
    """Run discovery across all adapters and report available models."""
    models = _probe_available_models(project)
    names = list_adapters()

    if as_json:
        rows = []
        for name in names:
            try:
                info = adapter_info(name)
                rows.append(
                    {
                        "name": name,
                        "valid": info["valid"],
                        "issues": info["issues"],
                        "available_models": models.get(name, []),
                    }
                )
            except AdapterValidationError as e:
                rows.append(
                    {
                        "name": name,
                        "valid": False,
                        "issues": [str(e)],
                        "available_models": [],
                        "failed": str(e),
                    }
                )
        click.echo(json.dumps(rows, indent=2))
        return

    click.echo("superharness — adapters --probe")
    click.echo("=" * 40)
    click.echo()
    for name in names:
        try:
            info = adapter_info(name)
            status = click.style("✓", fg="green") if info["valid"] else click.style("✗", fg="red")
        except AdapterValidationError as e:
            status = click.style("✗", fg="red")
            click.echo(f"  {status} {name}  — {e}")
            continue
        avail = models.get(name, [])
        if avail:
            models_str = ", ".join(avail[:3])
            if len(avail) > 3:
                models_str += f" (+{len(avail) - 3} more)"
        else:
            models_str = click.style("none discovered", fg="yellow")
        click.echo(f"  {status} {name}  — {info['description']}")
        click.echo(f"      models: {models_str}")
    click.echo()


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
                rows.append(
                    {"name": name, "valid": info["valid"], "issues": info["issues"]}
                )
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
        click.echo(
            click.style(f"✗ Adapter '{name}' failed validation:", fg="red"), err=True
        )
        click.echo(f"  {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
