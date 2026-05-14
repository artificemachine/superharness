"""Unit tests for superharness.commands.test_type."""
from __future__ import annotations

import subprocess
import sys
import yaml
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite


PYTHON = sys.executable


def _write_project(tmp_path: Path, *, tasks: str = "") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    contract_text = (
        "id: test\ncreated: '2026-01-01T00:00:00Z'\ncreated_by: owner\nstatus: active\n"
        f"tasks:\n{tasks}"
        "decisions: []\nfailures: []\n"
    )
    (harness / "contract.yaml").write_text(contract_text)

    # Seed SQLite so read_contract (always sqlite_only) finds the tasks.
    from superharness.engine.db import get_connection, init_db, transaction
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao
    doc = yaml.safe_load(contract_text) or {}
    conn = get_connection(str(project))
    init_db(conn)
    for task_dict in (doc.get("tasks") or []):
        if isinstance(task_dict, dict):
            with transaction(conn):
                tasks_dao.upsert(conn, _task_row_from_dict(task_dict, str(project), "2026-01-01T00:00:00Z"))
    conn.commit()
    conn.close()
    seed_sqlite_from_yaml(project)

    return project


def _get_task_sqlite(project: Path, task_id: str) -> dict:
    """Read a task directly from SQLite for post-command assertions."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from dataclasses import asdict
    conn = get_connection(str(project))
    init_db(conn)
    row = tasks_dao.get(conn, task_id)
    conn.close()
    if row is None:
        raise KeyError(f"task '{task_id}' not found in SQLite")
    return asdict(row)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.test_type"] + args,
        capture_output=True, text=True, check=False,
    )


def test_help() -> None:
    r = _run(["--help"])
    assert r.returncode == 0
    assert "--set" in r.stdout
    assert "--add" in r.stdout
    assert "--remove" in r.stdout
    assert "--show" in r.stdout


def test_requires_id() -> None:
    r = _run([])
    assert r.returncode != 0
    assert "--id is required" in r.stderr


def test_set_types(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n",
    )
    r = _run(["--id", "t1", "--set", "unit", "--set", "e2e", "-p", str(project)])
    assert r.returncode == 0
    assert "unit" in r.stdout
    assert "e2e" in r.stdout

    task = _get_task_sqlite(project, "t1")
    assert task["test_types"] == ["unit", "e2e"]


def test_add_type(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n",
    )
    r = _run(["--id", "t1", "--add", "smoke", "-p", str(project)])
    assert r.returncode == 0
    assert "smoke" in r.stdout

    task = _get_task_sqlite(project, "t1")
    assert "smoke" in task["test_types"]
    assert "unit" in task["test_types"]


def test_add_no_duplicate(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n",
    )
    r = _run(["--id", "t1", "--add", "unit", "-p", str(project)])
    assert r.returncode == 0

    task = _get_task_sqlite(project, "t1")
    assert task["test_types"].count("unit") == 1


def test_remove_type(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n      - e2e\n",
    )
    r = _run(["--id", "t1", "--remove", "e2e", "-p", str(project)])
    assert r.returncode == 0

    task = _get_task_sqlite(project, "t1")
    assert task["test_types"] == ["unit"]


def test_show_types(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n      - smoke\n",
    )
    r = _run(["--id", "t1", "--show", "-p", str(project)])
    assert r.returncode == 0
    assert "unit" in r.stdout
    assert "smoke" in r.stdout


def test_show_empty(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n",
    )
    r = _run(["--id", "t1", "--show", "-p", str(project)])
    assert r.returncode == 0
    assert "No test_types" in r.stdout


def test_task_not_found(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n",
    )
    r = _run(["--id", "nonexistent", "--show", "-p", str(project)])
    assert r.returncode != 0
    assert "not found" in r.stderr


def test_remove_all_clears_field(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n",
    )
    r = _run(["--id", "t1", "--remove", "unit", "-p", str(project)])
    assert r.returncode == 0
    assert "cleared" in r.stdout

    task = _get_task_sqlite(project, "t1")
    assert task["test_types"] == []


def test_all_requires_id_or_all() -> None:
    r = _run([])
    assert r.returncode != 0
    assert "--id is required" in r.stderr


def test_all_and_id_mutually_exclusive(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n",
    )
    r = _run(["--id", "t1", "--all", "--show", "-p", str(project)])
    assert r.returncode != 0
    assert "mutually exclusive" in r.stderr


def test_all_set_applies_to_all_tasks(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks=(
            "  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n"
            "  - id: t2\n    title: Task\n    status: todo\n    owner: claude-code\n"
        ),
    )
    r = _run(["--all", "--set", "unit", "--set", "smoke", "-p", str(project)])
    assert r.returncode == 0
    assert "t1" in r.stdout
    assert "t2" in r.stdout

    for tid in ("t1", "t2"):
        task = _get_task_sqlite(project, tid)
        assert task["test_types"] == ["unit", "smoke"]


def test_all_show(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks=(
            "  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n"
            "  - id: t2\n    title: Task\n    status: todo\n    owner: claude-code\n"
        ),
    )
    r = _run(["--all", "--show", "-p", str(project)])
    assert r.returncode == 0
    assert "t1" in r.stdout
    assert "t2" in r.stdout
    assert "unit" in r.stdout
    assert "No test_types" in r.stdout


def test_all_add_preserves_existing(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks=(
            "  - id: t1\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - unit\n"
            "  - id: t2\n    title: Task\n    status: todo\n    owner: claude-code\n    test_types:\n      - e2e\n"
        ),
    )
    r = _run(["--all", "--add", "smoke", "-p", str(project)])
    assert r.returncode == 0

    assert set(_get_task_sqlite(project, "t1")["test_types"]) == {"unit", "smoke"}
    assert set(_get_task_sqlite(project, "t2")["test_types"]) == {"e2e", "smoke"}


def test_hygiene_warns_done_task_with_test_types(tmp_path: Path) -> None:
    """Hygiene should warn when a done task has test_types set."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text(
        "id: test\ntasks:\n"
        "  - id: done-task\n    status: done\n    owner: claude-code\n"
        "    test_types:\n      - unit\n      - e2e\n"
        "decisions: []\nfailures: []\n"
    )
    (harness / "ledger.md").write_text("# Ledger\ndone-task completed\n")
    (harness / "handoffs" / "h.yaml").write_text("task: done-task\nto: claude-code\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    seed_sqlite_from_yaml(project)

    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.validate", "--project", str(project)],
        capture_output=True, text=True, check=False,
    )
    assert "requires test types [unit, e2e]" in r.stdout
