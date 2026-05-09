from __future__ import annotations

from tests.helpers import run_bash, seed_sqlite_from_yaml
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _make_project(tmp_path, task_id: str, owner: str, deadline_minutes: int | None, launched_at: str):
    project = tmp_path / f"proj-deadline-{task_id}"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "handoffs").mkdir()
    (harness / "failures.yaml").write_text("failures: []\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")

    deadline_line = f"    deadline_minutes: {deadline_minutes}\n" if deadline_minutes is not None else ""
    (harness / "contract.yaml").write_text(
        f"id: test-contract\n"
        f"tasks:\n"
        f"  - id: {task_id}\n"
        f"    title: Test task\n"
        f"    status: in_progress\n"
        f"    owner: {owner}\n"
        f"{deadline_line}"
        f"    project_path: \"{project}\"\n"
        f"decisions: []\n"
        f"failures: []\n"
    )

    (harness / "inbox.yaml").write_text(
        f"# Delegation inbox\n"
        f"# status: pending|launched|running|done|failed|stale\n"
        f"---\n"
        f"- id: inbox-{task_id}\n"
        f"  to: {owner}\n"
        f"  task: {task_id}\n"
        f"  project: \"{project}\"\n"
        f"  status: launched\n"
        f"  launched_at: {launched_at}\n"
        f"  priority: 1\n"
        f"  retry_count: 1\n"
        f"  max_retries: 3\n"
    )

    (harness / "ledger.md").write_text("# Ledger\n\nAppend-only.\n")
    seed_sqlite_from_yaml(project)
    return project


def test_deadline_exceeded_marks_failed_and_reenqueues(repo_root, tmp_path) -> None:
    project = _make_project(
        tmp_path,
        task_id="slow-task",
        owner="claude-code",
        deadline_minutes=1,
        launched_at="2026-01-01T00:00:00Z",   # far in the past
    )

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=1" in result.stdout

    # Inbox is SQLite-backed post-migration; inbox.yaml is no longer
    # the source of truth. Query SQLite for the status checks.
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    rows = db.execute(
        "SELECT id, target_agent, status, failed_reason FROM inbox "
        "WHERE task_id LIKE '%slow-task%' ORDER BY created_at"
    ).fetchall()
    db.close()
    statuses = {r[2] for r in rows}
    targets = {r[1] for r in rows}
    reasons = {(r[3] or "") for r in rows}
    assert "failed" in statuses, f"Expected a failed row, got {rows}"
    assert any("deadline_exceeded" in r for r in reasons)
    assert "codex-cli" in targets
    assert "pending" in statuses

    ledger_text = (project / ".superharness" / "ledger.md").read_text()
    assert "deadline-exceeded" in ledger_text
    assert "slow-task" in ledger_text
    assert "codex-cli" in ledger_text

    handoff_files = list((project / ".superharness" / "handoffs").glob("*deadline-slow-task.yaml"))
    assert len(handoff_files) == 1
    handoff_text = handoff_files[0].read_text()
    assert "deadline_exceeded" in handoff_text
    assert "claude-code" in handoff_text
    assert "codex-cli" in handoff_text

    # Verify SQLite tasks row reflects the deadline failure (post-migration
    # contract.yaml is no longer the source of truth).
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    task_row = db.execute(
        "SELECT status, failed_reason, stopped_at FROM tasks WHERE id='slow-task'"
    ).fetchone()
    db.close()
    assert task_row is not None
    assert task_row[0] == "failed"


def test_deadline_not_exceeded_does_nothing(repo_root, tmp_path) -> None:
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    project = _make_project(
        tmp_path,
        task_id="fast-task",
        owner="codex-cli",
        deadline_minutes=60,
        launched_at=now_utc,   # just launched
    )

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=0" in result.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: launched" in inbox_text   # unchanged


def test_no_deadline_set_does_nothing(repo_root, tmp_path) -> None:
    project = _make_project(
        tmp_path,
        task_id="nodeadline-task",
        owner="claude-code",
        deadline_minutes=None,
        launched_at="2026-01-01T00:00:00Z",
    )

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=0" in result.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: launched" in inbox_text   # unchanged


def test_deadline_reassigns_codex_to_claude(repo_root, tmp_path) -> None:
    project = _make_project(
        tmp_path,
        task_id="codex-slow",
        owner="codex-cli",
        deadline_minutes=1,
        launched_at="2026-01-01T00:00:00Z",
    )

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=1" in result.stdout

    # Inbox is SQLite-backed post-migration; query the DB.
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    rows = db.execute(
        "SELECT target_agent, status FROM inbox WHERE task_id LIKE '%codex-slow%'"
    ).fetchall()
    db.close()
    targets = {r[0] for r in rows}
    statuses = {r[1] for r in rows}
    assert "claude-code" in targets
    assert "pending" in statuses


def test_missing_inbox_exits_cleanly(repo_root, tmp_path) -> None:
    project = tmp_path / "empty-proj"
    project.mkdir()
    (project / ".superharness").mkdir()

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=0" in result.stdout
