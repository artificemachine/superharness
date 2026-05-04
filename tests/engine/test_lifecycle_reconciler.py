"""Tests for engine.lifecycle_rules — data-driven timeout enforcement.

Covers the rule table (LIFECYCLE_RULES) and the reconcile_lifecycle entry point.
Tests use the past_iso helper from conftest to set up timeout scenarios without
requiring time-mocking libraries.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from tests.conftest import past_iso


def _write_inbox(project: Path, items: list[dict]) -> None:
    (project / ".superharness" / "inbox.yaml").write_text(yaml.dump(items))


def _read_inbox(project: Path) -> list[dict]:
    return yaml.safe_load((project / ".superharness" / "inbox.yaml").read_text()) or []


def _write_contract(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness" / "contract.yaml").write_text(yaml.dump({"tasks": tasks}))


def _read_contract(project: Path) -> dict:
    return yaml.safe_load((project / ".superharness" / "contract.yaml").read_text()) or {}


def test_paused_item_no_reason_after_30m_becomes_failed(clean_harness: Path) -> None:
    """The paused-timeout rule from this session: 30m without reason → failed."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_inbox(clean_harness, [{
        "id": "test-1", "task": "feat.foo", "to": "claude-code",
        "status": "paused", "paused_at": past_iso(31),
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n >= 1
    items = _read_inbox(clean_harness)
    assert items[0]["status"] == "failed"
    assert "paused timeout" in items[0].get("failed_reason", "").lower()


def test_paused_item_with_reason_is_immune_to_timeout(clean_harness: Path) -> None:
    """Manual operator pauses (with reason) must not be auto-failed."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_inbox(clean_harness, [{
        "id": "test-1", "task": "feat.foo", "to": "claude-code",
        "status": "paused", "paused_at": past_iso(120),
        "reason": "manually paused by operator",
    }])
    reconcile_lifecycle(str(clean_harness))
    items = _read_inbox(clean_harness)
    assert items[0]["status"] == "paused"  # unchanged


def test_review_requested_after_120m_reverts_to_report_ready(clean_harness: Path) -> None:
    """The review timeout rule from this session: 120m → revert to report_ready."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "review_requested", "review_requested_at": past_iso(121),
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n >= 1
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "report_ready"


def test_in_progress_task_after_180m_is_archived(clean_harness: Path) -> None:
    """Iter 4 rule: in_progress > 180m gets archived (uses updated_at timestamp)."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "in_progress", "updated_at": past_iso(181),
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n >= 1
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "archived"


def test_review_requested_within_timeout_is_unchanged(clean_harness: Path) -> None:
    """Reviews within timeout window must not be touched."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "review_requested", "review_requested_at": past_iso(60),  # under 120
    }])
    reconcile_lifecycle(str(clean_harness))
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "review_requested"


def test_lifecycle_rules_table_is_data_driven() -> None:
    """Adding a row to LIFECYCLE_RULES affects no other code."""
    from superharness.engine.lifecycle_rules import LIFECYCLE_RULES

    assert isinstance(LIFECYCLE_RULES, list)
    assert all(hasattr(r, "state") for r in LIFECYCLE_RULES)
    assert all(hasattr(r, "timeout_minutes") for r in LIFECYCLE_RULES)
    assert all(hasattr(r, "on_timeout") for r in LIFECYCLE_RULES)
    # Spot-check the rules from the plan
    states = {r.state for r in LIFECYCLE_RULES}
    assert "paused" in states
    assert "review_requested" in states
    assert "in_progress" in states
    assert "waiting_input" in states
    assert "report_ready" in states


def test_reconcile_with_no_matching_items_returns_zero(clean_harness: Path) -> None:
    """No items, no tasks: reconciler is a safe no-op."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    n = reconcile_lifecycle(str(clean_harness))
    assert n == 0


def test_reconcile_uses_profile_overrides(clean_harness: Path) -> None:
    """Custom timeouts in profile.yaml override defaults."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    # Lower paused timeout to 10m via profile
    profile = clean_harness / ".superharness" / "profile.yaml"
    profile.write_text(profile.read_text() + "\npaused_timeout_minutes: 10\n")

    _write_inbox(clean_harness, [{
        "id": "test-1", "task": "feat.foo", "to": "claude-code",
        "status": "paused", "paused_at": past_iso(11),  # over 10m
    }])
    reconcile_lifecycle(str(clean_harness))
    items = _read_inbox(clean_harness)
    assert items[0]["status"] == "failed"


