#!/usr/bin/env python3
"""Release identity preflight.

Binds a `v*` git tag to the version declared in `pyproject.toml` and to a
matching entry in `CHANGELOG.md`, and fails before a release is cut if
either is missing. This guards the failure class recorded after
2026-05-30: a tag pushed on a commit whose `pyproject.toml` was never
bumped, or whose CHANGELOG entry never landed, used to be discovered only
after `release.yml` had already created a GitHub Release and dispatched
`publish.yml`.

Stdlib only — no third-party imports. This module runs as a step in
`.github/workflows/release.yml`'s `verify-ci` job on bare `ubuntu-latest`
Python 3.11+, before any release artifact is created.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

_TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ReleasePreflightError(Exception):
    """Raised when a tag fails release identity validation."""


def validate_release(tag: str, pyproject_text: str, changelog_text: str) -> dict[str, str]:
    """Validate that `tag` is canonical, matches the version declared in
    `pyproject_text`, and that `changelog_text` contains an entry for that
    version.

    Returns ``{"tag": tag, "version": version}`` on success. Raises
    ``ReleasePreflightError`` on any failure — never an unhandled
    exception, even on garbage input.
    """
    tag = (tag or "").strip()
    match = _TAG_RE.match(tag)
    if not match:
        raise ReleasePreflightError(
            f"tag {tag!r} is not a canonical release tag — expected the form "
            "'vX.Y.Z' with no leading zeros (e.g. 'v1.2.3')"
        )
    tag_version = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"

    try:
        pyproject = tomllib.loads(pyproject_text or "")
    except tomllib.TOMLDecodeError as exc:
        raise ReleasePreflightError(f"pyproject.toml could not be parsed as TOML: {exc}") from exc

    try:
        pyproject_version = pyproject["project"]["version"]
    except (KeyError, TypeError) as exc:
        raise ReleasePreflightError(
            "pyproject.toml has no [project] version field"
        ) from exc

    if tag_version != pyproject_version:
        raise ReleasePreflightError(
            f"tag version {tag_version!r} does not match pyproject.toml version "
            f"{pyproject_version!r} — bump pyproject.toml before tagging"
        )

    if tag_version not in (changelog_text or ""):
        raise ReleasePreflightError(
            f"CHANGELOG.md has no entry mentioning version {tag_version!r} — "
            "add an appended CHANGELOG.md line for this release before tagging"
        )

    return {"tag": tag, "version": tag_version}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that a release tag's version matches pyproject.toml "
            "and has a CHANGELOG.md entry, before a release is cut."
        )
    )
    parser.add_argument("--tag", required=True, help="Git tag, e.g. v1.2.3")
    parser.add_argument("--pyproject", required=True, type=Path, help="Path to pyproject.toml")
    parser.add_argument("--changelog", required=True, type=Path, help="Path to CHANGELOG.md")
    args = parser.parse_args(argv)

    try:
        pyproject_text = args.pyproject.read_text()
    except OSError as exc:
        print(f"release preflight failed: could not read {args.pyproject}: {exc}", file=sys.stderr)
        return 1

    try:
        changelog_text = args.changelog.read_text()
    except OSError as exc:
        print(f"release preflight failed: could not read {args.changelog}: {exc}", file=sys.stderr)
        return 1

    try:
        identity = validate_release(args.tag, pyproject_text, changelog_text)
    except ReleasePreflightError as exc:
        print(f"release preflight failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(identity))
    return 0


if __name__ == "__main__":
    sys.exit(main())
