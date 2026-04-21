"""Integration tests for shux handoff write."""
from __future__ import annotations

import json
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
    contract = f"""\
id: test
created: 2026-04-20
created_by: owner
status: active
tasks:
  - id: t-handoff
    title: Handoff write test
    owner: claude-code
    status: todo
    project_path: {tmp_path}
    workflow: implementation
  - id: parent-a
    title: Parent
    owner: claude-code
    status: in_progress
    subtasks:
      - id: parent-a.1
        title: Sub
        owner: claude-code
        model_tier: mini
        estimated_tokens: 100
        estimated_cost_usd: 0.01
        status: pending
"""
    (sh / "contract.yaml").write_text(contract)
    return tmp_path


def _run(args: list[str], cwd: Path):
    r = subprocess.run(
        [sys.executable, "-m", "superharness.commands.handoff_write"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    return r.returncode, r.stdout, r.stderr


def test_write_plan_handoff_inline_args(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "t-handoff",
         "--phase", "plan",
         "--from", "claude-code",
         "--to", "owner",
         "--plan", "Scope: add JSON output to five commands",
         "--tdd-red", "tests/.../test_cli_json_output.py",
         "--tdd-green", "Add --json flag",
         "--tdd-refactor", "Extract emit_json helper"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    files = list((project / ".superharness" / "handoffs").glob("t-handoff-plan-*.yaml"))
    assert len(files) == 1
    doc = yaml.safe_load(files[0].read_text())
    assert doc["task"] == "t-handoff"
    assert doc["phase"] == "plan"
    assert doc["from"] == "claude-code"
    assert doc["to"] == "owner"
    assert doc["status"] == "plan_proposed"
    assert "Scope" in doc["plan"]
    assert doc["tdd"]["red"].startswith("tests/")
    assert "green" in doc["tdd"]
    assert "refactor" in doc["tdd"]


def test_write_plan_handoff_from_file(project: Path, tmp_path: Path):
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n\nReplace stderr scraping with --json output on 5 commands.")
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "t-handoff", "--phase", "plan",
         "--from", "claude-code", "--to", "owner",
         "--plan", f"@{plan_file}",
         "--tdd-red", "failing tests",
         "--tdd-green", "minimal impl",
         "--tdd-refactor", "cleanup"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    files = list((project / ".superharness" / "handoffs").glob("t-handoff-plan-*.yaml"))
    doc = yaml.safe_load(files[0].read_text())
    assert "Replace stderr scraping" in doc["plan"]


def test_write_report_handoff(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "t-handoff", "--phase", "report",
         "--from", "claude-code", "--to", "owner",
         "--outcome", "Shipped JSON helper and --json on 5 commands",
         "--context", "See tests/integration/test_cli_json_output.py for expected payloads",
         "--tests-passed"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    files = list((project / ".superharness" / "handoffs").glob("t-handoff-report-*.yaml"))
    assert len(files) == 1
    doc = yaml.safe_load(files[0].read_text())
    assert doc["phase"] == "report"
    assert doc["status"] == "report_ready"
    assert "Shipped" in doc["outcome"]
    assert "context" in doc
    assert doc["tests_passed"] is True


def test_write_refuses_missing_task(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "does-not-exist", "--phase", "plan",
         "--from", "claude-code", "--to", "owner",
         "--plan", "x", "--tdd-red", "y"],
        project,
    )
    assert rc != 0
    # No handoff files should have been written
    assert not list((project / ".superharness" / "handoffs").glob("*.yaml"))
    assert "not found" in err.lower()


def test_write_refuses_plan_without_tdd(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "t-handoff", "--phase", "plan",
         "--from", "claude-code", "--to", "owner",
         "--plan", "some plan"],
        project,
    )
    assert rc != 0
    assert "tdd" in err.lower()


def test_write_refuses_report_without_outcome(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "t-handoff", "--phase", "report",
         "--from", "claude-code", "--to", "owner"],
        project,
    )
    assert rc != 0
    assert "outcome" in err.lower()


def test_write_resolves_subtask_id(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "parent-a.1", "--phase", "report",
         "--from", "claude-code", "--to", "owner",
         "--outcome", "subtask verified"],
        project,
    )
    assert rc == 0, f"stderr: {err}"


def test_write_json_mode(project: Path):
    rc, out, err = _run(
        ["write",
         "--project", str(project),
         "--task", "t-handoff", "--phase", "plan",
         "--from", "claude-code", "--to", "owner",
         "--plan", "p", "--tdd-red", "r", "--tdd-green", "g", "--tdd-refactor", "rf",
         "--json"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["task_id"] == "t-handoff"
    assert payload["phase"] == "plan"
    assert payload["path"].endswith(".yaml")


def test_write_refuses_overwrite_without_force(project: Path):
    common = [
        "write",
        "--project", str(project),
        "--task", "t-handoff", "--phase", "plan",
        "--from", "claude-code", "--to", "owner",
        "--plan", "p", "--tdd-red", "r", "--tdd-green", "g", "--tdd-refactor", "rf",
        "--out", "fixed-name.yaml",
    ]
    rc1, *_ = _run(common, project)
    assert rc1 == 0
    rc2, out2, err2 = _run(common, project)
    assert rc2 != 0
    assert "already exists" in err2.lower()

    rc3, *_ = _run(common + ["--force"], project)
    assert rc3 == 0
