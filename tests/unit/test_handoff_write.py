"""Iteration 3 (PLAN-token-cost-accounting): self-reported token/cost usage
via shux handoff-write.

Agents with no programmatic usage data (Codex CLI, Gemini CLI, OpenCode) can
report input_tokens/output_tokens/cost_usd/model as optional fields on the
handoff payload they already write at every phase transition. A handoff with
no usage fields must behave exactly as before this change.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from tests.helpers import seed_sqlite_from_yaml


def _make_project(tmp_path: Path, task: dict) -> Path:
    project = tmp_path / "proj"
    sh = project / ".superharness"
    sh.mkdir(parents=True)
    (sh / "contract.yaml").write_text(yaml.dump({"id": "proj", "tasks": [task]}))
    seed_sqlite_from_yaml(project)
    return project


def _base_task() -> dict:
    return {
        "id": "t1",
        "title": "test task",
        "owner": "claude-code",
        "status": "todo",
        "workflow": "quick",
        "require_tdd": False,
        "autonomy": "oversight",
    }


def _write_handoff(project: Path, **extra):
    from superharness.commands.handoff_write import _build_parser, write_handoff

    args_list = [
        "--task", "t1",
        "--phase", "report",
        "--from", "codex-cli",
        "--to", "owner",
        "--outcome", "did the thing",
    ]
    for flag, value in extra.items():
        args_list += [flag, str(value)]
    args = _build_parser().parse_args(args_list)
    return write_handoff(project, args)


def _usage_rows(project: Path, task_id: str = "t1"):
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import usage_dao

    conn = get_connection(str(project))
    init_db(conn)
    rows = usage_dao.list_for_task(conn, task_id)
    conn.close()
    return rows


def test_handoff_write_without_usage_fields_unchanged(tmp_path: Path) -> None:
    project = _make_project(tmp_path, _base_task())
    rc, _result = _write_handoff(project)
    assert rc == 0
    assert _usage_rows(project) == []


def test_handoff_write_with_usage_fields_creates_task_usage_row(tmp_path: Path) -> None:
    project = _make_project(tmp_path, _base_task())
    rc, _result = _write_handoff(
        project,
        **{
            "--input-tokens": 500,
            "--output-tokens": 200,
            "--cost-usd": 0.05,
            "--model": "codex-cli",
        },
    )
    assert rc == 0
    rows = _usage_rows(project)
    assert len(rows) == 1
    assert rows[0].source == "handoff"
    assert rows[0].agent == "codex-cli"
    assert rows[0].model == "codex-cli"
    assert rows[0].input_tokens == 500
    assert rows[0].output_tokens == 200
    assert rows[0].cost_usd == 0.05


def test_handoff_write_partial_usage_fields_allowed(tmp_path: Path) -> None:
    project = _make_project(tmp_path, _base_task())
    rc, _result = _write_handoff(project, **{"--cost-usd": 0.03})
    assert rc == 0
    rows = _usage_rows(project)
    assert len(rows) == 1
    assert rows[0].cost_usd == 0.03
    assert rows[0].input_tokens is None
    assert rows[0].output_tokens is None
