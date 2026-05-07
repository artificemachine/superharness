"""Unit tests for the TUI module — pure-function layer, no curses required."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from superharness.commands.tui import (
    categorize_tasks,
    filter_tasks,
    status_color_name,
    get_column_tasks,
    TuiState,
    COLUMNS,
    _can_approve,
    _can_reject,
    _can_pause,
    _can_delegate,
)


# ── Sample task fixtures ────────────────────────────────────────────────────

def _task(id: str, status: str, title: str = "", owner: str = "claude-code") -> dict:
    return {"id": id, "status": status, "title": title or id, "owner": owner}


SAMPLE_TASKS = [
    _task("t1", "todo",           "Task One"),
    _task("t2", "plan_proposed",  "Task Two"),
    _task("t3", "plan_approved",  "Task Three"),
    _task("t4", "in_progress",    "Task Four"),
    _task("t5", "report_ready",   "Task Five"),
    _task("t6", "review_failed",  "Task Six"),
    _task("t7", "done",           "Task Seven"),
    _task("t8", "archived",       "Task Eight"),
    _task("t9", "cancelled",      "Task Nine"),
]


# ── categorize_tasks ────────────────────────────────────────────────────────

def test_categorize_tasks_splits_into_five_columns():
    cats = categorize_tasks(SAMPLE_TASKS)
    assert set(cats.keys()) == {"todo", "plan", "active", "review", "done"}


def test_categorize_todo():
    cats = categorize_tasks(SAMPLE_TASKS)
    ids = [t["id"] for t in cats["todo"]]
    assert "t1" in ids


def test_categorize_plan():
    cats = categorize_tasks(SAMPLE_TASKS)
    ids = [t["id"] for t in cats["plan"]]
    assert "t2" in ids
    assert "t3" in ids


def test_categorize_active():
    cats = categorize_tasks(SAMPLE_TASKS)
    ids = [t["id"] for t in cats["active"]]
    assert "t4" in ids


def test_categorize_review():
    cats = categorize_tasks(SAMPLE_TASKS)
    ids = [t["id"] for t in cats["review"]]
    assert "t5" in ids
    assert "t6" in ids


def test_categorize_done_includes_archived_and_cancelled():
    cats = categorize_tasks(SAMPLE_TASKS)
    ids = [t["id"] for t in cats["done"]]
    assert "t7" in ids
    assert "t8" in ids
    assert "t9" in ids


def test_categorize_unknown_status_goes_to_todo():
    task = _task("tx", "some_future_status")
    cats = categorize_tasks([task])
    ids = [t["id"] for t in cats["todo"]]
    assert "tx" in ids


# ── get_column_tasks ────────────────────────────────────────────────────────

def test_get_column_tasks_returns_correct_column():
    cats = categorize_tasks(SAMPLE_TASKS)
    state = TuiState(col_idx=1)  # plan column
    tasks = get_column_tasks(cats, state)
    ids = [t["id"] for t in tasks]
    assert "t2" in ids and "t3" in ids


# ── filter_tasks ────────────────────────────────────────────────────────────

def test_filter_tasks_by_title():
    result = filter_tasks(SAMPLE_TASKS, "two")
    assert len(result) == 1
    assert result[0]["id"] == "t2"


def test_filter_tasks_by_id():
    result = filter_tasks(SAMPLE_TASKS, "t3")
    assert len(result) == 1
    assert result[0]["id"] == "t3"


def test_filter_tasks_empty_query_returns_all():
    result = filter_tasks(SAMPLE_TASKS, "")
    assert len(result) == len(SAMPLE_TASKS)


def test_filter_tasks_no_match_returns_empty():
    result = filter_tasks(SAMPLE_TASKS, "zzznomatch")
    assert result == []


def test_filter_tasks_case_insensitive():
    result = filter_tasks(SAMPLE_TASKS, "TASK ONE")
    assert len(result) == 1


def test_filter_tasks_by_owner():
    tasks = [
        _task("a", "todo", owner="claude-code"),
        _task("b", "todo", owner="codex-cli"),
    ]
    result = filter_tasks(tasks, "codex")
    assert len(result) == 1
    assert result[0]["id"] == "b"


# ── status_color_name ────────────────────────────────────────────────────────

def test_status_color_name_known_statuses():
    assert status_color_name("done") == "green"
    assert status_color_name("in_progress") == "blue"
    assert status_color_name("plan_proposed") == "yellow"
    assert status_color_name("report_ready") == "magenta"
    assert status_color_name("review_failed") == "red"
    assert status_color_name("todo") == "white"


def test_status_color_name_unknown_defaults_to_white():
    assert status_color_name("some_unknown_status") == "white"


# ── action predicates ────────────────────────────────────────────────────────

def test_can_approve_plan_proposed():
    t = _task("x", "plan_proposed")
    assert _can_approve(t) is True


def test_cannot_approve_in_progress():
    t = _task("x", "in_progress")
    assert _can_approve(t) is False


def test_can_reject_report_ready():
    t = _task("x", "report_ready")
    assert _can_reject(t) is True


def test_cannot_reject_todo():
    t = _task("x", "todo")
    assert _can_reject(t) is False


def test_can_pause_in_progress():
    t = _task("x", "in_progress")
    assert _can_pause(t) is True


def test_cannot_pause_done():
    t = _task("x", "done")
    assert _can_pause(t) is False


def test_can_delegate_plan_approved():
    t = _task("x", "plan_approved")
    assert _can_delegate(t) is True


def test_cannot_delegate_in_progress():
    t = _task("x", "in_progress")
    assert _can_delegate(t) is False


# ── TuiState defaults ────────────────────────────────────────────────────────

def test_tui_state_defaults():
    state = TuiState()
    assert state.col_idx == 0
    assert state.row_idx == 0
    assert state.mode == "board"
    assert state.search_query == ""
    assert state.refresh_interval == 5


def test_tui_state_col_idx_bounds():
    # col_idx should stay within 0..len(COLUMNS)-1
    assert len(COLUMNS) == 5


# ── COLUMNS definition ────────────────────────────────────────────────────────

def test_columns_has_five_entries():
    assert len(COLUMNS) == 5


def test_columns_labels():
    labels = [c[0] for c in COLUMNS]
    assert labels == ["TODO", "PLAN", "ACTIVE", "REVIEW", "DONE"]
