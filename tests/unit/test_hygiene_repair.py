"""Tests for hygiene --repair mode (harden.R4-repair)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import pytest

from superharness.engine.validate import (
    HELP_TEXT,
    _repair_append_ledger,
    _repair_create_handoff,
    _repair_fix_stuck_status,
    run_validate,
)

PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_project(
    tmp_path: Path,
    *,
    tasks: str = "",
    decisions: str = "[]",
    failures: str = "[]",
    ledger: str = "# Ledger\n",
) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text(
        f"id: test\ntasks:\n{tasks}"
        f"decisions: {decisions}\n"
        f"failures: {failures}\n"
    )
    (harness / "ledger.md").write_text(ledger)
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    seed_sqlite_from_yaml(project)
    return project


def _done_task_yaml(task_id: str = "task-a", verified: bool = True, status: str = "done") -> str:
    lines = [
        f"  - id: {task_id}",
        f"    status: {status}",
        f"    owner: claude-code",
    ]
    if verified:
        lines.append("    verified: true")
    return "\n".join(lines) + "\n"


def _run_validate_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.engine.validate"] + args,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

def test_repair_flag_in_help() -> None:
    """--repair must appear in help text."""
    assert "--repair" in HELP_TEXT


def test_repair_help_describes_read_only_without_flag() -> None:
    """Help must mention read-only behaviour when flag is absent."""
    assert "read-only" in HELP_TEXT or "Without --repair" in HELP_TEXT


def test_repair_flag_in_cli_help() -> None:
    r = _run_validate_cli(["--help"])
    assert "--repair" in r.stdout


# ---------------------------------------------------------------------------
# Missing handoff — repair
# ---------------------------------------------------------------------------

def test_repair_creates_skeleton_handoff(tmp_path: Path) -> None:
    """--repair creates a handoff YAML for a done task that has none."""
    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("my-task"),
        ledger="# Ledger\nmy-task done\n",
    )
    handoff_dir = project / ".superharness" / "handoffs"
    assert list(handoff_dir.glob("*.yaml")) == []

    rc = run_validate(str(project), repair=True)

    created = list(handoff_dir.glob("*.yaml"))
    assert len(created) == 1, f"Expected 1 handoff, got: {created}"
    assert rc == 0


def test_repair_handoff_contains_task_id(tmp_path: Path) -> None:
    """Skeleton handoff must reference the correct task id."""
    import yaml

    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("alpha-task"),
        ledger="# Ledger\nalpha-task done\n",
    )
    run_validate(str(project), repair=True)

    handoff_dir = project / ".superharness" / "handoffs"
    files = list(handoff_dir.glob("*.yaml"))
    assert files
    data = yaml.safe_load(files[0].read_text())
    assert data["task"] == "alpha-task"


def test_repair_handoff_is_valid_yaml(tmp_path: Path) -> None:
    """Skeleton handoff must be parseable YAML with required keys."""
    import yaml

    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("beta-task"),
        ledger="# Ledger\nbeta-task done\n",
    )
    run_validate(str(project), repair=True)

    handoff_dir = project / ".superharness" / "handoffs"
    data = yaml.safe_load(list(handoff_dir.glob("*.yaml"))[0].read_text())
    assert "task" in data
    assert "phase" in data
    assert "outcome" in data


def test_repair_appends_ledger_after_creating_handoff(tmp_path: Path) -> None:
    """Creating a skeleton handoff must log a [repair] line to ledger."""
    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("gamma-task"),
        ledger="# Ledger\ngamma-task done\n",
    )
    run_validate(str(project), repair=True)

    ledger = (project / ".superharness" / "ledger.md").read_text()
    assert "[repair]" in ledger
    assert "gamma-task" in ledger


# ---------------------------------------------------------------------------
# Missing ledger entry — repair
# ---------------------------------------------------------------------------

def test_repair_appends_ledger_for_missing_entry(tmp_path: Path) -> None:
    """--repair adds a ledger line when done task is absent from ledger."""
    project = _write_project(tmp_path, tasks=_done_task_yaml("delta-task"))
    handoffs = project / ".superharness" / "handoffs"
    (handoffs / "h.yaml").write_text("task: delta-task\nto: owner\n")

    rc = run_validate(str(project), repair=True)

    ledger = (project / ".superharness" / "ledger.md").read_text()
    assert "[repair]" in ledger
    assert "delta-task" in ledger
    assert rc == 0


def test_repair_ledger_entry_has_iso_timestamp(tmp_path: Path) -> None:
    """Ledger repair line must include an ISO 8601 timestamp."""
    import re

    project = _write_project(tmp_path, tasks=_done_task_yaml("eta-task"))
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: eta-task\n")

    run_validate(str(project), repair=True)

    ledger = (project / ".superharness" / "ledger.md").read_text()
    # Expect a line like: - 2026-03-27T12:34:56Z — [repair] — ...
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ledger)


# ---------------------------------------------------------------------------
# Read-only without --repair
# ---------------------------------------------------------------------------

def test_no_repair_does_not_create_handoff(tmp_path: Path) -> None:
    """Without --repair, no handoff file is created for a done task."""
    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("zeta-task"),
        ledger="# Ledger\nzeta-task done\n",
    )
    handoff_dir = project / ".superharness" / "handoffs"

    rc = run_validate(str(project), repair=False)

    assert list(handoff_dir.glob("*.yaml")) == []
    assert rc == 1


def test_no_repair_does_not_modify_ledger(tmp_path: Path) -> None:
    """Without --repair, ledger is not modified for a missing entry."""
    original_ledger = "# Ledger\n"
    project = _write_project(tmp_path, tasks=_done_task_yaml("theta-task"), ledger=original_ledger)
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: theta-task\n")

    run_validate(str(project), repair=False)

    assert (project / ".superharness" / "ledger.md").read_text() == original_ledger


# ---------------------------------------------------------------------------
# No duplicates
# ---------------------------------------------------------------------------

def test_repair_no_duplicate_handoff_if_exists(tmp_path: Path) -> None:
    """--repair must not create a second handoff when one already exists."""
    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("iota-task"),
        ledger="# Ledger\niota-task done\n",
    )
    handoff_dir = project / ".superharness" / "handoffs"
    (handoff_dir / "existing.yaml").write_text("task: iota-task\n")

    run_validate(str(project), repair=True)

    # Should still be exactly one (the pre-existing one)
    assert len(list(handoff_dir.glob("*.yaml"))) == 1


def test_repair_no_duplicate_ledger_entry_if_exists(tmp_path: Path) -> None:
    """--repair must not append a duplicate ledger entry when one already exists."""
    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("kappa-task"),
        ledger="# Ledger\nkappa-task done\n",
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: kappa-task\n")

    before = (project / ".superharness" / "ledger.md").read_text()
    run_validate(str(project), repair=True)
    after = (project / ".superharness" / "ledger.md").read_text()

    assert after == before  # nothing appended


# ---------------------------------------------------------------------------
# Clean project — no-op
# ---------------------------------------------------------------------------

def test_repair_noop_on_clean_project(tmp_path: Path) -> None:
    """--repair on a fully compliant project changes nothing and returns 0."""
    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("lambda-task"),
        ledger="# Ledger\nlambda-task done\n",
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: lambda-task\n")

    ledger_before = (project / ".superharness" / "ledger.md").read_text()
    rc = run_validate(str(project), repair=True)

    assert rc == 0
    assert (project / ".superharness" / "ledger.md").read_text() == ledger_before


# ---------------------------------------------------------------------------
# Stuck status
# ---------------------------------------------------------------------------

def test_repair_fixes_stuck_status(tmp_path: Path) -> None:
    """--repair sets status to done when verified=true but status!=done."""
    import yaml

    project = _write_project(
        tmp_path,
        tasks=_done_task_yaml("mu-task", verified=True, status="plan_approved"),
        ledger="# Ledger\nmu-task done\n",
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: mu-task\n")

    # Without repair, this task has status plan_approved and verified=true,
    # so it's a stuck status; adjust contract first so run_validate sees it
    (project / ".superharness" / "contract.yaml").write_text(
        "id: test\ntasks:\n"
        "  - id: mu-task\n"
        "    status: plan_approved\n"
        "    verified: true\n"
        "    owner: claude-code\n"
        "decisions: []\nfailures: []\n"
    )

    rc = run_validate(str(project), repair=True)

    contract = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    tasks_by_id = {t["id"]: t for t in contract["tasks"]}
    assert tasks_by_id["mu-task"]["status"] == "done"
    assert rc == 0


def test_repair_stuck_status_logged_in_ledger(tmp_path: Path) -> None:
    """Fixing stuck status must log a [repair] line to ledger."""
    project = _write_project(tmp_path, ledger="# Ledger\nnu-task done\n")
    (project / ".superharness" / "contract.yaml").write_text(
        "id: test\ntasks:\n"
        "  - id: nu-task\n"
        "    status: in_progress\n"
        "    verified: true\n"
        "    owner: claude-code\n"
        "decisions: []\nfailures: []\n"
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: nu-task\n")

    run_validate(str(project), repair=True)

    ledger = (project / ".superharness" / "ledger.md").read_text()
    assert "[repair]" in ledger
    assert "nu-task" in ledger


def test_no_repair_reports_stuck_status_as_issue(tmp_path: Path) -> None:
    """Without --repair, verified+non-done task counts as an issue (rc=1)."""
    project = _write_project(tmp_path, ledger="# Ledger\nxi-task done\n")
    (project / ".superharness" / "contract.yaml").write_text(
        "id: test\ntasks:\n"
        "  - id: xi-task\n"
        "    status: report_ready\n"
        "    verified: true\n"
        "    owner: claude-code\n"
        "decisions: []\nfailures: []\n"
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: xi-task\n")

    rc = run_validate(str(project), repair=False)
    assert rc == 1


# ---------------------------------------------------------------------------
# Multiple tasks
# ---------------------------------------------------------------------------

def test_repair_handles_multiple_tasks(tmp_path: Path) -> None:
    """--repair creates handoffs and ledger entries for multiple tasks at once."""
    import yaml as _yaml

    tasks_yaml = (
        "  - id: task-one\n    status: done\n    owner: cc\n    verified: true\n"
        "  - id: task-two\n    status: done\n    owner: cc\n    verified: true\n"
    )
    project = _write_project(
        tmp_path,
        tasks=tasks_yaml,
        ledger="# Ledger\ntask-one done\ntask-two done\n",
    )
    # No handoffs for either task
    handoff_dir = project / ".superharness" / "handoffs"

    rc = run_validate(str(project), repair=True)

    created = list(handoff_dir.glob("*.yaml"))
    assert len(created) == 2
    ids_in_handoffs = {_yaml.safe_load(f.read_text())["task"] for f in created}
    assert ids_in_handoffs == {"task-one", "task-two"}
    assert rc == 0


# ---------------------------------------------------------------------------
# Unit-level helpers
# ---------------------------------------------------------------------------

def test_repair_append_ledger_writes_repair_prefix(tmp_path: Path) -> None:
    """_repair_append_ledger writes a line containing [repair]."""
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n")
    _repair_append_ledger(str(ledger), "test message")
    content = ledger.read_text()
    assert "[repair]" in content
    assert "test message" in content


def test_repair_create_handoff_file_named_with_task_id(tmp_path: Path) -> None:
    """_repair_create_handoff includes task_id in the filename."""
    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    path = _repair_create_handoff("omicron-task", str(handoff_dir))
    assert "omicron-task" in Path(path).name
