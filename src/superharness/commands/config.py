"""shux config — get/set project profile settings.

Usage:
  shux config get <key>              # e.g. budget.daily_limit, default_model
  shux config set <key> <value>      # e.g. budget.daily_limit 5.00
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import yaml


def _profile_path(project: str) -> Path:
    return Path(project) / ".superharness" / "profile.yaml"


def _load_profile(project: str) -> dict:
    p = _profile_path(project)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}


def _save_profile(project: str, doc: dict) -> None:
    _profile_path(project).write_text(yaml.dump(doc, default_flow_style=False))


def _get_nested(doc: dict, key: str):
    """Traverse dot-separated key into nested dict. Returns None if missing."""
    parts = key.split(".")
    node = doc
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_nested(doc: dict, key: str, value) -> None:
    """Set dot-separated key in nested dict, creating intermediate dicts."""
    parts = key.split(".")
    node = doc
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _coerce(value: str):
    """Try to coerce a string value to float or bool before storing."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return float(value)
    except ValueError:
        return value


@click.group(name="config")
def cmd_config():
    """Get or set project profile settings."""


@cmd_config.command(name="get")
@click.argument("key")
@click.option("--project", default=None)
def config_get(key: str, project: Optional[str]) -> None:
    """Print the value of a profile key (dot-separated)."""
    project_dir = str(Path(project).resolve() if project else Path.cwd())
    doc = _load_profile(project_dir)
    val = _get_nested(doc, key)
    if val is None:
        click.echo(f"(not set)")
    else:
        click.echo(str(val))


@cmd_config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.option("--project", default=None)
def config_set(key: str, value: str, project: Optional[str]) -> None:
    """Set a profile key (dot-separated) to a value."""
    project_dir = str(Path(project).resolve() if project else Path.cwd())
    doc = _load_profile(project_dir)
    coerced = _coerce(value)
    _set_nested(doc, key, coerced)
    _save_profile(project_dir, doc)
    click.echo(f"Set {key} = {coerced}")
