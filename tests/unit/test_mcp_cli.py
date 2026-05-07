"""Tests for MCP CLI subcommands — Iteration 10."""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from superharness.cli import main


def test_shux_mcp_subcommand_registered():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "mcp" in result.output.lower() or "start" in result.output.lower()


def test_shux_mcp_start_accepts_port_flag():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "start", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output


def test_shux_mcp_status_subcommand_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "status", "--help"])
    assert result.exit_code == 0


def test_shux_mcp_stop_subcommand_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "stop", "--help"])
    assert result.exit_code == 0
