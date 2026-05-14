"""Tests for review_escalation — RED tests for iter 7 of auto-mode-gap-plan.

Replaces the simple revert-after-timeout behavior from iter 2 with an
escalation chain: if reviewer A doesn't respond, advance to reviewer B,
then to operator. Today the lifecycle rule for review_requested just
reverts to report_ready, which loses the escalation context.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.conftest import past_iso
from tests.helpers import seed_sqlite_from_yaml


def _write_contract(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness" / "contract.yaml").write_text(yaml.dump({"tasks": tasks}))
    seed_sqlite_from_yaml(project)


def _read_contract(project: Path) -> dict:
    from superharness.engine import state_reader
    return {"tasks": state_reader.get_tasks(str(project))}


def test_review_with_chain_advances_to_next_reviewer_on_timeout(clean_harness: Path) -> None:
    from superharness.engine.review_escalation import escalate_stale_reviews

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "review_requested",
        "review_requested_at": past_iso(121),
        "review_chain": ["codex-cli", "gemini-cli"],
        "review_chain_index": 0,
        "review_target": "codex-cli",
    }])
    n = escalate_stale_reviews(str(clean_harness))
    assert n == 1
    doc = _read_contract(clean_harness)
    t = doc["tasks"][0]
    assert t["status"] == "review_requested"  # still in review
    assert t["review_chain_index"] == 1
    assert t["review_target"] == "gemini-cli"


def test_review_with_chain_exhausted_escalates_to_operator(clean_harness: Path) -> None:
    from superharness.engine.review_escalation import escalate_stale_reviews

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "review_requested",
        "review_requested_at": past_iso(121),
        "review_chain": ["codex-cli", "gemini-cli"],
        "review_chain_index": 1,
        "review_target": "gemini-cli",
    }])
    n = escalate_stale_reviews(str(clean_harness))
    assert n == 1
    doc = _read_contract(clean_harness)
    t = doc["tasks"][0]
    assert t["status"] == "review_requested"
    assert t.get("escalated_to") == "operator"


def test_review_within_timeout_is_unchanged(clean_harness: Path) -> None:
    from superharness.engine.review_escalation import escalate_stale_reviews

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "review_requested",
        "review_requested_at": past_iso(60),
        "review_chain": ["codex-cli", "gemini-cli"],
        "review_chain_index": 0,
        "review_target": "codex-cli",
    }])
    n = escalate_stale_reviews(str(clean_harness))
    assert n == 0
    doc = _read_contract(clean_harness)
    t = doc["tasks"][0]
    assert t["review_chain_index"] == 0


def test_review_without_chain_falls_back_to_operator(clean_harness: Path) -> None:
    """No review_chain field means immediate operator escalation on timeout."""
    from superharness.engine.review_escalation import escalate_stale_reviews

    _write_contract(clean_harness, [{
        "id": "feat.foo", "owner": "claude-code",
        "status": "review_requested",
        "review_requested_at": past_iso(121),
        # no review_chain
    }])
    n = escalate_stale_reviews(str(clean_harness))
    assert n == 1
    doc = _read_contract(clean_harness)
    assert doc["tasks"][0].get("escalated_to") == "operator"
