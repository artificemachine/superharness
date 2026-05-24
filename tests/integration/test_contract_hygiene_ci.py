"""Test contract hygiene CI enforcement."""
import subprocess
import yaml
from pathlib import Path

from tests.helpers import SCRIPTS_DIR, seed_sqlite_from_yaml
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _setup_harness(harness: Path) -> None:
    """Init SQLite after writing contract.yaml — validate requires state.sqlite3."""
    seed_sqlite_from_yaml(harness.parent)


def test_hygiene_check_passes_with_valid_contract(tmp_path):
    """Verify hygiene check passes when done tasks have handoffs and ledger entries."""
    harness = tmp_path / ".superharness"
    harness.mkdir()

    # Create valid contract with done task
    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [
            {"id": "task-one", "status": "done", "title": "Test task", "verified": True}
        ],
        "decisions": [],
        "failures": []
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    _setup_harness(harness)

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

    # Seed SQLite for handoff and ledger (production code reads from SQLite)
    from tests.helpers import seed_sqlite_handoff, seed_sqlite_ledger
    seed_sqlite_handoff(tmp_path, "task-one", phase="report", status="done",
                        content="task: task-one\nstatus: done\n", now="2026-03-10T00:00:00Z")
    seed_sqlite_ledger(tmp_path, action="completed task-one", task_id="task-one",
                       now="2026-03-10T00:00:00Z")

    # Run check
    result = subprocess.run(
        [str(SCRIPTS_DIR / "check-contract-hygiene.sh"), "--project", str(tmp_path)],
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
    _setup_harness(harness)
    (harness / "ledger.md").write_text("# Ledger\n\n2026-03-10 completed task-orphan\n")

    handoffs = harness / "handoffs"
    handoffs.mkdir()
    # No handoff file created

    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    result = subprocess.run(
        [str(SCRIPTS_DIR / "check-contract-hygiene.sh"), "--project", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 1
    assert "Missing handoff for done task: task-orphan" in result.stdout


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
    _setup_harness(harness)
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
        [str(SCRIPTS_DIR / "check-contract-hygiene.sh"), "--project", str(tmp_path)],
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
    _setup_harness(harness)
    (harness / "ledger.md").write_text("# Ledger\n\n")

    handoffs = harness / "handoffs"
    handoffs.mkdir()

    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    result = subprocess.run(
        [str(SCRIPTS_DIR / "check-contract-hygiene.sh"), "--project", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert "passed" in result.stdout.lower()
