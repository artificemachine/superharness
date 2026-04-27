"""Tests for the /api/recent-failures endpoint shape — iter 8 of auto-mode-gap-plan.

Verifies the data contract that the dashboard panel consumes. Doesn't spin up
the HTTP server; tests the data assembly logic against an in-tmp inbox.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _build_failures_payload(project_dir: Path, limit: int = 10) -> dict:
    """Reproduce the /api/recent-failures payload assembly for unit testing.

    This mirrors the inline logic in dashboard-ui.py. Keeping it duplicated for
    test isolation; if the contract changes we update both.
    """
    harness = project_dir / ".superharness"
    inbox_file = harness / "inbox.yaml"
    launcher_logs = harness / "launcher-logs"
    failures: list[dict] = []
    items = yaml.safe_load(inbox_file.read_text()) or [] if inbox_file.exists() else []
    failed = [i for i in items if isinstance(i, dict) and i.get("status") == "failed"]
    failed.sort(key=lambda i: str(i.get("failed_at") or ""), reverse=True)
    for item in failed[:limit]:
        log_tail = ""
        task_id = str(item.get("task") or item.get("task_id") or "")
        target = str(item.get("to") or item.get("target_agent") or "")
        if task_id and launcher_logs.is_dir():
            safe_task = task_id.replace("/", "-")
            candidates = sorted(
                launcher_logs.glob(f"{safe_task}-{target}-*.log"),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            if candidates:
                try:
                    lines = candidates[0].read_text(encoding="utf-8", errors="replace").splitlines()
                    log_tail = "\n".join(lines[-20:])
                except Exception:
                    pass
        failures.append({
            "id": str(item.get("id", "")),
            "task": task_id,
            "to": target,
            "failed_at": str(item.get("failed_at") or ""),
            "failure_class": str(item.get("failure_class") or "unknown"),
            "failure_explain": str(item.get("failure_explain") or item.get("failed_reason") or ""),
            "retry_count": int(item.get("retry_count", 0) or 0),
            "max_retries": int(item.get("max_retries", 3) or 3),
            "log_tail": log_tail,
        })
    return {"failures": failures}


def test_no_failures_returns_empty_list(clean_harness: Path) -> None:
    payload = _build_failures_payload(clean_harness)
    assert payload == {"failures": []}


def test_failed_item_appears_with_classification(clean_harness: Path) -> None:
    inbox = clean_harness / ".superharness" / "inbox.yaml"
    inbox.write_text(yaml.dump([{
        "id": "test-1", "task": "feat.foo", "to": "claude-code",
        "status": "failed", "failed_at": "2026-04-27T12:00:00Z",
        "failure_class": "permanent_block",
        "failure_explain": "bash unbound variable",
        "retry_count": 3, "max_retries": 3,
    }]))
    payload = _build_failures_payload(clean_harness)
    assert len(payload["failures"]) == 1
    f = payload["failures"][0]
    assert f["failure_class"] == "permanent_block"
    assert f["failure_explain"] == "bash unbound variable"
    assert f["retry_count"] == 3


def test_log_tail_is_attached_when_log_exists(clean_harness: Path) -> None:
    inbox = clean_harness / ".superharness" / "inbox.yaml"
    inbox.write_text(yaml.dump([{
        "id": "test-1", "task": "feat.foo", "to": "claude-code",
        "status": "failed", "failed_at": "2026-04-27T12:00:00Z",
    }]))
    logs = clean_harness / ".superharness" / "launcher-logs"
    logs.mkdir()
    log_path = logs / "feat.foo-claude-code-20260427T120000Z.log"
    log_path.write_text("\n".join([f"line {i}" for i in range(30)]))
    payload = _build_failures_payload(clean_harness)
    assert "line 29" in payload["failures"][0]["log_tail"]
    # Only last 20 lines
    assert "line 0" not in payload["failures"][0]["log_tail"]


def test_only_failed_items_included(clean_harness: Path) -> None:
    inbox = clean_harness / ".superharness" / "inbox.yaml"
    inbox.write_text(yaml.dump([
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "launched"},
        {"id": "c", "status": "failed", "failed_at": "2026-04-27T12:00:00Z"},
        {"id": "d", "status": "done"},
    ]))
    payload = _build_failures_payload(clean_harness)
    assert len(payload["failures"]) == 1
    assert payload["failures"][0]["id"] == "c"


def test_failures_sorted_newest_first(clean_harness: Path) -> None:
    inbox = clean_harness / ".superharness" / "inbox.yaml"
    inbox.write_text(yaml.dump([
        {"id": "old", "status": "failed", "failed_at": "2026-04-27T10:00:00Z"},
        {"id": "new", "status": "failed", "failed_at": "2026-04-27T12:00:00Z"},
        {"id": "mid", "status": "failed", "failed_at": "2026-04-27T11:00:00Z"},
    ]))
    payload = _build_failures_payload(clean_harness)
    ids = [f["id"] for f in payload["failures"]]
    assert ids == ["new", "mid", "old"]
