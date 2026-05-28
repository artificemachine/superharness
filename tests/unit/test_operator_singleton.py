"""Tests for operator singleton enforcement.

When an operator is already running for a project, start_stack() must refuse
to start a second instance. This prevents the process-accumulation bug where
launchd KeepAlive=true combined with lack of singleton enforcement caused
hundreds of operator processes to accumulate.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from superharness.engine.operator import Operator, _OPERATOR_STATE_FILE


def _harness_dir(tmp: Path) -> Path:
    h = tmp / ".superharness"
    h.mkdir(parents=True, exist_ok=True)
    return h


class TestOperatorSingleton:
    def test_no_state_file_is_not_singleton(self, tmp_path):
        """With no operator-state.json, _check_singleton returns False."""
        _harness_dir(tmp_path)
        op = Operator(str(tmp_path))
        assert not op._check_singleton()

    def test_dead_pid_is_not_singleton(self, tmp_path):
        """A state file with a dead PID is treated as stale — not a singleton."""
        _harness_dir(tmp_path)
        state_file = tmp_path / _OPERATOR_STATE_FILE
        state_file.write_text(json.dumps({"operator_pid": 99999999, "dashboard_port": 8787}))

        op = Operator(str(tmp_path))
        result = op._check_singleton()

        assert not result
        assert not state_file.exists(), "stale file should have been removed"

    def test_live_pid_is_singleton(self, tmp_path):
        """A state file with our own PID signals an already-running operator."""
        _harness_dir(tmp_path)
        state_file = tmp_path / _OPERATOR_STATE_FILE
        state_file.write_text(json.dumps({"operator_pid": os.getpid(), "dashboard_port": 8787}))

        op = Operator(str(tmp_path))
        assert op._check_singleton()

    def test_stale_file_removed_on_check(self, tmp_path):
        """_check_singleton removes stale state files so subsequent starts proceed."""
        _harness_dir(tmp_path)
        state_file = tmp_path / _OPERATOR_STATE_FILE
        state_file.write_text(json.dumps({"operator_pid": 99999999, "dashboard_port": 8787}))

        op = Operator(str(tmp_path))
        op._check_singleton()  # should clean up

        assert not state_file.exists()
        # Second check sees no file — also returns False (fresh start is allowed)
        assert not op._check_singleton()

    def test_corrupt_state_file_is_not_singleton(self, tmp_path):
        """A corrupt/empty operator-state.json does not block startup."""
        _harness_dir(tmp_path)
        state_file = tmp_path / _OPERATOR_STATE_FILE
        state_file.write_text("not-valid-json{{{")

        op = Operator(str(tmp_path))
        assert not op._check_singleton()
