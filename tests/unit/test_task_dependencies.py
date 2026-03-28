"""Tests for feat.task-dependencies — blocked_by field and lifecycle gates.

RED phase: all tests should fail before implementation.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import os

import yaml

PYTHON = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(tmp_path: Path, tasks: list[dict]) -> tuple[Path, Path]:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "handoffs").mkdir(exist_ok=True)
    (harness / "ledger.md").write_text("# Ledger\n")
    contract = harness / "contract.yaml"
    # Resolve project_path in tasks that use the sentinel "__project__"
    resolved = []
    for t in tasks:
        t2 = dict(t)
        if t2.get("project_path") == "__project__":
            t2["project_path"] = str(project)
        resolved.append(t2)
    data = {"id": "test-contract", "tasks": resolved}
    contract.write_text(yaml.dump(data, default_flow_style=False))
    return project, contract


def _run_task(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.task"] + args,
        capture_output=True, text=True, check=False,
    )


def _run_delegate(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.delegate"] + args,
        capture_output=True, text=True, check=False, env=env,
    )


def _run_close(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.close"] + args,
        capture_output=True, text=True, check=False,
    )


# ---------------------------------------------------------------------------
# Task create — blocked_by field
# ---------------------------------------------------------------------------

class TestBlockedByCreate:
    def test_blocked_by_none_written_on_create(self, tmp_path):
        """task create with no --blocked-by stores blocked_by: none in contract."""
        project, contract = _make_contract(tmp_path, [])
        r = _run_task([
            "create", "--project", str(project),
            "--id", "feat.new", "--title", "New feature",
            "--owner", "claude-code",
        ])
        assert r.returncode == 0, r.stderr
        data = yaml.safe_load(contract.read_text())
        task = next(t for t in data["tasks"] if t["id"] == "feat.new")
        assert task.get("blocked_by") == "none"

    def test_blocked_by_task_written_on_create(self, tmp_path):
        """task create with --blocked-by stores the dependency ID."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.dep", "title": "Dep", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
        ])
        r = _run_task([
            "create", "--project", str(project),
            "--id", "feat.child", "--title", "Child",
            "--owner", "claude-code",
            "--blocked-by", "feat.dep",
        ])
        assert r.returncode == 0, r.stderr
        data = yaml.safe_load(contract.read_text())
        task = next(t for t in data["tasks"] if t["id"] == "feat.child")
        assert task.get("blocked_by") == "feat.dep"

    def test_blocked_by_none_accepted(self, tmp_path):
        """blocked_by=none is explicitly valid."""
        project, contract = _make_contract(tmp_path, [])
        r = _run_task([
            "create", "--project", str(project),
            "--id", "feat.x", "--title", "X",
            "--owner", "claude-code",
            "--blocked-by", "none",
        ])
        assert r.returncode == 0, r.stderr

    def test_blocked_by_list_accepted(self, tmp_path):
        """blocked_by can be a comma-separated list of task IDs."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.a", "title": "A", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
            {"id": "feat.b", "title": "B", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
        ])
        r = _run_task([
            "create", "--project", str(project),
            "--id", "feat.child", "--title", "Child",
            "--owner", "claude-code",
            "--blocked-by", "feat.a,feat.b",
        ])
        assert r.returncode == 0, r.stderr
        data = yaml.safe_load(contract.read_text())
        task = next(t for t in data["tasks"] if t["id"] == "feat.child")
        blocked = task.get("blocked_by")
        assert isinstance(blocked, list)
        assert "feat.a" in blocked
        assert "feat.b" in blocked

    def test_blocked_by_nonexistent_task_rejected(self, tmp_path):
        """blocked_by referencing a non-existent task is rejected."""
        project, contract = _make_contract(tmp_path, [])
        r = _run_task([
            "create", "--project", str(project),
            "--id", "feat.child", "--title", "Child",
            "--owner", "claude-code",
            "--blocked-by", "feat.ghost",
        ])
        assert r.returncode != 0
        assert "not found" in r.stderr.lower()


# ---------------------------------------------------------------------------
# Delegate — blocked_by gate
# ---------------------------------------------------------------------------

class TestDelegateBlockedByGate:
    def test_delegate_blocked_by_not_done_refused(self, tmp_path):
        """delegate refuses when blocked_by task is not done."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.dep", "title": "Dep", "owner": "claude-code",
             "status": "in_progress", "project_path": "__project__"},
            {"id": "feat.child", "title": "Child", "owner": "claude-code",
             "status": "plan_approved", "project_path": "__project__",
             "blocked_by": "feat.dep"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.child",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode != 0
        assert "blocked" in r.stderr.lower()

    def test_delegate_blocked_by_done_allowed(self, tmp_path):
        """delegate proceeds when blocked_by task is done."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.dep", "title": "Dep", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
            {"id": "feat.child", "title": "Child", "owner": "claude-code",
             "status": "plan_approved", "project_path": "__project__",
             "blocked_by": "feat.dep"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.child",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode == 0, r.stderr

    def test_delegate_blocked_by_none_allowed(self, tmp_path):
        """delegate proceeds when blocked_by is 'none'."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.x", "title": "X", "owner": "claude-code",
             "status": "plan_approved", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.x",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode == 0, r.stderr

    def test_delegate_blocked_by_list_all_done_allowed(self, tmp_path):
        """delegate proceeds when all tasks in blocked_by list are done."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.a", "title": "A", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
            {"id": "feat.b", "title": "B", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
            {"id": "feat.child", "title": "Child", "owner": "claude-code",
             "status": "plan_approved", "project_path": "__project__",
             "blocked_by": ["feat.a", "feat.b"]},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.child",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode == 0, r.stderr

    def test_delegate_blocked_by_list_one_not_done_refused(self, tmp_path):
        """delegate refuses when any task in blocked_by list is not done."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.a", "title": "A", "owner": "claude-code",
             "status": "done", "project_path": "__project__"},
            {"id": "feat.b", "title": "B", "owner": "claude-code",
             "status": "todo", "project_path": "__project__"},
            {"id": "feat.child", "title": "Child", "owner": "claude-code",
             "status": "plan_approved", "project_path": "__project__",
             "blocked_by": ["feat.a", "feat.b"]},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.child",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode != 0
        assert "blocked" in r.stderr.lower()


