"""Tests for the on_verify lifecycle hook firing + hard security gate.

Wires `run_hooks("on_verify", ...)` into the verify command and enforces a
true gate: when a hook declares block_on and reports a blocking finding, a
requested `--result pass` is downgraded to "not verified" and the command
exits non-zero. This is the security module's `block_on: critical` contract,
which previously never fired (no command called run_hooks for on_verify).
"""
from __future__ import annotations

from pathlib import Path

import superharness.modules.runner as runner_mod
from superharness.commands import verify as verify_mod
from superharness.engine import tasks_dao
from superharness.engine.contract_io import _task_row_from_dict
from superharness.engine.db import get_connection, init_db, transaction


def _seed(project: Path, task_id: str = "feat-001") -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    task_dict = {
        "id": task_id,
        "title": "t",
        "owner": "claude-code",
        "status": "report_ready",
        "project_path": project.as_posix(),
    }
    conn = get_connection(str(project))
    init_db(conn)
    with transaction(conn):
        tasks_dao.upsert(
            conn, _task_row_from_dict(task_dict, str(project), "2026-01-01T00:00:00Z")
        )
    conn.commit()
    conn.close()


def _verified(project: Path, task_id: str = "feat-001") -> bool:
    conn = get_connection(str(project))
    init_db(conn)
    row = tasks_dao.get(conn, task_id)
    conn.close()
    return bool(row.verified)


def test_verify_fires_on_verify_hook_with_context(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed(project)

    calls = []
    monkeypatch.setattr(
        runner_mod, "run_hooks",
        lambda event, ctx, pdir: calls.append((event, ctx, pdir)) or [],
    )

    rc = verify_mod.verify(str(project), "feat-001", "manual", "pass", "claude-code")
    assert rc == 0
    on_verify = [c for c in calls if c[0] == "on_verify"]
    assert len(on_verify) == 1
    _, ctx, _ = on_verify[0]
    assert ctx["task_id"] == "feat-001"
    assert ctx["project_dir"] == str(project)
    assert ctx["result"] == "pass"
    assert ctx["actor"] == "claude-code"


def test_verify_pass_blocked_by_hook_records_not_verified(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed(project)

    monkeypatch.setattr(
        runner_mod, "run_hooks",
        lambda event, ctx, pdir: [
            {"module": "security", "event": "on_verify", "success": False,
             "blocked": True, "block_on": "critical",
             "message": "shipguard found critical issues"}
        ],
    )

    rc = verify_mod.verify(str(project), "feat-001", "manual", "pass", "claude-code")
    assert rc != 0, "a blocked pass must exit non-zero"
    assert _verified(project) is False, "blocked pass must not mark task verified"

    ledger = (project / ".superharness" / "ledger.md").read_text()
    assert "BLOCKED" in ledger
    assert "security" in ledger


def test_verify_pass_not_blocked_records_verified(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed(project)
    monkeypatch.setattr(runner_mod, "run_hooks", lambda event, ctx, pdir: [])

    rc = verify_mod.verify(str(project), "feat-001", "manual", "pass", "claude-code")
    assert rc == 0
    assert _verified(project) is True


def test_verify_hook_error_does_not_mask_verification(tmp_path, monkeypatch):
    """A crashing on_verify hook must not block a clean verification."""
    project = tmp_path / "proj"
    _seed(project)

    def _boom(event, ctx, pdir):
        raise RuntimeError("hook exploded")

    monkeypatch.setattr(runner_mod, "run_hooks", _boom)

    rc = verify_mod.verify(str(project), "feat-001", "manual", "pass", "claude-code")
    assert rc == 0
    assert _verified(project) is True
