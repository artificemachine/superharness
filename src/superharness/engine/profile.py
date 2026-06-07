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
    "autonomy":      "ai_driven",
    "primary_agent": "",
    "team_size":     "solo",
}

# Legacy / UI alias → canonical name.  Add new modes here as they are introduced.
# "supervised" is intentionally NOT aliased — it is a distinct mode that preserves human oversight.
_AUTONOMY_ALIASES: dict[str, str] = {
    "full-auto":      "ai_driven",
    "autonomous":     "ai_driven",
    "approval-gated": "ai_driven",
    "oversight":      "ai_driven",
    "hands_on":       "ai_driven",
}


def normalize_autonomy(value: str | None) -> str:
    """Return the canonical autonomy string for *value*, falling back to ai_driven."""
    v = str(value or "").strip()
    return _AUTONOMY_ALIASES.get(v, v) or "ai_driven"


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
    result = str(value)
    if field == "autonomy":
        result = normalize_autonomy(result)
    return result


def write_field(project_dir: Path, field: str, value: str) -> None:
    """Write a single field into .superharness/profile.yaml, preserving other keys."""
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(parents=True, exist_ok=True)
    profile_path = sh_dir / "profile.yaml"
    try:
        import yaml
        doc: dict = {}
        if profile_path.exists():
            doc = yaml.safe_load(profile_path.read_text()) or {}
            if not isinstance(doc, dict):
                doc = {}
        doc[field] = value
        profile_path.write_text(yaml.dump(doc, default_flow_style=False))
    except Exception as e:
        _log.warning("could not write profile.yaml at %s: %s", profile_path, e)
        raise


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


def write_field(project_dir: Path, field: str, value: str) -> None:
    """Write a single field to .superharness/profile.yaml atomically.

    Uses a tmp-file-then-rename strategy so a mid-write crash never
    leaves a half-written profile.
    """
    import os
    import tempfile
    import yaml

    profile_dir = project_dir / ".superharness"
    profile_path = profile_dir / "profile.yaml"

    # Load existing document (or start fresh)
    if profile_path.exists():
        try:
            doc = yaml.safe_load(profile_path.read_text()) or {}
        except Exception as e:
            _log.warning("could not parse profile.yaml at %s: %s", profile_path, e)
            doc = {}
    else:
        doc = {}

    if not isinstance(doc, dict):
        doc = {}

    doc[field] = value

    # Ensure the directory exists (handles the no-.superharness case)
    profile_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix=".profile-", suffix=".yaml", dir=str(profile_dir))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.dump(doc, fh, default_flow_style=False, allow_unicode=True)
        os.replace(str(tmp_path), str(profile_path))
        tmp_path = None  # rename succeeded; nothing to clean up
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
