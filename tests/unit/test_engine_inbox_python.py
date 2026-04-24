"""Python-native tests for superharness.engine.inbox (no Ruby subprocess)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PYTHON = sys.executable

INBOX_HEADER = (
    "# Delegation inbox\n"
    "# status: pending|launched|running|done|failed|stale\n"
)


def _inbox_file(tmp_path: Path, items_yaml: str = "") -> Path:
    f = tmp_path / "inbox.yaml"
    f.write_text(INBOX_HEADER + items_yaml)
    return f


def _run_inbox(cmd: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.engine.inbox", cmd] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def test_enqueue_creates_pending_item(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "q1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 0
    assert "result=enqueued" in r.stdout
    assert "priority=1" in r.stdout


def test_enqueue_duplicate_id_rejected(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "dup1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "dup1", "--to", "codex-cli",
        "--task", "t2", "--project", "/p", "--priority", "2",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 2
    assert "duplicate_id" in r.stdout


def test_enqueue_duplicate_task_rejected_when_pending(tmp_path: Path) -> None:
    """Second enqueue for the same task is blocked while the first is pending."""
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "first-id", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "second-id", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:01Z",
    ])
    assert r.returncode == 2
    assert "duplicate_task" in r.stdout
    assert "my-task" in r.stdout


def test_enqueue_duplicate_task_rejected_when_launched(tmp_path: Path) -> None:
    """Second enqueue is also blocked when the first item is already launched."""
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "first-id", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    # Advance to launched
    _run_inbox("launch", ["--file", str(f), "--id", "first-id", "--now", "2026-01-01T00:00:05Z"])
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "second-id", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:06Z",
    ])
    assert r.returncode == 2
    assert "duplicate_task" in r.stdout


def test_enqueue_same_discussion_round_different_agent_allowed(tmp_path: Path) -> None:
    """Discussion round tasks (`.../round-N`) allow one entry per participant.

    Non-round tasks are covered by
    tests/integration/test_multi_agent_support.py::test_prevent_duplicate_task_different_agents,
    which asserts the opposite (strict single-agent ownership).
    """
    f = _inbox_file(tmp_path)
    task_id = "disc-42/round-1"
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "first-id", "--to", "claude-code",
        "--task", task_id, "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "second-id", "--to", "codex-cli",
        "--task", task_id, "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:01Z",
    ])
    assert r.returncode == 0
    assert "result=enqueued" in r.stdout


def test_enqueue_same_task_allowed_after_done(tmp_path: Path) -> None:
    """Same task can be re-enqueued once the previous item is done."""
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "first-id", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    # Mark it done via set_status
    _run_inbox("set_status", [
        "--file", str(f), "--id", "first-id",
        "--from", "pending", "--to", "done",
        "--now", "2026-01-01T01:00:00Z", "--stamp-key", "done_at",
    ])
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "second-id", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T02:00:00Z",
    ])
    assert r.returncode == 0
    assert "result=enqueued" in r.stdout


def test_enqueue_normalizes_priority(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox("enqueue", [
        "--file", str(f), "--id", "q2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "99",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 0
    assert "priority=2" in r.stdout


def test_next_pending_returns_highest_priority(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "low", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "3",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "high", "--to", "claude-code",
        "--task", "t2", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("next_pending", ["--file", str(f)])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["id"] == "high"
    assert data["priority"] == 1


def test_next_pending_filters_by_target(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "cc1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "cx1", "--to", "codex-cli",
        "--task", "t2", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("next_pending", ["--file", str(f), "--to", "codex-cli"])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["id"] == "cx1"


def test_next_pending_empty_inbox(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox("next_pending", ["--file", str(f)])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_launch_transitions_to_launched(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "l1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("launch", ["--file", str(f), "--id", "l1", "--now", "2026-01-01T00:01:00Z"])
    assert r.returncode == 0
    assert "result=launched" in r.stdout


def test_launch_not_found(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox("launch", ["--file", str(f), "--id", "missing", "--now", "2026-01-01T00:00:00Z"])
    assert r.returncode == 2
    assert "not_found" in r.stdout


def test_launch_status_mismatch(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "sm1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("launch", ["--file", str(f), "--id", "sm1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox("launch", ["--file", str(f), "--id", "sm1", "--now", "2026-01-01T00:02:00Z"])
    assert r.returncode == 3
    assert "status_mismatch" in r.stdout


def test_launch_retry_exhausted(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "rx1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
        "--retry-count", "3", "--max-retries", "3",
    ])
    r = _run_inbox("launch", ["--file", str(f), "--id", "rx1", "--now", "2026-01-01T00:01:00Z"])
    assert r.returncode == 4
    assert "retry_exhausted" in r.stdout


def test_set_status_transitions(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "ss1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("set_status", [
        "--file", str(f), "--id", "ss1",
        "--from", "pending", "--to", "done",
        "--now", "2026-01-01T00:05:00Z",
        "--stamp-key", "done_at",
    ])
    assert r.returncode == 0


def test_set_status_wrong_from(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "ss2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("set_status", [
        "--file", str(f), "--id", "ss2",
        "--from", "launched", "--to", "done",
        "--now", "2026-01-01T00:05:00Z",
    ])
    assert r.returncode == 3


def test_remove_item_deletes_row(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "rm1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("remove", ["--file", str(f), "--id", "rm1"])
    assert r.returncode == 0
    assert "result=removed id=rm1" in r.stdout
    after = f.read_text()
    assert "rm1" not in after


def test_remove_item_not_found(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox("remove", ["--file", str(f), "--id", "missing"])
    assert r.returncode == 2
    assert "result=not_found id=missing" in r.stdout


def test_recover_launched_marks_stale(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "rc1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("launch", ["--file", str(f), "--id", "rc1", "--now", "2026-01-01T00:00:00Z"])
    r = _run_inbox("recover_launched", [
        "--file", str(f),
        "--now", "2026-01-01T01:00:00Z",
        "--timeout-minutes", "20",
        "--action", "stale",
    ])
    assert r.returncode == 0
    assert "stale=1" in r.stdout


def test_recover_launched_retries(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "rc2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("launch", ["--file", str(f), "--id", "rc2", "--now", "2026-01-01T00:00:00Z"])
    r = _run_inbox("recover_launched", [
        "--file", str(f),
        "--now", "2026-01-01T01:00:00Z",
        "--timeout-minutes", "20",
        "--action", "retry",
    ])
    assert r.returncode == 0
    assert "retried=1" in r.stdout


def test_list_launched(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "ll1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("launch", ["--file", str(f), "--id", "ll1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox("list_launched", ["--file", str(f)])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data) == 1
    assert data[0]["id"] == "ll1"


def test_deadline_fail(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "df1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("launch", ["--file", str(f), "--id", "df1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox("deadline_fail", [
        "--file", str(f), "--id", "df1", "--now", "2026-01-01T01:00:00Z",
        "--reason", "deadline_exceeded",
    ])
    assert r.returncode == 0
    assert "result=ok" in r.stdout


def test_deadline_fail_wrong_status(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "df2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("deadline_fail", [
        "--file", str(f), "--id", "df2", "--now", "2026-01-01T01:00:00Z",
    ])
    assert r.returncode == 3
    assert "status_mismatch" in r.stdout


def test_normalize_drops_stale(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "n1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("set_status", [
        "--file", str(f), "--id", "n1",
        "--from", "pending", "--to", "stale",
        "--now", "2026-01-01T00:05:00Z",
    ])
    r = _run_inbox("normalize", ["--file", str(f), "--drop-status", "stale"])
    assert r.returncode == 0
    r2 = _run_inbox("next_pending", ["--file", str(f)])
    assert r2.stdout.strip() == ""


def test_set_field(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "sf1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox("set_field", [
        "--file", str(f), "--id", "sf1",
        "--key", "notes", "--value", "hello",
    ])
    assert r.returncode == 0


def test_sync_task_status_closes_launched_items(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox("enqueue", [
        "--file", str(f), "--id", "sync1", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox("launch", ["--file", str(f), "--id", "sync1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox("sync_task_status", [
        "--file", str(f), "--task", "my-task", "--to", "done",
        "--now", "2026-01-01T00:10:00Z",
    ])
    assert r.returncode == 0
    assert "synced=1" in r.stdout
    r2 = _run_inbox("list_launched", ["--file", str(f)])
    data = json.loads(r2.stdout)
    assert len(data) == 0


def test_sync_task_status_no_match(tmp_path: Path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox("sync_task_status", [
        "--file", str(f), "--task", "nonexistent", "--to", "done",
        "--now", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 0
    assert "synced=0" in r.stdout
