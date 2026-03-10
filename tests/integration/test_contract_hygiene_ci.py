"""Test contract hygiene CI enforcement."""
import os
import subprocess
import tempfile
import yaml
from pathlib import Path


def test_hygiene_check_passes_with_valid_contract(tmp_path):
    """Verify hygiene check passes when done tasks have handoffs and ledger entries."""
    harness = tmp_path / ".superharness"
    harness.mkdir()

    # Create valid contract with done task
    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [
            {"id": "task-one", "status": "done", "title": "Test task"}
        ],
        "decisions": [],
        "failures": []
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))

    # Create ledger with task mention
    (harness / "ledger.md").write_text("# Ledger\n\n2026-03-10 completed task-one\n")

    # Create handoff
    handoffs = harness / "handoffs"
    handoffs.mkdir()
    handoff = {
        "task": "task-one",
        "status": "done",
        "outcomes": ["completed successfully"]
    }
    (handoffs / "task-one.yaml").write_text(yaml.dump(handoff))

    # Create decisions and failures
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    # Run check
    result = subprocess.run(
        ["scripts/check-contract-hygiene.sh", "--project", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "passed" in result.stdout.lower()


def test_hygiene_check_fails_without_handoff(tmp_path):
    """Verify hygiene check fails when done task lacks handoff file."""
    harness = tmp_path / ".superharness"
    harness.mkdir()

    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [
            {"id": "task-orphan", "status": "done", "title": "Orphan task"}
        ],
        "decisions": [],
        "failures": []
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    (harness / "ledger.md").write_text("# Ledger\n\n2026-03-10 completed task-orphan\n")

    handoffs = harness / "handoffs"
    handoffs.mkdir()
    # No handoff file created

    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    result = subprocess.run(
        ["scripts/check-contract-hygiene.sh", "--project", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 1
    assert "Missing handoff file for done task: task-orphan" in result.stdout


def test_hygiene_check_fails_without_ledger_entry(tmp_path):
    """Verify hygiene check fails when done task not mentioned in ledger."""
    harness = tmp_path / ".superharness"
    harness.mkdir()

    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [
            {"id": "task-silent", "status": "done", "title": "Silent task"}
        ],
        "decisions": [],
        "failures": []
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    (harness / "ledger.md").write_text("# Ledger\n\n")  # Empty ledger

    handoffs = harness / "handoffs"
    handoffs.mkdir()
    handoff = {
        "task": "task-silent",
        "status": "done",
        "outcomes": ["completed"]
    }
    (handoffs / "task-silent.yaml").write_text(yaml.dump(handoff))

    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    result = subprocess.run(
        ["scripts/check-contract-hygiene.sh", "--project", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 1
    assert "Missing ledger mention for done task: task-silent" in result.stdout


def test_hygiene_check_skips_non_done_tasks(tmp_path):
    """Verify hygiene check only enforces handoff+ledger for done tasks."""
    harness = tmp_path / ".superharness"
    harness.mkdir()

    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [
            {"id": "task-todo", "status": "todo", "title": "Not done yet"},
            {"id": "task-in-progress", "status": "in_progress", "title": "Working"}
        ],
        "decisions": [],
        "failures": []
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    (harness / "ledger.md").write_text("# Ledger\n\n")

    handoffs = harness / "handoffs"
    handoffs.mkdir()

    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    result = subprocess.run(
        ["scripts/check-contract-hygiene.sh", "--project", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert "passed" in result.stdout.lower()
