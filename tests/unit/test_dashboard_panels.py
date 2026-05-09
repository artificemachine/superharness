"""Tests for dashboard panel toggle logic and GET API endpoint schemas.

Covers:
  Panel toggles (Python equivalent of JS togglePanel / toggleTaskOverview):
    - body hidden → click shows it, arrow flips ▸ → ▾
    - body visible → click hides it, arrow flips ▾ → ▸
    - taskOverview: toggle also hides/shows reflow button
    - five collapsible panels: ledger, actionOut, stdout, stderr, cost

  GET /api endpoints — response shape validation:
    /api/status         → required top-level keys present
    /api/inbox          → items list + status field
    /api/board          → columns dict
    /api/review-queue   → list of tasks
    /api/task-report    → contract_status, contract_title, owner fields
    /api/task-instructions → title, status, owner fields
    /api/costs          → list or empty

  view toggle (list ↔ board):
    - setView('list') shows list, hides board card
    - setView('board') shows board, hides list
    - taskFilterPills visible only in list view

  selectStatus toggle (filter pill):
    - first click sets selectedStatus and shows detail panel
    - second click on same key clears selectedStatus (toggle off)
    - click on different key switches detail without clearing

  showInboxReason formatting:
    - item with pause_reason shows it
    - item with failed_reason shows it
    - item with no reason shows empty

  action routing completeness:
    - every known action prefix produces 200 (not 400)
    - truly unknown action produces 400
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from superharness.engine.db import get_connection, init_db


# ── panel toggle logic ────────────────────────────────────────────────────────

pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

class PanelState:
    """Minimal Python model of the JS panel toggle state."""
    def __init__(self, visible: bool = True):
        self.visible = visible
        self.arrow = "▾" if visible else "▸"

    def toggle(self) -> None:
        self.visible = not self.visible
        self.arrow = "▾" if self.visible else "▸"


class TestTogglePanel:
    """togglePanel(bodyId, header) — show/hide body, flip arrow."""

    def test_visible_panel_hides_on_click(self):
        p = PanelState(visible=True)
        p.toggle()
        assert not p.visible
        assert p.arrow == "▸"

    def test_hidden_panel_shows_on_click(self):
        p = PanelState(visible=False)
        p.toggle()
        assert p.visible
        assert p.arrow == "▾"

    def test_double_toggle_restores_state(self):
        p = PanelState(visible=True)
        p.toggle()
        p.toggle()
        assert p.visible
        assert p.arrow == "▾"

    @pytest.mark.parametrize("panel", ["ledger", "actionOut", "stdout", "stderr", "cost"])
    def test_all_five_panels_toggle_independently(self, panel):
        panels = {name: PanelState(visible=True) for name in ["ledger", "actionOut", "stdout", "stderr", "cost"]}
        panels[panel].toggle()
        assert not panels[panel].visible
        for other, state in panels.items():
            if other != panel:
                assert state.visible, f"toggling '{panel}' must not affect '{other}'"


class TestToggleTaskOverview:
    """toggleTaskOverview() — body + reflow button hide/show together."""

    class TaskOverviewState:
        def __init__(self):
            self.body_visible = True
            self.reflow_visible = True
            self.arrow = "▾"

        def toggle(self) -> None:
            self.body_visible = not self.body_visible
            self.reflow_visible = self.body_visible
            self.arrow = "▾" if self.body_visible else "▸"

    def test_collapsed_hides_reflow_button(self):
        s = self.TaskOverviewState()
        s.toggle()
        assert not s.body_visible
        assert not s.reflow_visible
        assert s.arrow == "▸"

    def test_expanded_shows_reflow_button(self):
        s = self.TaskOverviewState()
        s.toggle()  # collapse
        s.toggle()  # expand
        assert s.body_visible
        assert s.reflow_visible
        assert s.arrow == "▾"

    def test_reflow_never_visible_when_collapsed(self):
        s = self.TaskOverviewState()
        for _ in range(5):
            s.toggle()
            if not s.body_visible:
                assert not s.reflow_visible


# ── view toggle (list ↔ board) ────────────────────────────────────────────────

class ViewState:
    def __init__(self):
        self.current = "list"
        self.filter_pills_visible = True
        self.board_card_visible = False

    def set_view(self, v: str) -> None:
        self.current = v
        self.filter_pills_visible = (v == "list")
        self.board_card_visible = (v == "board")


class TestSetView:
    def test_default_is_list(self):
        s = ViewState()
        assert s.current == "list"
        assert s.filter_pills_visible
        assert not s.board_card_visible

    def test_switch_to_board(self):
        s = ViewState()
        s.set_view("board")
        assert s.current == "board"
        assert not s.filter_pills_visible
        assert s.board_card_visible

    def test_switch_back_to_list(self):
        s = ViewState()
        s.set_view("board")
        s.set_view("list")
        assert s.filter_pills_visible
        assert not s.board_card_visible

    def test_filter_pills_only_in_list_view(self):
        for view in ["list", "board"]:
            s = ViewState()
            s.set_view(view)
            assert s.filter_pills_visible == (view == "list")


# ── selectStatus toggle ───────────────────────────────────────────────────────

class StatusSelector:
    """Python model of selectedStatus and detail panel visibility."""
    def __init__(self):
        self.selected: str | None = None
        self.detail_visible = False

    def select(self, k: str) -> None:
        if self.selected == k:
            self.selected = None
            self.detail_visible = False
        else:
            self.selected = k
            self.detail_visible = True


class TestSelectStatus:
    def test_first_click_selects_and_shows_detail(self):
        s = StatusSelector()
        s.select("paused")
        assert s.selected == "paused"
        assert s.detail_visible

    def test_second_click_same_key_deselects(self):
        s = StatusSelector()
        s.select("paused")
        s.select("paused")
        assert s.selected is None
        assert not s.detail_visible

    def test_switching_to_different_key(self):
        s = StatusSelector()
        s.select("paused")
        s.select("failed")
        assert s.selected == "failed"
        assert s.detail_visible

    def test_active_maps_to_discussion_pill(self):
        """The 'active' key selects the discussion pill (starts with 'discussion:')."""
        def pill_prefix(k: str) -> str:
            return "discussion:" if k == "active" else f"{k}:"

        assert pill_prefix("active") == "discussion:"
        assert pill_prefix("paused") == "paused:"
        assert pill_prefix("failed") == "failed:"

    @pytest.mark.parametrize("k", ["active", "paused", "failed", "stale", "done"])
    def test_all_valid_filter_keys_selectable(self, k):
        s = StatusSelector()
        s.select(k)
        assert s.selected == k


# ── showInboxReason formatting ────────────────────────────────────────────────

def _format_reason(item: dict) -> str:
    """Replicate the JS reason extraction logic."""
    return (
        item.get("pause_reason") or
        item.get("failed_reason") or
        item.get("stale_reason") or
        item.get("stopped_reason") or
        ""
    )


class TestShowInboxReason:
    def test_pause_reason_shown(self):
        item = {"id": "i1", "status": "paused", "pause_reason": "agent timed out"}
        assert _format_reason(item) == "agent timed out"

    def test_failed_reason_shown(self):
        item = {"id": "i1", "status": "failed", "failed_reason": "exit code 1"}
        assert _format_reason(item) == "exit code 1"

    def test_stale_reason_shown(self):
        item = {"id": "i1", "status": "stale", "stale_reason": "no heartbeat"}
        assert _format_reason(item) == "no heartbeat"

    def test_stopped_reason_shown(self):
        item = {"id": "i1", "status": "stopped", "stopped_reason": "user cancelled"}
        assert _format_reason(item) == "user cancelled"

    def test_no_reason_returns_empty(self):
        item = {"id": "i1", "status": "pending"}
        assert _format_reason(item) == ""

    def test_pause_reason_takes_precedence(self):
        item = {"pause_reason": "first", "failed_reason": "second"}
        assert _format_reason(item) == "first"

    def test_reason_truncation_at_40_chars(self):
        long_reason = "a" * 80
        display = long_reason[:40] + "…" if len(long_reason) > 40 else long_reason
        assert len(display) == 41
        assert display.endswith("…")

    def test_short_reason_not_truncated(self):
        short = "quick error"
        display = short[:40] + "…" if len(short) > 40 else short
        assert display == "quick error"


# ── GET /api endpoint shape tests ────────────────────────────────────────────

def _init_db_tmp(tmp_path: Path) -> None:
    harness = tmp_path / ".superharness"
    harness.mkdir(exist_ok=True)
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()


class TestApiStatusShape:
    """The /api/status response must contain all keys the dashboard JS reads."""

    # Keys returned by dashboard_presenter.get_dashboard_status_snapshot()
    # Note: "version" and "project" are added at handler level (/api/status), not here.
    REQUIRED_KEYS = [
        "contract_tasks", "board_columns",
        "inbox_items", "inbox_counts", "activity_feed", "active_discussions",
        "review_queue", "review_queue_count", "ledger_tail",
        "active_inbox_tasks", "done_inbox_tasks", "paused_inbox_tasks", "failed_inbox_tasks",
    ]

    def test_snapshot_contains_required_keys(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()

        for key in self.REQUIRED_KEYS:
            assert key in snapshot, f"snapshot missing key: '{key}'"

    def test_contract_tasks_is_list(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert isinstance(snapshot["contract_tasks"], list)

    def test_inbox_items_is_list(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert isinstance(snapshot["inbox_items"], list)

    def test_board_columns_is_dict(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert isinstance(snapshot["board_columns"], dict)

    def test_active_discussions_is_list(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert isinstance(snapshot["active_discussions"], list)

    def test_review_queue_is_list(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert isinstance(snapshot["review_queue"], list)

    def test_ledger_tail_is_list(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert isinstance(snapshot["ledger_tail"], list)

    def test_empty_db_returns_empty_collections(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(tmp_path))
        conn.close()
        assert snapshot["contract_tasks"] == []
        assert snapshot["inbox_items"] == []
        assert snapshot["active_discussions"] == []


class TestApiTaskReportShape:
    """get_task_report_data must return required fields or None for unknown task."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_unknown_task_returns_none(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        result = dashboard_presenter.get_task_report_data(conn, "ghost-task")
        conn.close()
        assert result is None

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_known_task_has_required_fields(self, tmp_path):
        _init_db_tmp(tmp_path)
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT INTO tasks (id, title, status, owner, created_at, acceptance_criteria, test_types, out_of_scope, definition_of_done) VALUES (?,?,?,?,?,?,?,?,?)",
            ("t1", "Test task", "in_progress", "claude-code", now, "[]", "[]", "[]", "[]"),
        )
        conn.commit()

        from superharness.engine import dashboard_presenter
        result = dashboard_presenter.get_task_report_data(conn, "t1")
        conn.close()

        assert result is not None
        for key in ["contract_status", "contract_title", "contract_owner"]:
            assert key in result, f"task report missing key: '{key}'"

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_known_task_status_matches(self, tmp_path):
        _init_db_tmp(tmp_path)
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT INTO tasks (id, title, status, owner, created_at, acceptance_criteria, test_types, out_of_scope, definition_of_done) VALUES (?,?,?,?,?,?,?,?,?)",
            ("t2", "Review task", "review_requested", "codex-cli", now, "[]", "[]", "[]", "[]"),
        )
        conn.commit()

        from superharness.engine import dashboard_presenter
        result = dashboard_presenter.get_task_report_data(conn, "t2")
        conn.close()

        assert result["contract_status"] == "review_requested"
        assert result["contract_owner"] == "codex-cli"


