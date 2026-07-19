"""Tests for the test-environment guardrail: fail fast when a test targets a
non-ephemeral SUPERHARNESS_STATE_DIR.

See docs/PLAN-steal-omnigent.md iteration 1.
"""
from __future__ import annotations

import pytest

from tests.conftest import _assert_ephemeral_state_dir


def test_guardrail_rejects_home_state_dir(monkeypatch):
    monkeypatch.setenv(
        "SUPERHARNESS_STATE_DIR", "/Users/someuser/.local/state/superharness"
    )
    with pytest.raises(RuntimeError, match="someuser"):
        _assert_ephemeral_state_dir()


def test_guardrail_accepts_tmp_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "state"))
    _assert_ephemeral_state_dir()  # must not raise


def test_guardrail_rejects_unset_env(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="SUPERHARNESS_STATE_DIR"):
        _assert_ephemeral_state_dir()
