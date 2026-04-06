"""
Iteration 0 — CLI router unit tests (TDD: written before implementation).
Tests that each known subcommand is recognized and dispatched.
"""
import pytest
from click.testing import CliRunner
from superharness.cli import main

KNOWN_SUBCOMMANDS = [
    "init",
    "contract",
    "delegate",
    "enqueue",
    "task",
    "dispatch",
    "watch",
    "uninstall",
    "dashboard",
    "dashboard-ui",
    "monitor",       # compat alias
    "monitor-ui",    # compat alias
    "doctor",
    "install-wrapper",
    "recover",
    "normalize",
    "hygiene",
    "discuss",
    "watcher-worker",
    "benchmark",
    "daemon",
    "diff",
    "explain",
    "why",   # alias
    "wtf",   # alias
    "version",
]


@pytest.fixture
def runner():
    return CliRunner()


def test_help_exits_zero(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_version_subcommand(runner):
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0


@pytest.mark.parametrize("subcommand", KNOWN_SUBCOMMANDS)
def test_known_subcommand_is_recognized(runner, subcommand):
    """Every known subcommand must NOT produce 'No such command' error."""
    result = runner.invoke(main, [subcommand, "--help"])
    assert "No such command" not in result.output, (
        f"Subcommand '{subcommand}' not recognized: {result.output}"
    )
