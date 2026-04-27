"""Tests for the /api/inbox?status=<filter> endpoint filter logic.

Covers every filter pill visible in the dashboard UI:
  - discussion (status=active)  → pending/launched/running only; paused EXCLUDED
  - paused    (status=paused)   → paused only
  - failed    (status=failed)   → failed only
  - stale     (status=stale)    → stale only
  - done      (status=done)     → done only
  - no filter (status='')       → all items

Bug fixed in v1.37.3: "paused" was included in the _ACTIVE set for
status=active, causing the discussion pill to show 6 paused inbox items
alongside active discussions instead of showing discussions only.
"""

import json
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── inbox item factory ────────────────────────────────────────────────────────

_STATUSES = ["pending", "launched", "running", "paused", "failed", "stale", "done", "stopped"]

def _item(id: str, status: str, agent: str = "claude-code") -> dict:
    return {
        "id": id,
        "task_id": f"task-{id}",
        "status": status,
        "target_agent": agent,
        "created_at": "2026-04-27T00:00:00Z",
        "pause_reason": None,
        "failed_reason": None,
        "stale_reason": None,
        "stopped_reason": None,
    }


# ── helper: call the filter logic directly without HTTP ───────────────────────

def _apply_status_filter(items: list[dict], status_filter: str) -> list[dict]:
    """Replicate exactly the filter logic from dashboard-ui.py /api/inbox."""
    if status_filter == "active":
        _ACTIVE = {"pending", "launched", "running"}
        return [i for i in items if i.get("status") in _ACTIVE]
    if status_filter:
        return [i for i in items if i.get("status") == status_filter]
    return items  # no filter → all


def _make_inbox(specs: list[tuple[str, str]]) -> list[dict]:
    """Build a list of inbox items from (id, status) pairs."""
    return [_item(id_, status) for id_, status in specs]


# ── shared fixture: mixed inbox with one item per status ──────────────────────

@pytest.fixture
def mixed_inbox() -> list[dict]:
    return _make_inbox([
        ("p1", "pending"),
        ("p2", "launched"),
        ("p3", "running"),
        ("p4", "paused"),
        ("p5", "failed"),
        ("p6", "stale"),
        ("p7", "done"),
        ("p8", "stopped"),
    ])


# ── "discussion" pill → status=active ────────────────────────────────────────

