"""
Iteration 0 — Unknown subcommand behavior (TDD: written before implementation).
Tests that unknown subcommands produce helpful error messages and non-zero exit.
"""
import pytest
from click.testing import CliRunner
from superharness.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_unknown_subcommand_exits_nonzero(runner):
    result = runner.invoke(main, ["not-a-real-command"])
    assert result.exit_code != 0


def test_unknown_subcommand_mentions_command_name(runner):
    result = runner.invoke(main, ["not-a-real-command"])
    assert "not-a-real-command" in result.output


def test_unknown_subcommand_suggests_help(runner):
    result = runner.invoke(main, ["not-a-real-command"])
    # Should mention --help or 'help' to guide the user
    assert "--help" in result.output or "help" in result.output.lower()


def test_no_args_shows_help(runner):
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "Usage" in result.output
