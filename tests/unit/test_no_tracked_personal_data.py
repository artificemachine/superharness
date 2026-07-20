"""Iteration 5 — no tracked file may contain the maintainer's real home path
or username. This is the standing contract: it's what actually enforces the
2026-07-20 audit's personal-data finding going forward, not `.shipguard.yml`'s
`sanitize_blocklist` (shipguard 0.5.2, as installed, does not consume that
key at all — grepping the installed package for `sanitize_blocklist` finds
no matches. Verified empirically while writing this test; not an assumption).

The maintainer identifier below is deliberately split across two string
literals rather than written as one contiguous token. `git grep` (and this
test's own file-scanning logic) match raw file bytes, not evaluated Python —
writing the token whole here would make this very file the next tracked
occurrence the test has to reject.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# See module docstring: split so this file's raw text never contains the
# maintainer's identifier as a contiguous substring.
_MAINTAINER = "air" + "m2max"

# This test file itself is exempt — it necessarily discusses the identifier
# (in split form) and the mechanics of the guard.
_SELF = "tests/unit/test_no_tracked_personal_data.py"


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def _read(rel: str) -> str:
    path = _REPO_ROOT / rel
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def test_no_home_paths_in_tracked_files():
    """No tracked file may reference the maintainer's real home directory."""
    offenders = []
    for rel in _tracked_files():
        if rel == _SELF:
            continue
        text = _read(rel)
        for prefix in (f"/Users/{_MAINTAINER}/", f"/home/{_MAINTAINER}/"):
            if prefix in text:
                offenders.append(rel)
                break
    assert not offenders, (
        f"tracked files reference the maintainer's real home path: {offenders}"
    )


def test_no_maintainer_username_in_tracked_files():
    """No tracked file may contain the bare username, with one exception:
    `.shipguard.yml` may reference it only via an env-var placeholder
    (`${SUPERHARNESS_MAINTAINER_USERNAME}`), never as the raw literal."""
    offenders = []
    for rel in _tracked_files():
        if rel == _SELF:
            continue
        text = _read(rel)
        if _MAINTAINER not in text:
            continue
        if rel == ".shipguard.yml":
            # Permitted only inside an env-var reference on the same line.
            bad_lines = [
                line for line in text.splitlines()
                if _MAINTAINER in line and "${" not in line
            ]
            if bad_lines:
                offenders.append(rel)
            continue
        offenders.append(rel)

    assert not offenders, (
        f"tracked files contain the maintainer's real username as a literal: "
        f"{offenders}"
    )
