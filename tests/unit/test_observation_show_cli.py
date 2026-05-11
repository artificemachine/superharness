"""Tests for shux observation show <id> CLI.

Verifies exit codes and stdout shape. Uses click's CliRunner against the
in-process command registered on the main CLI group.
"""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from superharness.cli import main
from superharness.engine.db import get_connection, init_db
from superharness.engine import observations_dao


@pytest.fixture
def project_with_observation(tmp_path, monkeypatch):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c = get_connection(str(project_dir))
    init_db(c, str(project_dir))
    new_id = observations_dao.insert(c, "t-1", "report_ready", "did things")
    c.close()
    monkeypatch.chdir(project_dir)
    return project_dir, new_id


def test_show_exit_0_when_found(project_with_observation):
    _proj, new_id = project_with_observation
    runner = CliRunner()
    result = runner.invoke(main, ["observation", "show", str(new_id)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["task_id"] == "t-1"
    assert payload["id"] == new_id


def test_show_exit_1_when_missing(project_with_observation):
    runner = CliRunner()
    result = runner.invoke(main, ["observation", "show", "9999"])
    assert result.exit_code == 1


def test_show_exit_2_when_invalid_id(project_with_observation):
    runner = CliRunner()
    result = runner.invoke(main, ["observation", "show", "abc"])
    assert result.exit_code == 2
