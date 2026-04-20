"""Integration tests for the `archived` task status and bulk archive-done."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    (sh / "ledger.md").write_text("# Ledger\n")
    contract = f"""\
id: test
created: 2026-04-20
created_by: owner
status: active
tasks:
  - id: t-live
    title: Active task
    owner: claude-code
    status: in_progress
    project_path: {tmp_path}
  - id: t-done-1
    title: Done task 1
    owner: claude-code
    status: done
    project_path: {tmp_path}
  - id: t-done-2
    title: Done task 2
    owner: codex-cli
    status: done
    project_path: {tmp_path}
  - id: t-failed
    title: Failed task
    owner: claude-code
    status: failed
    project_path: {tmp_path}
"""
    (sh / "contract.yaml").write_text(contract)
    return tmp_path


def _run(module: str, args: list[str], cwd: Path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-m", module] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    return r.returncode, r.stdout, r.stderr


def _load_contract(project: Path) -> dict:
    return yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())


def test_archive_done_flips_all_done_tasks(project: Path):
    rc, out, err = _run(
        "superharness.commands.task",
        ["archive-done", "--project", str(project)],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    doc = _load_contract(project)
    tasks = {t["id"]: t for t in doc["tasks"]}
    assert tasks["t-done-1"]["status"] == "archived"
    assert tasks["t-done-2"]["status"] == "archived"
    # Non-done tasks left alone
    assert tasks["t-live"]["status"] == "in_progress"
    assert tasks["t-failed"]["status"] == "failed"
    assert "Archived 2 task(s)" in out


def test_archive_done_specific_ids(project: Path):
    rc, out, err = _run(
        "superharness.commands.task",
        ["archive-done", "--project", str(project), "--id", "t-done-1"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    doc = _load_contract(project)
    tasks = {t["id"]: t for t in doc["tasks"]}
    assert tasks["t-done-1"]["status"] == "archived"
    # Other done task untouched
    assert tasks["t-done-2"]["status"] == "done"


def test_archive_done_noop_when_nothing_done(project: Path):
    # First archive everything
    _run("superharness.commands.task", ["archive-done", "--project", str(project)], project)
    # Second run should be a no-op
    rc, out, err = _run(
        "superharness.commands.task",
        ["archive-done", "--project", str(project)],
        project,
    )
    assert rc == 0
    assert "No done tasks" in out


def test_contract_hides_archived_by_default(project: Path):
    _run("superharness.commands.task", ["archive-done", "--project", str(project)], project)
    rc, out, err = _run(
        "superharness.commands.contract_today",
        ["--project", str(project)],
        project,
    )
    assert rc == 0
    assert "t-live" in out
    assert "t-failed" in out
    # Archived tasks hidden
    assert "t-done-1" not in out
    assert "t-done-2" not in out
    # Hidden count surfaced
    assert "2 archived" in out


def test_contract_include_archived_flag(project: Path):
    _run("superharness.commands.task", ["archive-done", "--project", str(project)], project)
    rc, out, err = _run(
        "superharness.commands.contract_today",
        ["--project", str(project), "--include-archived"],
        project,
    )
    assert rc == 0
    # All tasks visible including archived
    assert "t-live" in out
    assert "t-done-1" in out
    assert "t-done-2" in out


def test_adapter_payload_emits_archived_status(project: Path):
    _run("superharness.commands.task", ["archive-done", "--project", str(project)], project)
    rc, out, err = _run(
        "superharness.commands.adapter_payload",
        ["--json", "--project", str(project)],
        project,
    )
    assert rc == 0
    import json
    doc = json.loads(out)
    tasks = {t["id"]: t for t in doc["tasks"]}
    assert tasks["t-done-1"]["status"] == "archived"
    assert tasks["t-done-2"]["status"] == "archived"
    # Morpheme can filter/show these based on status value