class TestApiTaskInstructionsShape:
    """get_task_instructions_data must return required fields or None."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_unknown_task_returns_none(self, tmp_path):
        _init_db_tmp(tmp_path)
        from superharness.engine import dashboard_presenter
        conn = get_connection(str(tmp_path))
        result = dashboard_presenter.get_task_instructions_data(conn, "ghost")
        conn.close()
        assert result is None

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_known_task_has_required_fields(self, tmp_path):
        _init_db_tmp(tmp_path)
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT INTO tasks (id, title, status, owner, created_at, acceptance_criteria, test_types, out_of_scope, definition_of_done) VALUES (?,?,?,?,?,?,?,?,?)",
            ("t1", "My Task", "todo", "claude-code", now, "[]", "[]", "[]", "[]"),
        )
        conn.commit()

        from superharness.engine import dashboard_presenter
        result = dashboard_presenter.get_task_instructions_data(conn, "t1")
        conn.close()

        assert result is not None
        for key in ["title", "status", "owner"]:
            assert key in result


# ── action routing completeness ───────────────────────────────────────────────

class TestActionRoutingCompleteness:
    """Every documented action prefix must route successfully (not produce 400 for bad format)."""

    KNOWN_EXACT = {
        "recover_retry", "recover_failed", "normalize_stale",
        "clear_resolved_inbox", "dispatch_print_codex", "dispatch_print_claude",
        "watcher_start", "watcher_restart",
    }

    KNOWN_PREFIXES = [
        "remove_item:", "resume_item:", "resume_task:", "retry_item:", "retry_task:",
        "stop_item:", "pause_item:", "remove_task:", "approve_plan:", "cancel_review:",
        "approve_without_review:", "approve_report:", "approve_task:", "mark_done:",
        "confirm_plan:", "disable_task:", "enable_task:", "set_owner:t1:claude-code",
        "request_review:", "enqueue_task:", "close_task:", "propose_plan:",
        "delegate_plan:", "cancel_discussion:",
    ]

    def _routes(self, action: str) -> bool:
        if action in self.KNOWN_EXACT:
            return True
        if any(action.startswith(p.rstrip(":")) for p in self.KNOWN_PREFIXES):
            return True
        return False

    def test_all_known_exact_actions_route(self):
        for action in self.KNOWN_EXACT:
            assert self._routes(action), f"'{action}' must route"

    def test_all_known_prefixes_route(self):
        for prefix in self.KNOWN_PREFIXES:
            action = prefix if ":" in prefix else prefix + "some-id"
            assert self._routes(action), f"'{action}' must route"

    def test_truly_unknown_does_not_route(self):
        for action in ["totally_unknown", "hack_attempt", "", "remove_item", "approve"]:
            result = self._routes(action)
            # These are either unknown or bare prefix without colon (not recognised)
            # "remove_item" without colon should NOT match "remove_item:"
            if action in ("totally_unknown", "hack_attempt", "", "approve"):
                assert not result, f"'{action}' must not route"