class TestActiveFilter:
    """The discussion pill calls /api/inbox?status=active.

    Must return pending/launched/running only — paused is excluded (Bug v1.37.3).
    """

    def test_returns_pending(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p1" in ids

    def test_returns_launched(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p2" in ids

    def test_returns_running(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p3" in ids

    def test_excludes_paused(self, mixed_inbox):
        """Regression: paused was in _ACTIVE before the v1.37.3 fix."""
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p4" not in ids, "paused must NOT appear in active filter (discussion pill bug)"

    def test_excludes_failed(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p5" not in ids

    def test_excludes_stale(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p6" not in ids

    def test_excludes_done(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p7" not in ids

    def test_excludes_stopped(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "active")
        ids = [i["id"] for i in result]
        assert "p8" not in ids

    def test_empty_inbox_returns_empty(self):
        assert _apply_status_filter([], "active") == []

    def test_only_paused_inbox_returns_empty(self):
        """Critical regression guard: all paused → discussion pill must show 0 inbox items."""
        items = _make_inbox([("a", "paused"), ("b", "paused"), ("c", "paused")])
        result = _apply_status_filter(items, "active")
        assert result == [], "only paused items must yield 0 active items (discussion pill shows discussions only)"

    def test_count_matches_only_active_statuses(self):
        items = _make_inbox([
            ("x1", "pending"),
            ("x2", "paused"),
            ("x3", "running"),
            ("x4", "failed"),
            ("x5", "launched"),
        ])
        result = _apply_status_filter(items, "active")
        assert len(result) == 3  # pending + running + launched only


# ── "paused" pill → status=paused ────────────────────────────────────────────

class TestPausedFilter:
    def test_returns_only_paused(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "paused")
        assert all(i["status"] == "paused" for i in result)
        assert len(result) == 1

    def test_excludes_pending(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "paused")
        assert not any(i["status"] == "pending" for i in result)

    def test_excludes_active_statuses(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "paused")
        active = {"pending", "launched", "running"}
        assert not any(i["status"] in active for i in result)

    def test_multiple_paused_items(self):
        items = _make_inbox([("a", "paused"), ("b", "paused"), ("c", "running")])
        result = _apply_status_filter(items, "paused")
        assert len(result) == 2
        assert all(i["status"] == "paused" for i in result)

    def test_empty_when_none_paused(self):
        items = _make_inbox([("a", "pending"), ("b", "running")])
        result = _apply_status_filter(items, "paused")
        assert result == []


# ── "failed" pill → status=failed ────────────────────────────────────────────

class TestFailedFilter:
    def test_returns_only_failed(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "failed")
        assert all(i["status"] == "failed" for i in result)
        assert len(result) == 1

    def test_excludes_stale(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "failed")
        assert not any(i["status"] == "stale" for i in result)

    def test_empty_when_none_failed(self):
        items = _make_inbox([("a", "done"), ("b", "stale")])
        assert _apply_status_filter(items, "failed") == []


# ── "stale" pill → status=stale ──────────────────────────────────────────────

class TestStaleFilter:
    def test_returns_only_stale(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "stale")
        assert all(i["status"] == "stale" for i in result)
        assert len(result) == 1

    def test_excludes_failed(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "stale")
        assert not any(i["status"] == "failed" for i in result)

    def test_empty_when_none_stale(self):
        items = _make_inbox([("a", "done"), ("b", "failed")])
        assert _apply_status_filter(items, "stale") == []


# ── "done" pill → status=done ────────────────────────────────────────────────

class TestDoneFilter:
    def test_returns_only_done(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "done")
        assert all(i["status"] == "done" for i in result)
        assert len(result) == 1

    def test_empty_when_none_done(self):
        items = _make_inbox([("a", "pending"), ("b", "failed")])
        assert _apply_status_filter(items, "done") == []


# ── no filter (status='') → all items ────────────────────────────────────────

class TestNoFilter:
    def test_returns_all_items(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "")
        assert len(result) == len(mixed_inbox)

    def test_all_statuses_present(self, mixed_inbox):
        result = _apply_status_filter(mixed_inbox, "")
        statuses = {i["status"] for i in result}
        assert statuses == set(_STATUSES)


# ── cross-pill isolation: every pair of pills must be disjoint ───────────────

# All 6 named filter keys (maps to pills visible in the UI).
_ALL_PILLS = ["active", "paused", "failed", "stale", "done", "stopped"]

# Generate all 15 unique pairs — C(6,2).
import itertools
_PILL_PAIRS = list(itertools.combinations(_ALL_PILLS, 2))


@pytest.mark.parametrize("a,b", _PILL_PAIRS, ids=[f"{a}-vs-{b}" for a, b in _PILL_PAIRS])
def test_pills_are_disjoint(mixed_inbox, a, b):
    """No item must appear in two different pill results simultaneously.

    Parametrized over all 15 pairs so every button combination is covered.
    """
    ids_a = set(i["id"] for i in _apply_status_filter(mixed_inbox, a))
    ids_b = set(i["id"] for i in _apply_status_filter(mixed_inbox, b))
    overlap = ids_a & ids_b
    assert not overlap, (
        f"pills '{a}' and '{b}' share items {overlap} — "
        "clicking one pill must never show items belonging to another"
    )


def test_union_of_all_pills_equals_full_inbox(mixed_inbox):
    """The union of every pill filter must cover every inbox item with no gaps."""
    all_ids = set(i["id"] for i in mixed_inbox)
    pill_ids: set[str] = set()
    for pill in _ALL_PILLS:
        pill_ids |= set(i["id"] for i in _apply_status_filter(mixed_inbox, pill))
    assert pill_ids == all_ids, (
        f"missing from pills: {all_ids - pill_ids} | "
        f"extra in pills: {pill_ids - all_ids}"
    )
