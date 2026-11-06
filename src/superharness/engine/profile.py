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

from superharness.engine.errors import SuperharnessError, UsageError, handle_cli_error

_log = logging.getLogger(__name__)

FIELD_DEFAULTS: dict[str, str] = {
    "autonomy": "ai_driven",
    "primary_agent": "",
    "team_size": "solo",
}

# Legacy / UI alias → canonical name.  Add new modes here as they are introduced.
# "supervised" is intentionally NOT aliased — it is a distinct mode that preserves human oversight.
_AUTONOMY_ALIASES: dict[str, str] = {
    "full-auto": "ai_driven",
    "autonomous": "ai_driven",
    "approval-gated": "ai_driven",
    "oversight": "ai_driven",
    "hands_on": "ai_driven",
}


def normalize_autonomy(value: str | None) -> str:
    """Return the canonical autonomy string for *value*, falling back to ai_driven."""
    v = str(value or "").strip()
    return _AUTONOMY_ALIASES.get(v, v) or "ai_driven"


def load_profile_document(profile_path: str | os.PathLike[str]) -> object:
    """Parse profile.yaml, telling an empty file apart from an explicit null.

    Returns ``{}`` when the file has no YAML document (empty, or only comments
    and blank lines), the parsed root otherwise (``None`` for an explicit
    ``null`` or ``~`` document). Raises ``OSError`` or ``yaml.YAMLError`` when
    the file cannot be read or is not exactly one valid document.
    """
    import yaml

    with open(profile_path, encoding="utf-8") as fh:
        text = fh.read()
    if yaml.compose(text) is None:
        return {}
    return yaml.safe_load(text)


def plan_auto_approval_enabled(profile: object) -> bool:
    """Whether plan_proposed tasks are auto-approved under *profile*.

    *profile* is the parsed profile root, ``{}`` when there is no profile file
    or it is empty (see ``load_profile_document``). A missing
    ``auto_approve_plans`` key keeps the autonomy default: ``ai_driven``
    approves automatically, any other mode such as ``supervised`` keeps the
    operator in the loop. A key that is present must hold a real boolean and
    then wins. Anything else is malformed and refused rather than coerced: a
    present non-boolean (``"false"``, ``1``, null, a list), or a root that is
    not a mapping (including an explicit ``null`` document, so ``None``),
    disables auto-approval.
    """
    if not isinstance(profile, dict):
        # Name the type only: the raw content is untrusted input.
        _log.warning(
            "profile must be a mapping, got a %s: plan auto-approval stays off",
            type(profile).__name__,
        )
        return False
    if "auto_approve_plans" not in profile:
        return normalize_autonomy(profile.get("autonomy")) == "ai_driven"
    explicit = profile["auto_approve_plans"]
    if not isinstance(explicit, bool):
        _log.warning(
            "profile auto_approve_plans must be true or false, got a %s: "
            "plan auto-approval stays off",
            type(explicit).__name__,
        )
        return False
    return explicit


def auto_close_enabled(profile: object) -> bool:
    """Whether the watcher closes finished tasks on its own under *profile*.

    Same contract as ``plan_auto_approval_enabled``: *profile* is the parsed
    profile root (``{}`` for a missing or empty file). A missing ``auto_close``
    key keeps the autonomy default (``ai_driven`` closes automatically). A key
    that is present must hold a real boolean and then wins. Anything else is
    refused rather than coerced, because ``"false"`` is a truthy string: a
    present non-boolean, or a root that is not a mapping, disables auto-close.
    """
    if not isinstance(profile, dict):
        _log.warning(
            "profile must be a mapping, got a %s: auto-close stays off",
            type(profile).__name__,
        )
        return False
    if "auto_close" not in profile:
        return normalize_autonomy(profile.get("autonomy", "ai_driven")) == "ai_driven"
    explicit = profile["auto_close"]
    if not isinstance(explicit, bool):
        _log.warning(
            "profile auto_close must be true or false, got a %s: auto-close stays off",
            type(explicit).__name__,
        )
        return False
    return explicit


def task_auto_commit_enabled(profile: dict | None) -> bool:
    """Whether a closing task's worktree is committed locally under *profile*.

    Opt-in only: ``auto_commit_tasks`` must be the YAML boolean ``true``.
    A missing key leaves auto-commit off whatever the autonomy mode, and a
    mistyped value (``"true"``, ``1``, a list) is refused rather than coerced.
    The commit stays local: nothing is pushed.
    """
    if not isinstance(profile, dict):
        return False
    value = profile.get("auto_commit_tasks")
    if value is not None and not isinstance(value, bool):
        # Name the field and the type only: the raw value is untrusted input.
        _log.warning(
            "profile auto_commit_tasks must be true or false, got a %s: "
            "auto-commit stays off",
            type(value).__name__,
        )
    return value is True


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


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(
        prog="profile",
        description="Read a field from .superharness/profile.yaml.",
        add_help=True,
    )
    p.add_argument(
        "-p", "--project", default=os.getcwd(), help="Project directory (default: cwd)"
    )
    p.add_argument("field", nargs="?", default=None, help="Field name to read")
    opts = p.parse_args(argv)

    if not opts.field:
        raise UsageError("Usage: profile [--project DIR] FIELD", exit_code=2)

    project_dir = Path(opts.project).resolve()
    print(read_field(project_dir, opts.field))


if __name__ == "__main__":
    try:
        main()
    except SuperharnessError as e:
        handle_cli_error(e)


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
