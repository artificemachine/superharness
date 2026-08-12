"""TDD coverage for progressive root CLI help."""

from __future__ import annotations

import re

from click.testing import CliRunner

from superharness.cli import main


CORE_COMMANDS = [
    "onboard",
    "task",
    "contract",
    "delegate",
    "status",
    "context",
    "verify",
    "close",
    "dashboard",
    "doctor",
    "recall",
    "explain",
]
COMPAT_ALIASES = {"discussion", "monitor", "monitor-ui"}


def _section(output: str, heading: str) -> str:
    start = output.index(heading)
    remainder = output[start + len(heading) :]
    return remainder.split("\n\n", 1)[0]


def test_default_help_lists_exact_core_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0, result.output
    core = _section(result.output, "Core commands:")
    assert [name for name in CORE_COMMANDS if name in core] == CORE_COMMANDS


def test_default_help_lists_four_domain_entry_points() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0, result.output
    more = _section(result.output, "More commands:")
    for name in ("state", "agent", "ops", "memory"):
        assert name in more
    assert "shux help --all" in result.output


def test_help_all_lists_every_canonical_command_once() -> None:
    result = CliRunner().invoke(main, ["help", "--all"])

    assert result.exit_code == 0, result.output
    for name in main.commands:
        if name not in COMPAT_ALIASES | {"help"}:
            assert len(re.findall(rf"^  {re.escape(name)}\s{{2,}}", result.output, re.M)) == 1, name


def test_help_without_all_matches_root_help() -> None:
    runner = CliRunner()

    root = runner.invoke(main, ["--help"])
    alias = runner.invoke(main, ["help"])

    assert root.exit_code == alias.exit_code == 0
    assert alias.output == root.output


def test_compat_aliases_never_appear_in_help() -> None:
    runner = CliRunner()

    for args in (["--help"], ["help", "--all"]):
        result = runner.invoke(main, args)
        assert result.exit_code == 0, result.output
        for alias in COMPAT_ALIASES:
            assert f"  {alias}" not in result.output


def test_onboarding_banner_survives_progressive_help() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0, result.output
    assert "New here?" in result.output
