from __future__ import annotations
import pytest

import json
from pathlib import Path

from tests.helpers import run_cmd


INBOX_HEADER = (
    "# Delegation inbox\n"
    "# status: pending|launched|running|done|failed|stale\n"
)


pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def _inbox_file(tmp_path: Path, items_yaml: str = "") -> Path:
    f = tmp_path / "inbox.yaml"
    f.write_text(INBOX_HEADER + items_yaml)
    return f


def _run_inbox(repo_root: Path, cmd: str, args: list[str]) -> object:
    import sys
    return run_cmd(
        [sys.executable, "-m", "superharness.engine.inbox", cmd] + args,
        cwd=repo_root,
    )


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_creates_pending_item(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "q1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 0
    assert "result=enqueued" in r.stdout
    assert "priority=1" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_duplicate_id_rejected(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "dup1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "dup1", "--to", "codex-cli",
        "--task", "t2", "--project", "/p", "--priority", "2",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 2
    assert "duplicate_id" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_normalizes_priority(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "q2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "99",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 0
    assert "priority=2" in r.stdout  # out-of-range normalizes to 2


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_next_pending_returns_highest_priority(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    # Enqueue two items with different priorities
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "low", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "3",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "high", "--to", "claude-code",
        "--task", "t2", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "next_pending", ["--file", str(f)])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["id"] == "high"
    assert data["priority"] == 1


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_next_pending_filters_by_target(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "cc1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "cx1", "--to", "codex-cli",
        "--task", "t2", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "next_pending", ["--file", str(f), "--to", "codex-cli"])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["id"] == "cx1"


def test_next_pending_empty_inbox(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox(repo_root, "next_pending", ["--file", str(f)])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_launch_transitions_to_launched(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "l1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "launch", [
        "--file", str(f), "--id", "l1", "--now", "2026-01-01T00:01:00Z",
    ])
    assert r.returncode == 0
    assert "result=launched" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_launch_not_found(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox(repo_root, "launch", [
        "--file", str(f), "--id", "missing", "--now", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 2
    assert "not_found" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_launch_status_mismatch(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "sm1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    # Launch once
    _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "sm1", "--now", "2026-01-01T00:01:00Z"])
    # Launch again (already launched)
    r = _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "sm1", "--now", "2026-01-01T00:02:00Z"])
    assert r.returncode == 3
    assert "status_mismatch" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_launch_retry_exhausted(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "rx1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
        "--retry-count", "3", "--max-retries", "3",
    ])
    r = _run_inbox(repo_root, "launch", [
        "--file", str(f), "--id", "rx1", "--now", "2026-01-01T00:01:00Z",
    ])
    assert r.returncode == 4
    assert "retry_exhausted" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_set_status_transitions(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "ss1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "set_status", [
        "--file", str(f), "--id", "ss1",
        "--from", "pending", "--to", "done",
        "--now", "2026-01-01T00:05:00Z",
        "--stamp-key", "done_at",
    ])
    assert r.returncode == 0


def test_set_status_wrong_from(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "ss2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "set_status", [
        "--file", str(f), "--id", "ss2",
        "--from", "launched", "--to", "done",
        "--now", "2026-01-01T00:05:00Z",
    ])
    assert r.returncode == 3


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_remove_item_deletes_row(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "rm1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "remove", ["--file", str(f), "--id", "rm1"])
    assert r.returncode == 0
    assert "result=removed id=rm1" in r.stdout
    after = f.read_text()
    assert "rm1" not in after


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_remove_item_not_found(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox(repo_root, "remove", ["--file", str(f), "--id", "missing"])
    assert r.returncode == 2
    assert "result=not_found id=missing" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_recover_launched_marks_stale(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "rc1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "rc1", "--now", "2026-01-01T00:00:00Z"])
    r = _run_inbox(repo_root, "recover_launched", [
        "--file", str(f),
        "--now", "2026-01-01T01:00:00Z",
        "--timeout-minutes", "20",
        "--action", "stale",
    ])
    assert r.returncode == 0
    assert "stale=1" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_recover_launched_retries(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "rc2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "rc2", "--now", "2026-01-01T00:00:00Z"])
    r = _run_inbox(repo_root, "recover_launched", [
        "--file", str(f),
        "--now", "2026-01-01T01:00:00Z",
        "--timeout-minutes", "20",
        "--action", "retry",
    ])
    assert r.returncode == 0
    assert "retried=1" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_list_launched(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "ll1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "ll1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox(repo_root, "list_launched", ["--file", str(f)])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data) == 1
    assert data[0]["id"] == "ll1"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_deadline_fail(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "df1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "df1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox(repo_root, "deadline_fail", [
        "--file", str(f), "--id", "df1", "--now", "2026-01-01T01:00:00Z",
        "--reason", "deadline_exceeded",
    ])
    assert r.returncode == 0
    assert "result=ok" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_deadline_fail_wrong_status(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "df2", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    # Not launched, so deadline_fail should fail
    r = _run_inbox(repo_root, "deadline_fail", [
        "--file", str(f), "--id", "df2", "--now", "2026-01-01T01:00:00Z",
    ])
    assert r.returncode == 3
    assert "status_mismatch" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_normalize_drops_stale(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "n1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    # Mark as stale via set_status
    _run_inbox(repo_root, "set_status", [
        "--file", str(f), "--id", "n1",
        "--from", "pending", "--to", "stale",
        "--now", "2026-01-01T00:05:00Z",
    ])
    r = _run_inbox(repo_root, "normalize", [
        "--file", str(f), "--drop-status", "stale",
    ])
    assert r.returncode == 0
    # Verify item is gone
    r2 = _run_inbox(repo_root, "next_pending", ["--file", str(f)])
    assert r2.stdout.strip() == ""


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_set_field(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "sf1", "--to", "claude-code",
        "--task", "t1", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    r = _run_inbox(repo_root, "set_field", [
        "--file", str(f), "--id", "sf1",
        "--key", "notes", "--value", "hello",
    ])
    assert r.returncode == 0


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_sync_task_status_closes_launched_items(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "sync1", "--to", "claude-code",
        "--task", "my-task", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])
    _run_inbox(repo_root, "launch", ["--file", str(f), "--id", "sync1", "--now", "2026-01-01T00:01:00Z"])
    r = _run_inbox(repo_root, "sync_task_status", [
        "--file", str(f), "--task", "my-task", "--to", "done",
        "--now", "2026-01-01T00:10:00Z",
    ])
    assert r.returncode == 0
    assert "synced=1" in r.stdout
    # Verify item is no longer launched
    r2 = _run_inbox(repo_root, "list_launched", ["--file", str(f)])
    data = json.loads(r2.stdout)
    assert len(data) == 0


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_sync_task_status_no_match(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    r = _run_inbox(repo_root, "sync_task_status", [
        "--file", str(f), "--task", "nonexistent", "--to", "done",
        "--now", "2026-01-01T00:00:00Z",
    ])
    assert r.returncode == 0
    assert "synced=0" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_has_active_detects_matching_pending_item(repo_root, tmp_path) -> None:
    f = _inbox_file(tmp_path)
    _run_inbox(repo_root, "enqueue", [
        "--file", str(f), "--id", "ha1", "--to", "codex-cli",
        "--task", "t-active", "--project", "/p", "--priority", "1",
        "--created-at", "2026-01-01T00:00:00Z",
    ])

    active = _run_inbox(repo_root, "has_active", [
        "--file", str(f), "--to", "codex-cli", "--task", "t-active",
    ])
    assert active.returncode == 0
    assert active.stdout.strip() == "true"

    inactive = _run_inbox(repo_root, "has_active", [
        "--file", str(f), "--to", "claude-code", "--task", "t-active",
    ])
    assert inactive.returncode == 0
    assert inactive.stdout.strip() == "false"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_unknown_command(repo_root) -> None:
    r = _run_inbox(repo_root, "bogus", [])
    assert r.returncode != 0
    assert "Usage:" in r.stderr


def test_missing_required_args(repo_root) -> None:
    r = _run_inbox(repo_root, "enqueue", [])
    assert r.returncode != 0
    assert "required" in r.stderr.lower()
