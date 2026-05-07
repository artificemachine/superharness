"""Tests for MCP EventStream — Iteration 4."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from superharness.mcp.events import EventStream


def _make_events_file(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for i in range(n):
            f.write(json.dumps({"type": "tick", "seq": i}) + "\n")


def test_get_events_returns_last_n(tmp_path):
    events_file = tmp_path / ".superharness" / "events.jsonl"
    _make_events_file(events_file, 20)
    es = EventStream()
    events = es.get_events(str(tmp_path), n=5)
    assert len(events) == 5
    assert events[-1]["seq"] == 19


def test_get_events_empty_file(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    es = EventStream()
    events = es.get_events(str(tmp_path), n=10)
    assert events == []


def test_get_events_no_file(tmp_path):
    (tmp_path / ".superharness").mkdir()
    es = EventStream()
    events = es.get_events(str(tmp_path), n=10)
    assert events == []


def test_append_event_writes_jsonl_line(tmp_path):
    (tmp_path / ".superharness").mkdir()
    es = EventStream()
    es.append_event(str(tmp_path), {"type": "task:delegated", "task_id": "t1"})
    events_file = tmp_path / ".superharness" / "events.jsonl"
    assert events_file.exists()
    lines = events_file.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["type"] == "task:delegated"
    assert data["task_id"] == "t1"


def test_append_event_creates_file_if_missing(tmp_path):
    (tmp_path / ".superharness").mkdir()
    es = EventStream()
    es.append_event(str(tmp_path), {"type": "test"})
    assert (tmp_path / ".superharness" / "events.jsonl").exists()


def test_event_stream_project_scoped(tmp_path):
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    for p in (proj_a, proj_b):
        (p / ".superharness").mkdir(parents=True)
    es = EventStream()
    es.append_event(str(proj_a), {"type": "a-event"})
    events_b = es.get_events(str(proj_b), n=10)
    assert events_b == []


def test_append_event_adds_timestamp(tmp_path):
    (tmp_path / ".superharness").mkdir()
    es = EventStream()
    es.append_event(str(tmp_path), {"type": "tick"})
    lines = (tmp_path / ".superharness" / "events.jsonl").read_text().strip().splitlines()
    data = json.loads(lines[0])
    assert "ts" in data or "created_at" in data or "timestamp" in data
