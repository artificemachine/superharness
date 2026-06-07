"""E2E tests — full user workflows through the CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _shux(*args, cwd: str | None = None, timeout: int = 15) -> subprocess.CompletedProcess:
    cmd = ["shux"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def _init_project(tmp_path: Path) -> Path:
    project = tmp_path / "test-project"
    project.mkdir()
    r = _shux("init", "test-project", "python", "active", cwd=str(project))
    assert r.returncode == 0, f"init failed: {r.stderr[:200]}"
    return project


class TestTaskLifecycleE2E:
    def test_create_and_delegate_task(self, tmp_path):
        project = _init_project(tmp_path)
        r = _shux("task", "create", "--id", "e2e-1", "--title", "E2E test",
                  "--owner", "claude-code", "--criteria", "Works", cwd=str(project))
        assert r.returncode == 0, f"create: {r.stderr[:200]}"

        r = _shux("task", "status", "--id", "e2e-1", "--status", "plan_proposed",
                  "--actor", "claude-code", cwd=str(project))
        assert r.returncode == 0, f"plan_proposed: {r.stderr[:200]}"

        r = _shux("task", "status", "--id", "e2e-1", "--status", "plan_approved",
                  "--actor", "claude-code", cwd=str(project))
        assert r.returncode == 0, f"approve: {r.stderr[:200]}"

        r = _shux("delegate", "e2e-1", "--to", "claude-code", "--print-only",
                  "--non-interactive", cwd=str(project), timeout=15)
        assert r.returncode == 0, f"delegate: {r.stderr[:200]}"

    def test_doctor_reports_healthy(self, tmp_path):
        project = _init_project(tmp_path)
        r = _shux("doctor", cwd=str(project))
        assert r.returncode == 0


class TestStatusE2E:
    def test_status_runs(self, tmp_path):
        project = _init_project(tmp_path)
        r = _shux("status", cwd=str(project))
        assert r.returncode == 0

    def test_contract_lists_tasks(self, tmp_path):
        project = _init_project(tmp_path)
        _shux("task", "create", "--id", "e2e-c", "--title", "C", "--owner", "claude-code", cwd=str(project))
        r = _shux("contract", cwd=str(project))
        assert r.returncode == 0


class TestDiscussionE2E:
    def test_discuss_starts(self, tmp_path):
        project = _init_project(tmp_path)
        r = _shux("discuss", "start", "--topic", "E2E discussion",
                  "--owners", "claude-code,codex-cli", "--max-rounds", "1",
                  "--force", cwd=str(project))
        assert r.returncode == 0
