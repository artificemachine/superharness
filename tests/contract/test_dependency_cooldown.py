"""Iteration 1 of PLAN-prime-agent-adoptions.md — dependency cooldown guard.

Dependabot proposes a PR the moment a new package version is published.
A 7-day cooldown gives a freshly-published (and potentially compromised or
buggy) release time to be caught by upstream maintainers or the community
before superharness's own dependency graph is exposed to it. This contract
test keeps that cooldown from being silently dropped from
`.github/dependabot.yml` in a future edit.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"

_MIN_COOLDOWN_DAYS = 7


def _load_updates() -> list[dict]:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text())
    return config["updates"]


def _find_ecosystem(ecosystem: str) -> dict:
    updates = _load_updates()
    matches = [u for u in updates if u.get("package-ecosystem") == ecosystem]
    assert matches, f"no dependabot update entry found for ecosystem {ecosystem!r}"
    return matches[0]


def test_pip_ecosystem_has_cooldown() -> None:
    entry = _find_ecosystem("pip")
    assert "cooldown" in entry, "pip ecosystem entry is missing a cooldown block"
    assert "default-days" in entry["cooldown"], (
        "pip ecosystem cooldown block is missing default-days"
    )


def test_github_actions_ecosystem_has_cooldown() -> None:
    entry = _find_ecosystem("github-actions")
    assert "cooldown" in entry, "github-actions ecosystem entry is missing a cooldown block"
    assert "default-days" in entry["cooldown"], (
        "github-actions ecosystem cooldown block is missing default-days"
    )


def test_cooldown_at_least_seven_days() -> None:
    updates = _load_updates()
    assert updates, "dependabot.yml has no update entries"
    below_floor = {
        entry["package-ecosystem"]: entry.get("cooldown", {}).get("default-days")
        for entry in updates
        if entry.get("cooldown", {}).get("default-days", 0) < _MIN_COOLDOWN_DAYS
    }
    assert not below_floor, (
        f"ecosystems below the {_MIN_COOLDOWN_DAYS}-day cooldown floor: {below_floor}"
    )
