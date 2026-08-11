"""Iteration 3 of PLAN-prime-agent-adoptions.md — release identity preflight.

Guards the recorded merged-vs-released confusion class (memory
`project_released_vs_merged_2026_05_30`): a `v*` tag whose version does not
match `pyproject.toml`, or that lacks a CHANGELOG entry, must fail before a
GitHub Release or PyPI publish happens — not be discovered after.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release_preflight.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import release_preflight  # noqa: E402

validate_release = release_preflight.validate_release
ReleasePreflightError = release_preflight.ReleasePreflightError


def _pyproject_text(version: str) -> str:
    return f'[project]\nname = "example"\nversion = "{version}"\n'


def _changelog_text(*entries: str) -> str:
    return "\n".join(f"- 2026-08-10: chore(release): bump version to {e}." for e in entries)


def test_accepts_matching_tag_version_and_changelog() -> None:
    identity = validate_release(
        tag="v1.2.3",
        pyproject_text=_pyproject_text("1.2.3"),
        changelog_text=_changelog_text("1.2.3"),
    )
    assert identity == {"tag": "v1.2.3", "version": "1.2.3"}


def test_rejects_version_mismatch() -> None:
    with pytest.raises(ReleasePreflightError) as exc_info:
        validate_release(
            tag="v1.2.3",
            pyproject_text=_pyproject_text("1.2.4"),
            changelog_text=_changelog_text("1.2.3"),
        )
    message = str(exc_info.value)
    assert "1.2.3" in message
    assert "1.2.4" in message


@pytest.mark.parametrize("bad_tag", ["1.2.3", "v1.2", "v01.2.3"])
def test_rejects_noncanonical_tag(bad_tag: str) -> None:
    with pytest.raises(ReleasePreflightError, match="canonical"):
        validate_release(
            tag=bad_tag,
            pyproject_text=_pyproject_text("1.2.3"),
            changelog_text=_changelog_text("1.2.3"),
        )


def test_rejects_missing_changelog_entry() -> None:
    with pytest.raises(ReleasePreflightError, match="CHANGELOG"):
        validate_release(
            tag="v1.2.3",
            pyproject_text=_pyproject_text("1.2.3"),
            changelog_text=_changelog_text("1.2.2"),
        )


def test_garbage_inputs_fail_closed() -> None:
    for tag in ("", "   "):
        with pytest.raises(ReleasePreflightError):
            validate_release(
                tag=tag,
                pyproject_text=_pyproject_text("1.2.3"),
                changelog_text=_changelog_text("1.2.3"),
            )

    with pytest.raises(ReleasePreflightError):
        validate_release(tag="v1.2.3", pyproject_text="", changelog_text=_changelog_text("1.2.3"))

    with pytest.raises(ReleasePreflightError):
        validate_release(tag="v1.2.3", pyproject_text=_pyproject_text("1.2.3"), changelog_text="")


def test_cli_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_cli_exit_codes(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject_text("1.2.3"))
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_changelog_text("1.2.3"))

    ok = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tag",
            "v1.2.3",
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    assert "1.2.3" in ok.stdout

    bad = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tag",
            "v9.9.9",
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1
    assert bad.stderr.strip() != ""
