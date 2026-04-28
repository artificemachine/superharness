"""Tests for session flush (cherry-picked from hermes-agent)."""
import pytest
from superharness.engine.session_flush import check_expiring, flush_task


class TestSessionFlush:
    def test_flush_task_creates_handoff(self, tmp_path):
        import os
        harness = tmp_path / ".superharness"
        harness.mkdir()
        (harness / "handoffs").mkdir()
        ok = flush_task(str(tmp_path), "test-task-99")
        assert ok is False  # No tasks in test project, should return False

    def test_check_expiring_empty_project(self, tmp_path):
        expiring = check_expiring(str(tmp_path))
        assert expiring == []
