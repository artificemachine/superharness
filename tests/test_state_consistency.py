"""State-consistency tests: pin down YAML/SQLite drift and timeout behavior.

These tests document invariants that the auto-mode-gap-plan iterations must
preserve. They use the `clean_harness` and `frozen_time` fixtures.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_clean_harness_creates_valid_workspace(clean_harness: Path) -> None:
    """The clean_harness fixture creates a usable .superharness/ tree."""
    h = clean_harness / ".superharness"
    assert h.is_dir()
    assert (h / "contract.yaml").exists()
    assert (h / "inbox.yaml").exists()
    assert (h / "profile.yaml").exists()
    assert (h / "handoffs").is_dir()
    assert (h / "discussions").is_dir()


def test_past_iso_helper_returns_timestamp_in_past() -> None:
    """The past_iso helper returns a valid ISO timestamp N minutes ago."""
    from datetime import datetime, timezone

    from tests.conftest import past_iso

    ts = past_iso(31)
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    age_minutes = (datetime.now(timezone.utc) - parsed).total_seconds() / 60
    assert 30.5 < age_minutes < 31.5
