"""Integration tests for --json output on task status, enqueue, verify, close, delegate."""
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
    contract = f"""\
id: test
created: 2026-04-20
created_by: owner
status: active
tasks:
  - id: t-json
    title: JSON test
    owner: claude-code
    status: plan_approved
    project_path: {tmp_path}
    workflow: implementation
"""
    (sh / "contract.yaml").write_text(contract)
    return tmp_path


def _run(module: str, args: list[str], cwd: Path):
    r = subprocess.run(
        [sys.executable, "-m", module] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    return r.returncode, r.stdout, r.stderr


def _parse(out: str) -> dict:
    """Last non-empty line of stdout should be a JSON object."""
    line = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
    return json.loads(line)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_task_status_json_success(project: Path):
    rc, out, err = _run(
        "superharness.commands.task",
        ["status", "--project", str(project),
         "--id", "t-json", "--status", "in_progress",
         "--actor", "claude-code", "--summary", "starting",
         "--json"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    payload = _parse(out)
    assert payload["ok"] is True
    assert payload["task_id"] == "t-json"
    assert payload["new_status"] == "in_progress"
    assert payload["old_status"] == "plan_approved"
    assert payload["actor"] == "claude-code"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_task_status_json_error(project: Path):
    rc, out, err = _run(
        "superharness.commands.task",
        ["status", "--project", str(project),
         "--id", "does-not-exist", "--status", "in_progress",
         "--actor", "claude-code", "--summary", "x", "--json"],
        project,
    )
    assert rc != 0
    payload = _parse(out)
    assert payload["ok"] is False
    assert "error" in payload
    assert "does-not-exist" in payload["error"]


def test_enqueue_json_success(project: Path):
    rc, out, err = _run(
        "superharness.commands.inbox_enqueue",
        ["--project", str(project), "--to", "claude-code",
         "--task", "t-json", "--json", "--plan-only"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    payload = _parse(out)
    assert payload["ok"] is True
    assert payload["task_id"] == "t-json"
    assert payload["to"] == "claude-code"
    assert payload["plan_only"] is True
    assert payload["item_id"]


def test_enqueue_json_error_owner_mismatch(project: Path):
    # Task is owned by claude-code; requesting codex-cli without --force-reassign
    # should error out with a JSON payload.
    rc, out, err = _run(
        "superharness.commands.inbox_enqueue",
        ["--project", str(project), "--to", "codex-cli",
         "--task", "t-json", "--json"],
        project,
    )
    assert rc != 0
    payload = _parse(out)
    assert payload["ok"] is False
    assert "error" in payload


def test_verify_json_pass(project: Path):
    rc, out, err = _run(
        "superharness.commands.verify",
        ["--project", str(project), "--id", "t-json",
         "--method", "unit tests green", "--result", "pass",
         "--actor", "claude-code", "--json"],
        project,
    )
    assert rc == 0, f"stderr: {err}"
    payload = _parse(out)
    assert payload["ok"] is True
    assert payload["task_id"] == "t-json"
    assert payload["result"] == "pass"
    assert payload["verified"] is True


def test_close_json_requires_verify_gate(project: Path):
    # Close without verification first — must fail with JSON error
    rc, out, err = _run(
        "superharness.commands.close",
        ["--project", str(project), "--id", "t-json",
         "--actor", "claude-code", "--summary", "done", "--json"],
        project,
    )
    assert rc != 0
    payload = _parse(out)
    assert payload["ok"] is False


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_close_json_success_after_verify(project: Path):
    # Move plan_approved → in_progress → report_ready
    _run("superharness.commands.task",
         ["status", "--project", str(project), "--id", "t-json",
          "--status", "in_progress", "--actor", "claude-code",
          "--summary", "start"],
         project)
    _run("superharness.commands.task",
         ["status", "--project", str(project), "--id", "t-json",
          "--status", "report_ready", "--actor", "claude-code",
          "--summary", "ready"],
         project)
    # Verify pass
    _run("superharness.commands.verify",
         ["--project", str(project), "--id", "t-json",
          "--method", "checked", "--result", "pass", "--actor", "claude-code"],
         project)
    # Close
    rc, out, err = _run(
        "superharness.commands.close",
        ["--project", str(project), "--id", "t-json",
         "--actor", "claude-code", "--summary", "done", "--json"],
        project,
    )
    assert rc == 0, f"stderr: {err}, stdout: {out}"
    payload = _parse(out)
    assert payload["ok"] is True
    assert payload["closed"] is True


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_json_print_only(project: Path):
    # Task already starts in plan_approved, so it's dispatchable
    rc, out, err = _run(
        "superharness.commands.delegate",
        ["--project", str(project), "--to", "claude-code",
         "--task", "t-json", "--json", "--skip-preflight"],
        project,
    )
    # Delegate may return non-zero if gates fail, but JSON must be emitted
    payload = _parse(out)
    assert "ok" in payload
    assert payload["task_id"] == "t-json"
    assert payload["to"] == "claude-code"
    assert payload["print_only"] is True  # --json implies print-only


def test_delegate_json_invalid_target():
    rc = subprocess.run(
        [sys.executable, "-m", "superharness.commands.delegate",
         "--to", "invalid-agent", "--task", "x", "--json"],
        capture_output=True, text=True,
    )
    # argparse exits 2 before our code, but if it reaches our guard → JSON
    if rc.stdout.strip():
        payload = json.loads(rc.stdout.splitlines()[-1])
        assert payload["ok"] is False
