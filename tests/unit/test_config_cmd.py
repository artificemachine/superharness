"""Tests for shux config get/set (TDD: written before implementation)."""
from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "profile.yaml").write_text("default_model: claude-sonnet-4-6\n")
    return tmp_path


def test_config_set_writes_profile(runner, project):
    """shux config set budget.daily_limit 5.00 → profile.yaml updated."""
    from superharness.commands.config import cmd_config
    result = runner.invoke(cmd_config, [
        "set", "budget.daily_limit", "5.00",
        "--project", str(project),
    ])
    assert result.exit_code == 0, result.output
    doc = yaml.safe_load((project / ".superharness" / "profile.yaml").read_text())
    assert doc["budget"]["daily_limit"] == 5.00


def test_config_get_reads_profile(runner, project):
    """shux config get budget.daily_limit → prints the value."""
    profile = project / ".superharness" / "profile.yaml"
    profile.write_text(yaml.dump({"budget": {"daily_limit": 5.00}}))

    from superharness.commands.config import cmd_config
    result = runner.invoke(cmd_config, [
        "get", "budget.daily_limit",
        "--project", str(project),
    ])
    assert result.exit_code == 0, result.output
    assert "5" in result.output


def test_config_get_missing_key(runner, project):
    """shux config get nonexistent.key → helpful message, exit 0."""
    from superharness.commands.config import cmd_config
    result = runner.invoke(cmd_config, [
        "get", "nonexistent.key",
        "--project", str(project),
    ])
    assert result.exit_code == 0
    assert "not set" in result.output.lower() or "none" in result.output.lower() or result.output.strip() == ""
