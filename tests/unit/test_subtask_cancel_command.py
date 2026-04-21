"""Unit tests for shux subtask-cancel command."""
from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from superharness.commands.subtask_cancel import cancel_subtask


def _make_contract(subtask_status: str = "pending", extra_subtasks: list | None = None) -> dict:
    subtasks = [
        {
            "id": "T-1.1",
            "title": "Write test",
            "model_tier": "standard",
            "owner": "claude-code",
            "estimated_tokens": 10000,
            "estimated_cost_usd": 0.05,
            "status": subtask_status,
        }
    ]
    if extra_subtasks:
        subtasks.extend(extra_subtasks)
    return {
        "tasks": [
            {
                "id": "T-1",
                "title": "Parent task",
                "owner": "claude-code",
                "status": "in_progress",
                "subtasks": subtasks,
            }
        ]
    }


def _setup(tmp_path, subtask_status: str = "pending", extra_subtasks: list | None = None):
    harness_dir = tmp_path / ".superharness"
    harness_dir.mkdir()
    contract_file = harness_dir / "contract.yaml"
    ledger_file = harness_dir / "ledger.md"
    ledger_file.write_text("")
    contract = _make_contract(subtask_status, extra_subtasks)
    contract_file.write_text(yaml.dump(contract, default_flow_style=False))
    return str(contract_file), str(ledger_file)


class TestCancelSubtask:
    def test_cancels_pending_subtask(self, tmp_path):
        contract_file, _ = _setup(tmp_path, "pending")
        rc = cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "scope shrunk")
        assert rc == 0
        doc = yaml.safe_load(open(contract_file))
        sub = doc["tasks"][0]["subtasks"][0]
        assert sub["status"] == "cancelled"

    def test_cancels_in_progress_subtask(self, tmp_path):
        contract_file, _ = _setup(tmp_path, "in_progress")
        rc = cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "no longer needed")
        assert rc == 0
        doc = yaml.safe_load(open(contract_file))
        assert doc["tasks"][0]["subtasks"][0]["status"] == "cancelled"

    def test_cancels_failed_subtask(self, tmp_path):
        contract_file, _ = _setup(tmp_path, "failed")
        rc = cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "retry path chosen")
        assert rc == 0
        doc = yaml.safe_load(open(contract_file))
        assert doc["tasks"][0]["subtasks"][0]["status"] == "cancelled"

    def test_refuses_to_cancel_done_subtask(self, tmp_path, capsys):
        contract_file, _ = _setup(tmp_path, "done")
        rc = cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "some reason")
        assert rc != 0
        err = capsys.readouterr().err
        assert "done" in err
        # status must not have changed
        doc = yaml.safe_load(open(contract_file))
        assert doc["tasks"][0]["subtasks"][0]["status"] == "done"

    def test_writes_ledger_line(self, tmp_path):
        contract_file, ledger_file = _setup(tmp_path, "pending")
        cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "obsolete after review")
        ledger = open(ledger_file).read()
        assert "SUBTASK_CANCEL" in ledger
        assert "T-1.1" in ledger
        assert "parent=T-1" in ledger
        assert "obsolete after review" in ledger

    def test_ledger_line_format(self, tmp_path):
        contract_file, ledger_file = _setup(tmp_path, "pending")
        cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "my reason")
        lines = [l for l in open(ledger_file).read().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0].startswith("- 20")
        assert "SUBTASK_CANCEL: T-1.1 (parent=T-1)" in lines[0]
        assert "my reason" in lines[0]

    def test_fails_when_task_not_found(self, tmp_path, capsys):
        contract_file, _ = _setup(tmp_path)
        rc = cancel_subtask(contract_file, "nonexistent", "T-1.1", "claude-code", "reason")
        assert rc != 0
        assert "not found" in capsys.readouterr().err

    def test_fails_when_subtask_not_found(self, tmp_path, capsys):
        contract_file, _ = _setup(tmp_path)
        rc = cancel_subtask(contract_file, "T-1", "T-1.99", "claude-code", "reason")
        assert rc != 0
        assert "not found" in capsys.readouterr().err

    def test_cancelled_subtask_stays_cancelled_in_round_trip(self, tmp_path):
        contract_file, _ = _setup(tmp_path, "pending")
        cancel_subtask(contract_file, "T-1", "T-1.1", "claude-code", "done")
        doc = yaml.safe_load(open(contract_file))
        sub = doc["tasks"][0]["subtasks"][0]
        assert sub["status"] == "cancelled"


class TestCancelSubtaskCLI:
    def test_cli_requires_reason(self, tmp_path):
        import sys
        from superharness.commands.subtask_cancel import main as cancel_main
        contract_file, _ = _setup(tmp_path)
        with pytest.raises(SystemExit) as exc:
            cancel_main(["--project", str(tmp_path), "--task", "T-1", "--sub", "T-1.1"])
        assert exc.value.code != 0

    def test_cli_requires_task(self, tmp_path):
        from superharness.commands.subtask_cancel import main as cancel_main
        with pytest.raises(SystemExit) as exc:
            cancel_main(["--project", str(tmp_path), "--sub", "T-1.1", "--reason", "x"])
        assert exc.value.code != 0

    def test_cli_requires_sub(self, tmp_path):
        from superharness.commands.subtask_cancel import main as cancel_main
        with pytest.raises(SystemExit) as exc:
            cancel_main(["--project", str(tmp_path), "--task", "T-1", "--reason", "x"])
        assert exc.value.code != 0
