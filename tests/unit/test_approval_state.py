"""Tests for smart approval state with risk classification."""
import json
import os
import pytest
from superharness.guard.state import ApprovalState


class TestApprovalState:
    def test_auto_approve_low_risk_echo(self):
        state = ApprovalState()
        assert state.check_risk("echo hello") == "low"

    def test_auto_approve_low_risk_ls(self):
        state = ApprovalState()
        assert state.check_risk("ls -la") == "low"

    def test_high_risk_rm_rf(self):
        state = ApprovalState()
        assert state.check_risk("rm -rf /") == "high"

    def test_medium_risk_git_push(self):
        state = ApprovalState()
        assert state.check_risk("git push origin main") == "medium"

    def test_permanent_approval_persists(self, tmp_path):
        config_file = tmp_path / "approvals.json"
        state = ApprovalState(config_path=str(config_file))
        state.approve("rm", scope="permanent")
        # New state loading same config should see approval
        state2 = ApprovalState(config_path=str(config_file))
        assert state2.is_approved("rm -rf /tmp/test") is True

    def test_reset_session_clears_once(self):
        state = ApprovalState()
        state.approve("rm -rf /tmp", scope="once")
        state.reset()
        assert state.is_approved("rm -rf /tmp") is False

    def test_reset_session_keeps_permanent(self, tmp_path):
        config_file = tmp_path / "approvals2.json"
        state = ApprovalState(config_path=str(config_file))
        state.approve("rm", scope="permanent")
        state.reset()
        assert state.is_approved("rm -rf /tmp") is True

    def test_thread_safe_concurrent(self):
        import threading
        state = ApprovalState()
        results = []

        def approve_batch():
            for i in range(100):
                state.approve(f"cmd-{i}", scope="once")

        threads = [threading.Thread(target=approve_batch) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # All 500 commands should be approved
        for i in range(100):
            assert state.is_approved(f"cmd-{i}") is True
