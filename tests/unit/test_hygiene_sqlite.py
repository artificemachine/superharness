"""
Tests for shux hygiene (validate.py) in SQLite-only environment.
Verifies that hygiene passes without contract.yaml or inbox.yaml.
"""
from __future__ import annotations

import os
from pathlib import Path
from tests.helpers import run_cmd, seed_sqlite_from_yaml

def _write_project_sqlite_only(tmp_path: Path, *, tasks: list[dict] = None) -> Path:
    project = tmp_path / "sqlite_proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    # No contract.yaml!
    (harness / "ledger.md").write_text("# Ledger\n")
    
    # We must seed SQLite directly or via a mock contract then delete it
    if tasks:
        (harness / "contract.yaml").write_text(
            f"id: test\ntasks:\n" + "".join(f"  - id: {t['id']}\n    status: {t['status']}\n    owner: {t.get('owner', 'claude-code')}\n" for t in tasks)
        )
        seed_sqlite_from_yaml(project)
        (harness / "contract.yaml").unlink()
    
    return project

def test_hygiene_passes_without_contract_yaml(tmp_path, repo_root):
    """shux hygiene should pass if SQLite has tasks but contract.yaml is missing."""
    project = _write_project_sqlite_only(tmp_path, tasks=[{"id": "t1", "status": "todo"}])
    
    import sys
    r = run_cmd(
        [sys.executable, "-m", "superharness.engine.validate", "--project", str(project)],
        cwd=repo_root,
    )
    assert r.returncode == 0
    assert "Contract hygiene check passed" in r.stdout

def test_hygiene_detects_missing_handoff_via_sqlite(tmp_path, repo_root):
    """shux hygiene should detect missing handoff for a done task stored in SQLite."""
    project = _write_project_sqlite_only(tmp_path, tasks=[{"id": "done-task", "status": "done"}])
    
    import sys
    r = run_cmd(
        [sys.executable, "-m", "superharness.engine.validate", "--project", str(project)],
        cwd=repo_root,
    )
    # Should fail because of missing handoff
    assert r.returncode == 1
    assert "Missing handoff file for done task: done-task" in r.stdout

def test_inbox_dispatch_ready_uses_sqlite(tmp_path):
    """engine.inbox._task_is_dispatch_ready should use SQLite when contract.yaml is missing."""
    project = _write_project_sqlite_only(tmp_path, tasks=[{"id": "ready-task", "status": "plan_approved"}])
    
    from superharness.engine.inbox import _task_is_dispatch_ready
    assert _task_is_dispatch_ready(str(project), "ready-task") is True
    assert _task_is_dispatch_ready(str(project), "nonexistent") is False
