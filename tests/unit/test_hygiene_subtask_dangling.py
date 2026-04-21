"""Unit tests for hygiene dangling-subtask check.

A 'done' parent with open subtasks (pending/in_progress/failed) should
produce a hygiene warning. A done parent with all subtasks resolved
(done or cancelled) should be clean.

An in-progress parent with open subtasks is not flagged — the gate only
cares about closed parents that have dangling sub-work.
"""
from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from superharness.engine.validate import run_validate


def _write_contract(tmp_path, tasks: list) -> str:
    harness_dir = tmp_path / ".superharness"
    harness_dir.mkdir(exist_ok=True)
    contract = {"tasks": tasks}
    (harness_dir / "contract.yaml").write_text(
        yaml.dump(contract, default_flow_style=False)
    )
    (harness_dir / "ledger.md").write_text("")
    (harness_dir / "handoffs").mkdir(exist_ok=True)
    (harness_dir / "decisions.yaml").write_text("decisions: []\n")
    (harness_dir / "failures.yaml").write_text("failures: []\n")
    return str(tmp_path)


def _done_task_with_subtasks(sub_statuses: list[str], task_id: str = "T-1") -> dict:
    subtasks = [
        {
            "id": f"{task_id}.{i+1}",
            "title": f"sub {i+1}",
            "status": s,
        }
        for i, s in enumerate(sub_statuses)
    ]
    return {
        "id": task_id,
        "title": "Parent",
        "owner": "claude-code",
        "status": "done",
        "verified": True,
        "subtasks": subtasks,
    }


def _handoff_for(tmp_path, task_id: str) -> None:
    hdir = tmp_path / ".superharness" / "handoffs"
    hdir.mkdir(parents=True, exist_ok=True)
    hfile = hdir / f"{task_id}-to-owner.yaml"
    hfile.write_text(yaml.dump({"task": task_id, "status": "done"}))


def _ledger_mention(tmp_path, task_id: str) -> None:
    harness_dir = tmp_path / ".superharness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    ledger = harness_dir / "ledger.md"
    ledger.write_text(f"- 2026-01-01 — actor — CLOSE: {task_id} — done\n")


class TestHygieneDanglingSubtasks:
    def test_done_parent_with_open_pending_subtask_warns(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["done", "pending"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert rc != 0
        assert "T-1" in out
        assert "open subtask" in out

    def test_done_parent_with_in_progress_subtask_warns(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["in_progress"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert rc != 0
        assert "open subtask" in out

    def test_done_parent_with_failed_subtask_warns(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["failed"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert rc != 0
        assert "open subtask" in out

    def test_done_parent_all_subtasks_done_is_clean(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["done", "done"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert rc == 0
        assert "open subtask" not in out

    def test_done_parent_all_subtasks_cancelled_is_clean(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["cancelled", "cancelled"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert rc == 0
        assert "open subtask" not in out

    def test_done_parent_mixed_done_and_cancelled_is_clean(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["done", "cancelled", "done"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert rc == 0
        assert "open subtask" not in out

    def test_in_progress_parent_with_open_subtasks_is_not_flagged(self, tmp_path, capsys):
        task = {
            "id": "T-2",
            "title": "In progress parent",
            "owner": "claude-code",
            "status": "in_progress",
            "subtasks": [{"id": "T-2.1", "title": "sub", "status": "pending"}],
        }
        project = _write_contract(tmp_path, [task])
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert "open subtask" not in out

    def test_done_parent_no_subtasks_is_clean(self, tmp_path, capsys):
        task = {
            "id": "T-3",
            "title": "No subtasks",
            "owner": "claude-code",
            "status": "done",
            "verified": True,
            "subtasks": [],
        }
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-3")
        _ledger_mention(tmp_path, "T-3")
        rc = run_validate(project)
        out = capsys.readouterr().out
        assert "open subtask" not in out

    def test_warning_includes_remediation_hint(self, tmp_path, capsys):
        task = _done_task_with_subtasks(["pending"])
        project = _write_contract(tmp_path, [task])
        _handoff_for(tmp_path, "T-1")
        _ledger_mention(tmp_path, "T-1")
        run_validate(project)
        out = capsys.readouterr().out
        assert "subtask-cancel" in out
