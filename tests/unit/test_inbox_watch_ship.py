"""Tests for ship_on_complete missing-PR guard in inbox_watch."""
from __future__ import annotations

import yaml
from pathlib import Path

from superharness.commands.inbox_watch import _check_ship_on_complete_tasks


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / ".superharness" / "handoffs").mkdir(parents=True)
    return project


def _write_contract(project: Path, task: dict) -> None:
    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [task],
    }
    (project / ".superharness" / "contract.yaml").write_text(yaml.dump(contract))


def _read_contract(project: Path) -> dict:
    return yaml.safe_load(
        (project / ".superharness" / "contract.yaml").read_text()
    ) or {}


def _write_handoff(project: Path, task_id: str, outcomes: list[str]) -> None:
    handoff = {
        "id": f"hf-{task_id}",
        "task": task_id,
        "from": "claude-code",
        "to": "owner",
        "status": "report_ready",
        "outcomes": outcomes,
    }
    (project / ".superharness" / "handoffs" / f"{task_id}-report.yaml").write_text(
        yaml.dump(handoff)
    )


# ── missing PR URL → task marked failed ─────────────────────────────────────

def test_missing_pr_marks_task_failed(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _write_contract(project, {
        "id": "feat.ship-me",
        "status": "report_ready",
        "ship_on_complete": True,
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })
    _write_handoff(project, "feat.ship-me", outcomes=["implemented the feature"])

    _check_ship_on_complete_tasks(str(project))

    tasks = _read_contract(project).get("tasks", [])
    assert tasks[0]["status"] == "failed"


def test_pr_url_in_outcomes_task_stays_report_ready(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _write_contract(project, {
        "id": "feat.ship-me",
        "status": "report_ready",
        "ship_on_complete": True,
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })
    _write_handoff(project, "feat.ship-me", outcomes=[
        "implemented the feature",
        "PR: https://github.com/org/repo/pull/42",
    ])

    _check_ship_on_complete_tasks(str(project))

    tasks = _read_contract(project).get("tasks", [])
    assert tasks[0]["status"] == "report_ready"


def test_ship_on_complete_false_skipped(tmp_path: Path) -> None:
    """Tasks without ship_on_complete are not touched even at report_ready."""
    project = _make_project(tmp_path)
    _write_contract(project, {
        "id": "feat.normal",
        "status": "report_ready",
        "ship_on_complete": False,
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })
    # No handoff — if the guard ran it would fail; it should not run.
    _check_ship_on_complete_tasks(str(project))

    tasks = _read_contract(project).get("tasks", [])
    assert tasks[0]["status"] == "report_ready"


def test_no_handoff_marks_failed(tmp_path: Path) -> None:
    """ship_on_complete task at report_ready with no handoff at all → failed."""
    project = _make_project(tmp_path)
    _write_contract(project, {
        "id": "feat.ship-me",
        "status": "report_ready",
        "ship_on_complete": True,
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })
    # No handoff written.
    _check_ship_on_complete_tasks(str(project))

    tasks = _read_contract(project).get("tasks", [])
    assert tasks[0]["status"] == "failed"


def test_pr_url_as_bare_url_in_outcomes(tmp_path: Path) -> None:
    """A bare GitHub PR URL anywhere in outcomes is sufficient."""
    project = _make_project(tmp_path)
    _write_contract(project, {
        "id": "feat.ship-me",
        "status": "report_ready",
        "ship_on_complete": True,
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })
    _write_handoff(project, "feat.ship-me", outcomes=[
        "https://github.com/celstnblacc/superharness/pull/99",
    ])

    _check_ship_on_complete_tasks(str(project))

    tasks = _read_contract(project).get("tasks", [])
    assert tasks[0]["status"] == "report_ready"
