"""Tests for shux diff command."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    contract = {
        "project_path": str(tmp_path),
        "tasks": [
            {
                "id": "task-001",
                "title": "Test task",
                "owner": "claude-code",
                "status": "report_ready",
            }
        ],
    }
    (sh / "contract.yaml").write_text(yaml.dump(contract))
    return tmp_path


def test_diff_known_task(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    runner = CliRunner()
    result = runner.invoke(cmd_diff, ["task-001", "--project", str(project)])
    assert result.exit_code == 0
    # Either shows diff metadata or "no changes found"
    assert "task-001" in result.output or "no changes" in result.output


def test_diff_unknown_task_warns(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    runner = CliRunner()
    result = runner.invoke(cmd_diff, ["nonexistent-task", "--project", str(project)])
    assert result.exit_code == 0
    assert "warning" in result.output.lower() or "not found" in result.output.lower()


def test_diff_stat_flag(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    runner = CliRunner()
    # Should not crash even with --stat
    result = runner.invoke(cmd_diff, ["task-001", "--project", str(project), "--stat"])
    assert result.exit_code == 0


def test_diff_base_flag(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    runner = CliRunner()
    result = runner.invoke(cmd_diff, ["task-001", "--project", str(project), "--base", "HEAD"])
    assert result.exit_code == 0
