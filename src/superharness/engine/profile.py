"""Python port of engine/profile.rb.

Read a field from .superharness/profile.yaml.

Usage:
    python3 -m superharness.engine.profile --project /path/to/project FIELD

Outputs the field value to stdout and exits 0.
If profile.yaml is missing or the field is absent, outputs the default and exits 0.

Known fields and their defaults:
    autonomy       -> approval-gated
    primary_agent  -> (empty string)
    team_size      -> solo

Unknown fields return an empty string.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

FIELD_DEFAULTS: dict[str, str] = {
    "autonomy":      "approval-gated",
    "primary_agent": "",
    "team_size":     "solo",
}


def read_field(project_dir: Path, field: str) -> str:
    profile_path = project_dir / ".superharness" / "profile.yaml"
    if not profile_path.exists():
        return FIELD_DEFAULTS.get(field, "")
    try:
        import yaml
        doc = yaml.safe_load(profile_path.read_text()) or {}
    except Exception as e:
        _log.warning("could not parse profile.yaml at %s: %s", profile_path, e)
        print(f"Warning: could not parse profile.yaml: {e}", file=sys.stderr)
        return FIELD_DEFAULTS.get(field, "")
    if not isinstance(doc, dict):
        return FIELD_DEFAULTS.get(field, "")
    value = doc.get(field)
    if value is None:
        return FIELD_DEFAULTS.get(field, "")
    return str(value)


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(
        prog="profile",
        description="Read a field from .superharness/profile.yaml.",
        add_help=True,
    )
    p.add_argument("-p", "--project", default=os.getcwd(), help="Project directory (default: cwd)")
    p.add_argument("field", nargs="?", default=None, help="Field name to read")
    opts = p.parse_args(argv)

    if not opts.field:
        print("Usage: profile [--project DIR] FIELD", file=sys.stderr)
        sys.exit(2)

    project_dir = Path(opts.project).resolve()
    print(read_field(project_dir, opts.field))


if __name__ == "__main__":
    main()
