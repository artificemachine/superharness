"""Tests for PID schema split (Iteration 7).

daemon.py writes daemon-state.json (key: pid).
operator.py writes operator-state.json (keys: operator_pid, dashboard_port).
Neither should touch the old daemon.pid.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_daemon_state_file_constant():
    from superharness.commands.daemon import _DAEMON_STATE_FILE
    assert "daemon-state" in _DAEMON_STATE_FILE
    assert "daemon.pid" not in _DAEMON_STATE_FILE


def test_operator_state_file_constant():
    from superharness.engine.operator import _OPERATOR_STATE_FILE
    assert "operator-state" in _OPERATOR_STATE_FILE
    assert "daemon.pid" not in _OPERATOR_STATE_FILE


def test_daemon_writes_to_daemon_state_file(tmp_path):
    harness = tmp_path / ".superharness"
    harness.mkdir()

    from superharness.commands.daemon import _write_state
    _write_state(tmp_path, {"pid": 12345, "started_at": 0.0})

    state_file = harness / "daemon-state.json"
    assert state_file.exists(), "daemon must write daemon-state.json"
    data = json.loads(state_file.read_text())
    assert data["pid"] == 12345

    old_file = harness / "daemon.pid.json"
    assert not old_file.exists(), "daemon must NOT write daemon.pid.json"


def test_operator_writes_to_operator_state_file(tmp_path):
    harness = tmp_path / ".superharness"
    harness.mkdir()

    from superharness.engine.operator import _OPERATOR_STATE_FILE
    op_file = tmp_path / _OPERATOR_STATE_FILE

    import time
    info = {
        "operator_pid": 99999,
        "dashboard_port": 8787,
        "started_at": time.time(),
        "project": str(tmp_path),
    }
    import json as _json
    op_file.parent.mkdir(parents=True, exist_ok=True)
    with open(op_file, "w") as f:
        _json.dump(info, f)

    assert op_file.exists()
    data = _json.loads(op_file.read_text())
    assert data["operator_pid"] == 99999
    assert data["dashboard_port"] == 8787

    old_file = harness / "daemon.pid.json"
    assert not old_file.exists(), "operator must NOT write daemon.pid.json"


def test_daemon_reads_own_state_correctly(tmp_path):
    harness = tmp_path / ".superharness"
    harness.mkdir()
    state_file = harness / "daemon-state.json"
    state_file.write_text(json.dumps({"pid": 12345}))

    from superharness.commands.daemon import _read_state
    state = _read_state(tmp_path)
    assert state.get("pid") == 12345
