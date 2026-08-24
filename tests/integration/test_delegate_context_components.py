"""Integration: `shux delegate`'s SDK path records dispatch context components.

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 4.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest


def _setup_project(tmp_path: Path) -> Path:
    """Create a project with a dispatchable task in SQLite (via YAML seed)."""
    from tests.helpers import seed_sqlite_from_yaml

    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: ctx-task\n    owner: claude-code\n    status: plan_approved\n"
        f"    project_path: '{project.as_posix()}'\n"
        "    acceptance_criteria:\n      - implement the feature\n"
    )
    seed_sqlite_from_yaml(project)
    return project


def _dispatch(project: Path):
    from superharness.commands.delegate import delegate

    with (
        patch("superharness.commands.delegate.sdk_available", return_value=True),
        patch("superharness.commands.delegate.SDKRunner") as mock_runner_class,
        patch("superharness.commands.delegate._confirm_non_interactive_risk"),
    ):
        mock_runner_class.return_value.run.return_value = {"output": ""}
        rc = delegate(
            str(project),
            "claude-code",
            "ctx-task",
            print_only=False,
            non_interactive=True,
            codex_bypass=False,
            skip_preflight=True,
            model_override="stub-model-for-test",
            effort_override="medium",
            no_orchestrate=True,
        )
    return rc, mock_runner_class


def test_sdk_dispatch_records_components(tmp_path):
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import context_dao

    project = _setup_project(tmp_path)

    rc, mock_runner_class = _dispatch(project)

    assert rc == 0
    assert mock_runner_class.return_value.run.called

    conn = get_connection(str(project))
    init_db(conn)
    try:
        dispatch_ids = context_dao.last_dispatches(conn, task_id="ctx-task", n=1)
        assert len(dispatch_ids) == 1
        components = context_dao.components_for_dispatch(conn, dispatch_ids[0])
    finally:
        conn.close()

    component_types = {component_type for _, component_type, _ in components}
    assert "task_instructions" in component_types
    assert len(components) >= 1


def test_recording_failure_does_not_block_dispatch(tmp_path, caplog):
    from superharness.commands.delegate import delegate
    from superharness.engine.state_errors import StateError

    project = _setup_project(tmp_path)

    with (
        patch("superharness.commands.delegate.sdk_available", return_value=True),
        patch("superharness.commands.delegate.SDKRunner") as mock_runner_class,
        patch("superharness.commands.delegate._confirm_non_interactive_risk"),
        patch(
            "superharness.engine.context_dao.record_dispatch",
            side_effect=StateError("boom"),
        ),
        caplog.at_level(logging.WARNING, logger="superharness.commands.delegate"),
    ):
        mock_runner_class.return_value.run.return_value = {"output": ""}
        rc = delegate(
            str(project),
            "claude-code",
            "ctx-task",
            print_only=False,
            non_interactive=True,
            codex_bypass=False,
            skip_preflight=True,
            model_override="stub-model-for-test",
            effort_override="medium",
            no_orchestrate=True,
        )

    assert rc == 0
    assert mock_runner_class.return_value.run.called, (
        "recording failure must not block the actual SDK dispatch"
    )
    assert any(
        "record dispatch context" in record.message for record in caplog.records
    ), "recording failure must be logged as a warning"
    assert not any(
        record.levelno > logging.WARNING for record in caplog.records
    )


if __name__ == "__main__":
    pytest.main([__file__])