# ---------------------------------------------------------------------------
# Delegate — status lifecycle gate
# ---------------------------------------------------------------------------

class TestDelegateStatusGate:
    def test_delegate_status_todo_refused(self, tmp_path):
        """delegate refuses when task status is todo (must reach plan_approved first)."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.x", "title": "X", "owner": "claude-code",
             "status": "todo", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.x",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode != 0
        assert "plan" in r.stderr.lower() or "approve" in r.stderr.lower()

    def test_delegate_status_plan_proposed_refused(self, tmp_path):
        """delegate refuses when task status is plan_proposed."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.x", "title": "X", "owner": "claude-code",
             "status": "plan_proposed", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.x",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode != 0

    def test_delegate_status_plan_approved_allowed(self, tmp_path):
        """delegate proceeds when task status is plan_approved."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.x", "title": "X", "owner": "claude-code",
             "status": "plan_approved", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.x",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode == 0, r.stderr

    def test_delegate_status_in_progress_allowed(self, tmp_path):
        """delegate proceeds when task is already in_progress (resume)."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.x", "title": "X", "owner": "claude-code",
             "status": "in_progress", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.x",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode == 0, r.stderr

    def test_delegate_status_review_requested_refused_without_review_flag(self, tmp_path):
        """review_requested must not bypass the normal implementation gate by default."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.review", "title": "Review", "owner": "claude-code",
             "status": "review_requested", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.review",
            "--to", "claude-code", "--print-only",
        ])
        assert r.returncode != 0
        assert "plan" in r.stderr.lower() or "approve" in r.stderr.lower()

    def test_delegate_status_review_requested_allowed_for_review(self, tmp_path):
        """review_requested may dispatch only when explicitly marked as review workflow."""
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.review", "title": "Review", "owner": "claude-code",
             "status": "review_requested", "project_path": "__project__",
             "blocked_by": "none"},
        ])
        r = _run_delegate([
            "--project", str(project), "--task", "feat.review",
            "--to", "claude-code", "--print-only", "--for-review",
        ])
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# Close — status lifecycle gate
# ---------------------------------------------------------------------------

class TestCloseStatusGate:
    def _make_verified(self, tmp_path: Path, status: str) -> tuple[Path, Path]:
        project, contract = _make_contract(tmp_path, [
            {"id": "feat.x", "title": "X", "owner": "claude-code",
             "status": status, "project_path": "__project__",
             "verified": True},
        ])
        return project, contract

    def test_close_status_todo_refused(self, tmp_path):
        """close refuses when task status is todo."""
        project, contract = self._make_verified(tmp_path, "todo")
        r = _run_close([
            "--project", str(project), "--id", "feat.x",
            "--actor", "owner", "--summary", "done",
        ])
        assert r.returncode != 0
        assert "report" in r.stderr.lower() or "status" in r.stderr.lower()

    def test_close_status_in_progress_refused(self, tmp_path):
        """close refuses when task is still in_progress."""
        project, contract = self._make_verified(tmp_path, "in_progress")
        r = _run_close([
            "--project", str(project), "--id", "feat.x",
            "--actor", "owner", "--summary", "done",
        ])
        assert r.returncode != 0

    def test_close_status_report_ready_allowed(self, tmp_path):
        """close succeeds when task is report_ready and verified."""
        project, contract = self._make_verified(tmp_path, "report_ready")
        r = _run_close([
            "--project", str(project), "--id", "feat.x",
            "--actor", "owner", "--summary", "done",
        ])
        assert r.returncode == 0, r.stderr

    def test_close_status_review_passed_allowed(self, tmp_path):
        """close succeeds when task is review_passed and verified."""
        project, contract = self._make_verified(tmp_path, "review_passed")
        r = _run_close([
            "--project", str(project), "--id", "feat.x",
            "--actor", "owner", "--summary", "done",
        ])
        assert r.returncode == 0, r.stderr

    def test_close_force_flag_skips_status_gate(self, tmp_path):
        """--force bypasses status gate for emergency closes."""
        project, contract = self._make_verified(tmp_path, "in_progress")
        r = _run_close([
            "--project", str(project), "--id", "feat.x",
            "--actor", "owner", "--summary", "done", "--force",
        ])
        assert r.returncode == 0, r.stderr
