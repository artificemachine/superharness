"""Integration tests for subtask visibility across CLI surfaces.

Builds a minimal .superharness/ fixture with a parent task that has subtasks,
then exercises adapter-payload, contract, recall, and context end-to-end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    (sh / "ledger.md").write_text("# Ledger\n")
    contract = """\
id: test-contract
created: 2026-04-20
created_by: owner
status: active
tasks:
  - id: parent-done
    title: Parent marked done
    owner: claude-code
    status: done
    subtasks:
      - id: parent-done.1
        title: First subtask of done parent
        owner: claude-code
        model_tier: mini
        estimated_tokens: 1000
        estimated_cost_usd: 0.001
        status: pending
      - id: parent-done.2
        title: Second subtask
        owner: claude-code
        model_tier: mini
        estimated_tokens: 1000
        estimated_cost_usd: 0.001
        status: pending
  - id: parent-active
    title: Parent in progress
    owner: claude-code
    status: in_progress
    subtasks:
      - id: parent-active.1
        title: Subtask of active parent
        owner: claude-code
        model_tier: mini
        estimated_tokens: 500
        estimated_cost_usd: 0.0005
        status: pending
"""
    (sh / "contract.yaml").write_text(contract)
    return tmp_path


def _run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    # Force UTF-8 on subprocess stdout/stderr so box-drawing and emoji chars
    # survive the Windows default cp1252 codec.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-m"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    return r.returncode, r.stdout, r.stderr


def test_adapter_payload_includes_subtask_status(project: Path):
    rc, out, err = _run(
        ["superharness.commands.adapter_payload", "--json", "--project", str(project)],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    doc = json.loads(out)
    tasks = {t["id"]: t for t in doc["tasks"]}

    # Done parent subtasks inherit done
    done_parent = tasks["parent-done"]
    subs = {s["id"]: s for s in done_parent["subtasks"]}
    assert subs["parent-done.1"]["status"] == "done"
    assert subs["parent-done.2"]["status"] == "done"

    # Active parent subtasks stay pending
    active_parent = tasks["parent-active"]
    active_subs = {s["id"]: s for s in active_parent["subtasks"]}
    assert active_subs["parent-active.1"]["status"] == "pending"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_contract_include_subtasks_renders_nested(project: Path):
    rc, out, err = _run(
        ["superharness.commands.contract_today",
         "--project", str(project), "--include-subtasks"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    # Top-level tasks present
    assert "parent-done" in out
    assert "parent-active" in out
    # Subtasks nested with indent marker
    assert "parent-done.1" in out
    assert "parent-done.2" in out
    assert "parent-active.1" in out
    assert "└" in out  # nested-row marker


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_contract_without_flag_hides_subtasks(project: Path):
    rc, out, err = _run(
        ["superharness.commands.contract_today", "--project", str(project)],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    assert "parent-done" in out
    # Subtasks not shown
    assert "parent-done.1" not in out
    assert "parent-active.1" not in out


def test_recall_finds_subtask_by_title(project: Path):
    rc, out, err = _run(
        ["superharness.engine.recall", "--project", str(project), "first subtask"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    assert "parent-done.1" in out


def test_context_resolves_subtask_id(project: Path):
    rc, out, err = _run(
        ["superharness.commands.context",
         "--project", str(project), "parent-done.1"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    assert "parent-done.1" in out
    # Should reference parent id in output
    assert "parent-done" in out
    # Effective status should be done (inherited)
    assert "done" in out.lower()
    # Should label it as Subtask, not Context
    assert "Subtask" in out


def test_context_top_level_task_unchanged(project: Path):
    rc, out, err = _run(
        ["superharness.commands.context",
         "--project", str(project), "parent-active"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    assert "parent-active" in out
    # Should NOT be labeled Subtask
    assert "Subtask:" not in out