# ---------------------------------------------------------------------------
# New rules: waiting_input, report_ready, deadline enforcement
# ---------------------------------------------------------------------------


def test_waiting_input_task_after_480m_is_failed(clean_harness: Path) -> None:
    """waiting_input > 480m (8h) → failed."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "waiting_input", "updated_at": past_iso(481),
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n >= 1
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "failed"
    assert "waiting_input timeout" in doc["tasks"][0].get("failed_reason", "")


def test_waiting_input_task_within_timeout_is_unchanged(clean_harness: Path) -> None:
    """waiting_input under 480m must not be touched."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "waiting_input", "updated_at": past_iso(60),
    }])
    reconcile_lifecycle(str(clean_harness))
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "waiting_input"


def test_report_ready_after_1440m_is_archived(clean_harness: Path) -> None:
    """report_ready > 1440m (24h) → archived."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "report_ready", "report_ready_at": past_iso(1441),
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n >= 1
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "archived"
    assert "report_ready timeout" in doc["tasks"][0].get("archived_reason", "")


def test_report_ready_within_timeout_is_unchanged(clean_harness: Path) -> None:
    """report_ready under 1440m must not be touched."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "report_ready", "report_ready_at": past_iso(120),
    }])
    reconcile_lifecycle(str(clean_harness))
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "report_ready"


def test_deadline_exceeded_task_fails(clean_harness: Path) -> None:
    """in_progress task with deadline_minutes exceeded → failed."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "in_progress",
        "created_at": past_iso(500),  # created 500 min ago
        "deadline_minutes": 480,     # deadline is 480 min
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n >= 1
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "failed"
    assert "deadline exceeded" in doc["tasks"][0].get("failed_reason", "")


def test_deadline_not_exceeded_task_unchanged(clean_harness: Path) -> None:
    """Task with deadline_minutes not yet exceeded stays unchanged."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "in_progress",
        "created_at": past_iso(60),  # created 60 min ago
        "deadline_minutes": 480,     # deadline is 480 min
    }])
    reconcile_lifecycle(str(clean_harness))
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "in_progress"


def test_deadline_skips_done_tasks(clean_harness: Path) -> None:
    """Done tasks are never flagged by deadline enforcement."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "done",
        "created_at": past_iso(500),
        "deadline_minutes": 60,  # way past deadline
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n == 0
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "done"


def test_deadline_skips_task_without_deadline(clean_harness: Path) -> None:
    """Tasks with no deadline_minutes are not affected."""
    from superharness.engine.lifecycle_rules import reconcile_lifecycle

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "in_progress",
        "created_at": past_iso(500),
        # no deadline_minutes set
    }])
    n = reconcile_lifecycle(str(clean_harness))
    assert n == 0
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0]["status"] == "in_progress"


def test_taskrow_updated_at_survives_asdict(clean_harness: Path) -> None:
    """Verify updated_at is preserved when TaskRow is exported via asdict().

    This is the production path: SQLite → TaskRow → asdict → lifecycle rules.
    The field was previously missing from TaskRow, causing all updated_at-based
    rules to silently skip.
    """
    from dataclasses import asdict
    from superharness.engine.tasks_dao import TaskRow

    task = TaskRow(
        id="test-1",
        title="Test Task",
        owner="claude-code",
        status="in_progress",
        effort="medium",
        project_path="/tmp/test",
        development_method="tdd",
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd=None,
        version=1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T12:00:00Z",
    )
    d = asdict(task)
    assert "updated_at" in d
    assert d["updated_at"] == "2026-01-01T12:00:00Z"
    # deadline_minutes should also survive
    task2 = TaskRow(
        id="test-2",
        title="With Deadline",
        owner="claude-code",
        status="in_progress",
        effort="medium",
        project_path="/tmp/test",
        development_method="tdd",
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd=None,
        version=1,
        created_at="2026-01-01T00:00:00Z",
        deadline_minutes=480,
    )
    d2 = asdict(task2)
    assert "deadline_minutes" in d2
    assert d2["deadline_minutes"] == 480
