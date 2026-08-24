"""Tests for `shux diff <id> --context`.

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 4.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


def _record(project, task_id, agent, comps):
    from superharness.engine.db import get_connection, init_db, now_iso
    from superharness.engine import context_dao

    conn = get_connection(str(project))
    init_db(conn)
    dispatch_id = context_dao.record_dispatch(
        conn, task_id=task_id, agent=agent, components=comps, now=now_iso()
    )
    conn.commit()
    conn.close()
    return dispatch_id


def test_diff_help_lists_context_flag():
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    runner = CliRunner()
    result = runner.invoke(cmd_diff, ["--help"])
    assert result.exit_code == 0
    assert "--context" in result.output


def test_context_flag_falls_back_to_git_when_single_dispatch(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    _record(project, "task-001", "claude-code", [("task_instructions", "abc")])

    runner = CliRunner()
    result = runner.invoke(
        cmd_diff, ["task-001", "--project", str(project), "--context"]
    )
    assert result.exit_code == 0
    assert "no prior dispatch" in result.output.lower()
    # falls back to the ordinary git-diff section below the context message
    assert "no changes found" in result.output or "diff --git" in result.output


def test_context_flag_reports_changed_component(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    _record(
        project,
        "task-001",
        "claude-code",
        [("system", "sys"), ("task_instructions", "v1")],
    )
    _record(
        project,
        "task-001",
        "claude-code",
        [("system", "sys"), ("task_instructions", "v2")],
    )

    runner = CliRunner()
    result = runner.invoke(
        cmd_diff, ["task-001", "--project", str(project), "--context"]
    )
    assert result.exit_code == 0

    lines = result.output.splitlines()
    changed_lines = [line for line in lines if line.startswith("changed:")]
    assert len(changed_lines) == 1
    assert "task_instructions" in changed_lines[0]

    unchanged_lines = [line for line in lines if line.startswith("unchanged:")]
    assert any("system" in line for line in unchanged_lines)


def test_context_flag_reports_added_and_removed_component(project):
    from click.testing import CliRunner
    from superharness.commands.diff import cmd_diff

    _record(project, "task-001", "claude-code", [("task_instructions", "v1")])
    _record(
        project,
        "task-001",
        "claude-code",
        [("task_instructions", "v1"), ("vault_block", "notes")],
    )

    runner = CliRunner()
    result = runner.invoke(
        cmd_diff, ["task-001", "--project", str(project), "--context"]
    )
    assert result.exit_code == 0
    assert "added: vault_block" in result.output

    # Third dispatch drops vault_block again: last-two diff must report removed.
    _record(project, "task-001", "claude-code", [("task_instructions", "v1")])
    result = runner.invoke(
        cmd_diff, ["task-001", "--project", str(project), "--context"]
    )
    assert result.exit_code == 0
    assert "removed: vault_block" in result.output
