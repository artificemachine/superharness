from __future__ import annotations

from tests.helpers import run_bash


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
    return project


def test_deadline_exceeded_marks_failed_and_reenqueues(repo_root, tmp_path) -> None:
    project = _make_project(
        tmp_path,
        task_id="slow-task",
        owner="claude-code",
        deadline_minutes=1,
        launched_at="2026-01-01T00:00:00Z",   # far in the past
    )

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=1" in result.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    # Original item must be failed.
    assert "status: failed" in inbox_text
    assert "deadline_exceeded" in inbox_text
    # Re-enqueued item for other owner must be pending.
    assert "to: codex-cli" in inbox_text
    assert "status: pending" in inbox_text

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

    # Verify contract task is marked as failed with reason.
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: failed" in contract_text
    assert "stopped_reason: deadline_exceeded_after_" in contract_text


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

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
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

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
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

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=1" in result.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "to: claude-code" in inbox_text
    assert "status: pending" in inbox_text


def test_missing_inbox_exits_cleanly(repo_root, tmp_path) -> None:
    project = tmp_path / "empty-proj"
    project.mkdir()
    (project / ".superharness").mkdir()

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "exceeded=0" in result.stdout
