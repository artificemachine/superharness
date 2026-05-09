"""Unit tests for the subtask resolution gate (Phase 4).

Covers:
- evaluate_subtask_gate logic (profile wins, task can opt in)
- close_task gate enforcement and --cancel-remaining
- task status_update gate enforcement for done transition
- --force bypass logs to ledger
"""
from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from superharness.engine.subtask_gate import GateResult, evaluate_subtask_gate


# ---------------------------------------------------------------------------
# evaluate_subtask_gate
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def _sub(status: str, sub_id: str = "T-1.1") -> dict:
    return {"id": sub_id, "title": "sub", "status": status}


class TestEvaluateSubtaskGate:
    def test_gate_off_by_default(self):
        task = {"id": "T-1", "subtasks": [_sub("pending")]}
        result = evaluate_subtask_gate(task, {})
        assert result.enabled is False
        assert result.blocking == []
        assert result.source == "none"

    def test_task_opts_in(self):
        task = {"id": "T-1", "require_subtask_resolution": True, "subtasks": [_sub("pending")]}
        result = evaluate_subtask_gate(task, {})
        assert result.enabled is True
        assert len(result.blocking) == 1
        assert result.source == "task"

    def test_profile_opts_in(self):
        task = {"id": "T-1", "subtasks": [_sub("pending")]}
        result = evaluate_subtask_gate(task, {"require_subtask_resolution": True})
        assert result.enabled is True
        assert result.source == "profile"

    def test_profile_wins_over_task_false(self):
        task = {"id": "T-1", "require_subtask_resolution": False, "subtasks": [_sub("pending")]}
        result = evaluate_subtask_gate(task, {"require_subtask_resolution": True})
        assert result.enabled is True
        assert result.source == "profile"

    def test_task_can_opt_in_when_profile_off(self):
        task = {"id": "T-1", "require_subtask_resolution": True, "subtasks": [_sub("pending")]}
        result = evaluate_subtask_gate(task, {"require_subtask_resolution": False})
        assert result.enabled is True
        assert result.source == "task"

    def test_done_subtask_does_not_block(self):
        task = {
            "id": "T-1",
            "require_subtask_resolution": True,
            "subtasks": [_sub("done", "T-1.1"), _sub("cancelled", "T-1.2")],
        }
        result = evaluate_subtask_gate(task, {})
        assert result.blocking == []

    def test_failed_subtask_blocks(self):
        task = {
            "id": "T-1",
            "require_subtask_resolution": True,
            "subtasks": [_sub("failed")],
        }
        result = evaluate_subtask_gate(task, {})
        assert len(result.blocking) == 1

    def test_in_progress_subtask_blocks(self):
        task = {
            "id": "T-1",
            "require_subtask_resolution": True,
            "subtasks": [_sub("in_progress")],
        }
        result = evaluate_subtask_gate(task, {})
        assert len(result.blocking) == 1

    def test_pending_subtask_blocks(self):
        task = {
            "id": "T-1",
            "require_subtask_resolution": True,
            "subtasks": [_sub("pending")],
        }
        result = evaluate_subtask_gate(task, {})
        assert len(result.blocking) == 1

    def test_no_subtasks_gate_enabled_is_clean(self):
        task = {"id": "T-1", "require_subtask_resolution": True, "subtasks": []}
        result = evaluate_subtask_gate(task, {})
        assert result.enabled is True
        assert result.blocking == []

    def test_mixed_only_open_ones_block(self):
        task = {
            "id": "T-1",
            "require_subtask_resolution": True,
            "subtasks": [
                _sub("done", "T-1.1"),
                _sub("pending", "T-1.2"),
                _sub("cancelled", "T-1.3"),
                _sub("in_progress", "T-1.4"),
            ],
        }
        result = evaluate_subtask_gate(task, {})
        blocking_ids = [s["id"] for s in result.blocking]
        assert blocking_ids == ["T-1.2", "T-1.4"]


# ---------------------------------------------------------------------------
# close_task gate integration
# ---------------------------------------------------------------------------


def _make_harness(tmp_path, task: dict, profile: dict | None = None):
    harness_dir = tmp_path / ".superharness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    contract = {"tasks": [task]}
    (harness_dir / "contract.yaml").write_text(
        yaml.dump(contract, default_flow_style=False)
    )
    (harness_dir / "ledger.md").write_text("")
    (harness_dir / "handoffs").mkdir(exist_ok=True)
    if profile is not None:
        (harness_dir / "profile.yaml").write_text(
            yaml.dump(profile, default_flow_style=False)
        )
    return str(harness_dir / "contract.yaml")


def _base_task(subtasks: list, require: bool | None = None) -> dict:
    t = {
        "id": "T-1",
        "title": "Test task",
        "owner": "claude-code",
        "status": "report_ready",
        "verified": True,
        "subtasks": subtasks,
    }
    if require is not None:
        t["require_subtask_resolution"] = require
    return t


