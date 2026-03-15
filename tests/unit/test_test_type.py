"""Unit tests for superharness.commands.test_type."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYTHON = sys.executable


def _write_project(tmp_path: Path, *, tasks: str = "") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        f"id: test\ntasks:\n{tasks}"
        "decisions: []\nfailures: []\n"
    )
    return project


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
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n",
    )
    r = _run(["--id", "t1", "--set", "unit", "--set", "e2e", "-p", str(project)])
    assert r.returncode == 0
    assert "unit" in r.stdout
    assert "e2e" in r.stdout

    # Verify persisted
    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = [t for t in doc["tasks"] if t["id"] == "t1"][0]
    assert task["test_types"] == ["unit", "e2e"]


def test_add_type(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n",
    )
    r = _run(["--id", "t1", "--add", "smoke", "-p", str(project)])
    assert r.returncode == 0
    assert "smoke" in r.stdout

    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = [t for t in doc["tasks"] if t["id"] == "t1"][0]
    assert "smoke" in task["test_types"]
    assert "unit" in task["test_types"]


def test_add_no_duplicate(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n",
    )
    r = _run(["--id", "t1", "--add", "unit", "-p", str(project)])
    assert r.returncode == 0

    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = [t for t in doc["tasks"] if t["id"] == "t1"][0]
    assert task["test_types"].count("unit") == 1


def test_remove_type(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n      - e2e\n",
    )
    r = _run(["--id", "t1", "--remove", "e2e", "-p", str(project)])
    assert r.returncode == 0

    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = [t for t in doc["tasks"] if t["id"] == "t1"][0]
    assert task["test_types"] == ["unit"]


def test_show_types(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n      - smoke\n",
    )
    r = _run(["--id", "t1", "--show", "-p", str(project)])
    assert r.returncode == 0
    assert "unit" in r.stdout
    assert "smoke" in r.stdout


def test_show_empty(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n",
    )
    r = _run(["--id", "t1", "--show", "-p", str(project)])
    assert r.returncode == 0
    assert "No test_types" in r.stdout


def test_task_not_found(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n",
    )
    r = _run(["--id", "nonexistent", "--show", "-p", str(project)])
    assert r.returncode != 0
    assert "not found" in r.stderr


def test_remove_all_clears_field(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n",
    )
    r = _run(["--id", "t1", "--remove", "unit", "-p", str(project)])
    assert r.returncode == 0
    assert "cleared" in r.stdout

    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = [t for t in doc["tasks"] if t["id"] == "t1"][0]
    assert "test_types" not in task


def test_all_requires_id_or_all() -> None:
    r = _run([])
    assert r.returncode != 0
    assert "--id is required" in r.stderr


def test_all_and_id_mutually_exclusive(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: t1\n    status: active\n    owner: claude-code\n",
    )
    r = _run(["--id", "t1", "--all", "--show", "-p", str(project)])
    assert r.returncode != 0
    assert "mutually exclusive" in r.stderr


def test_all_set_applies_to_all_tasks(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks=(
            "  - id: t1\n    status: active\n    owner: claude-code\n"
            "  - id: t2\n    status: active\n    owner: claude-code\n"
        ),
    )
    r = _run(["--all", "--set", "unit", "--set", "smoke", "-p", str(project)])
    assert r.returncode == 0
    assert "t1" in r.stdout
    assert "t2" in r.stdout

    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    for task in doc["tasks"]:
        assert task["test_types"] == ["unit", "smoke"]


def test_all_show(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks=(
            "  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n"
            "  - id: t2\n    status: active\n    owner: claude-code\n"
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
            "  - id: t1\n    status: active\n    owner: claude-code\n    test_types:\n      - unit\n"
            "  - id: t2\n    status: active\n    owner: claude-code\n    test_types:\n      - e2e\n"
        ),
    )
    r = _run(["--all", "--add", "smoke", "-p", str(project)])
    assert r.returncode == 0

    import yaml
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    tasks = {t["id"]: t for t in doc["tasks"]}
    assert set(tasks["t1"]["test_types"]) == {"unit", "smoke"}
    assert set(tasks["t2"]["test_types"]) == {"e2e", "smoke"}


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

    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.validate", "--project", str(project)],
        capture_output=True, text=True, check=False,
    )
    assert "requires test types [unit, e2e]" in r.stdout