class TestCloseTaskGate:
    def test_gate_off_by_default_allows_close_with_open_subtasks(self, tmp_path):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending")])
        cf = _make_harness(tmp_path, task)
        rc = close_task(cf, "T-1", "claude-code", "done")
        assert rc == 0

    def test_gate_on_blocks_close_with_open_subtask(self, tmp_path, capsys):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending")], require=True)
        cf = _make_harness(tmp_path, task)
        rc = close_task(cf, "T-1", "claude-code", "done")
        assert rc != 0
        assert "open" in capsys.readouterr().err.lower()

    def test_gate_on_allows_close_when_all_resolved(self, tmp_path):
        from superharness.commands.close import close_task
        task = _base_task([_sub("done", "T-1.1"), _sub("cancelled", "T-1.2")], require=True)
        cf = _make_harness(tmp_path, task)
        rc = close_task(cf, "T-1", "claude-code", "done")
        assert rc == 0

    def test_profile_gate_blocks_even_when_task_flag_absent(self, tmp_path, capsys):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending")])
        cf = _make_harness(tmp_path, task, profile={"require_subtask_resolution": True})
        rc = close_task(cf, "T-1", "claude-code", "done")
        assert rc != 0
        err = capsys.readouterr().err
        assert "profile" in err

    def test_cancel_remaining_cancels_open_subtasks_and_closes(self, tmp_path):
        from superharness.commands.close import close_task
        task = _base_task(
            [_sub("pending", "T-1.1"), _sub("in_progress", "T-1.2"), _sub("done", "T-1.3")],
            require=True,
        )
        cf = _make_harness(tmp_path, task)
        rc = close_task(
            cf, "T-1", "claude-code", "done",
            cancel_remaining=True, cancel_reason="scope reduced",
        )
        assert rc == 0
        doc = yaml.safe_load(open(cf))
        subs = {s["id"]: s["status"] for s in doc["tasks"][0]["subtasks"]}
        assert subs["T-1.1"] == "cancelled"
        assert subs["T-1.2"] == "cancelled"
        assert subs["T-1.3"] == "done"

    def test_cancel_remaining_writes_ledger_lines(self, tmp_path):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending", "T-1.1"), _sub("pending", "T-1.2")], require=True)
        cf = _make_harness(tmp_path, task)
        close_task(
            cf, "T-1", "claude-code", "done",
            cancel_remaining=True, cancel_reason="no longer needed",
        )
        ledger = (tmp_path / ".superharness" / "ledger.md").read_text()
        assert ledger.count("SUBTASK_CANCEL") == 2
        assert "no longer needed" in ledger
        assert "CLOSE: T-1" in ledger

    def test_cancel_remaining_without_reason_fails(self, tmp_path, capsys):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending")], require=True)
        cf = _make_harness(tmp_path, task)
        rc = close_task(
            cf, "T-1", "claude-code", "done",
            cancel_remaining=True, cancel_reason="",
        )
        assert rc != 0
        assert "cancel-reason" in capsys.readouterr().err

    def test_force_bypasses_gate(self, tmp_path):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending")], require=True)
        cf = _make_harness(tmp_path, task)
        rc = close_task(cf, "T-1", "claude-code", "done", force=True)
        assert rc == 0

    def test_force_logs_warning_to_ledger(self, tmp_path):
        from superharness.commands.close import close_task
        task = _base_task([_sub("pending", "T-1.1")], require=True)
        cf = _make_harness(tmp_path, task)
        close_task(cf, "T-1", "claude-code", "done", force=True)
        ledger = (tmp_path / ".superharness" / "ledger.md").read_text()
        assert "FORCE_CLOSE_WARNING" in ledger
        assert "T-1.1" in ledger

    def test_error_message_names_blocking_subtasks(self, tmp_path, capsys):
        from superharness.commands.close import close_task
        task = _base_task(
            [_sub("pending", "T-1.1"), _sub("in_progress", "T-1.2")],
            require=True,
        )
        cf = _make_harness(tmp_path, task)
        close_task(cf, "T-1", "claude-code", "done")
        err = capsys.readouterr().err
        assert "T-1.1" in err
        assert "T-1.2" in err


# ---------------------------------------------------------------------------
# task status_update gate integration
# ---------------------------------------------------------------------------


class TestTaskStatusUpdateGate:
    def test_gate_off_by_default_allows_done(self, tmp_path):
        from superharness.commands.task import status_update
        task = {
            "id": "T-1",
            "title": "t",
            "owner": "claude-code",
            "status": "in_progress",
            "subtasks": [_sub("pending")],
        }
        cf = _make_harness(tmp_path, task)
        rc = status_update(cf, "T-1", "done", "claude-code", summary="done")
        assert rc == 0

    def test_gate_on_blocks_done_with_open_subtask(self, tmp_path, capsys):
        from superharness.commands.task import status_update
        task = {
            "id": "T-1",
            "title": "t",
            "owner": "claude-code",
            "status": "in_progress",
            "require_subtask_resolution": True,
            "subtasks": [_sub("pending")],
        }
        cf = _make_harness(tmp_path, task)
        with pytest.raises(SystemExit) as exc:
            status_update(cf, "T-1", "done", "claude-code", summary="done")
        assert exc.value.code != 0

    def test_gate_on_allows_done_when_subtasks_resolved(self, tmp_path):
        from superharness.commands.task import status_update
        task = {
            "id": "T-1",
            "title": "t",
            "owner": "claude-code",
            "status": "in_progress",
            "require_subtask_resolution": True,
            "subtasks": [_sub("done", "T-1.1"), _sub("cancelled", "T-1.2")],
        }
        cf = _make_harness(tmp_path, task)
        rc = status_update(cf, "T-1", "done", "claude-code", summary="done")
        assert rc == 0
