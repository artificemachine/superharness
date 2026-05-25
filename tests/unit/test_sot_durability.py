"""C-DURABLE regression tests (bulletproof v10).

When the SQLite SoT write fails in sqlite_only mode, the YAML mirror must be
written as a crash dump. Without this, data is silently lost — no exception
to the caller, no user-facing signal, just a logger.warning in a log file.

Covers the 4 dual-write paths:
  - engine/heartbeat_contract.write_heartbeat
  - engine/agent_status.write_agent_status
  - commands/agent_pulse._write_pulse
  - commands/onboard._save_state
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_project(tmp_path: Path) -> Path:
    """A project dir with .superharness/ created so the writers don't bail early."""
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    return project


def _force_sqlite_only_with_broken_dao():
    """Context: STATE_BACKEND=sqlite_only env + DAO upsert always raises.

    Use via `with patch(...)` for the specific DAO under test.
    """
    return patch.dict(os.environ, {"STATE_BACKEND": "sqlite_only"}, clear=False)


# ---------------------------------------------------------------------------
# heartbeat_contract.write_heartbeat
# ---------------------------------------------------------------------------

def test_durable_heartbeat_falls_back_to_yaml_on_sqlite_failure(tmp_path: Path):
    """When SQLite upsert fails in sqlite_only mode, watcher.heartbeat.yaml must be written."""
    from superharness.engine.heartbeat_contract import write_heartbeat, AgentHeartbeat, heartbeat_path
    project = _make_project(tmp_path)
    yaml_path = Path(heartbeat_path(str(project), "watcher"))
    assert not yaml_path.exists(), "precondition: no YAML mirror yet"

    with _force_sqlite_only_with_broken_dao(), patch(
        "superharness.engine.watcher_heartbeat_dao.upsert",
        side_effect=Exception("simulated SQLite write failure"),
    ):
        write_heartbeat(str(project), AgentHeartbeat(agent_id="watcher", runtime="native"))

    assert yaml_path.exists(), (
        "C-DURABLE violated: SQLite write failed in sqlite_only mode and YAML mirror "
        "was NOT written. Data is silently lost."
    )


def test_heartbeat_yaml_skipped_when_sqlite_succeeds_in_sqlite_only(tmp_path: Path):
    """Inverse: when SQLite write succeeds in sqlite_only mode, YAML is skipped (clean SoT)."""
    from superharness.engine.heartbeat_contract import write_heartbeat, AgentHeartbeat, heartbeat_path
    project = _make_project(tmp_path)
    yaml_path = Path(heartbeat_path(str(project), "watcher"))

    with _force_sqlite_only_with_broken_dao():
        write_heartbeat(str(project), AgentHeartbeat(agent_id="watcher", runtime="native"))

    assert not yaml_path.exists(), (
        "YAML mirror written despite successful SQLite write in sqlite_only mode"
    )


# ---------------------------------------------------------------------------
# agent_status.write_agent_status
# ---------------------------------------------------------------------------

def test_durable_agent_status_falls_back_to_yaml_on_sqlite_failure(tmp_path: Path):
    """When SQLite upsert fails in sqlite_only mode, <runtime>.status.yaml must be written."""
    from superharness.engine.agent_status import write_agent_status, _status_path
    project = _make_project(tmp_path)
    yaml_path = _status_path(project, "claude-code")
    assert not yaml_path.exists()

    with _force_sqlite_only_with_broken_dao(), patch(
        "superharness.engine.agent_runtime_status_dao.upsert",
        side_effect=Exception("simulated SQLite write failure"),
    ):
        write_agent_status(project, runtime="claude-code")

    assert yaml_path.exists(), (
        "C-DURABLE violated: agent_status SQLite write failed in sqlite_only mode "
        "but YAML mirror was NOT written. Data silently lost."
    )


# ---------------------------------------------------------------------------
# agent_pulse._write_pulse
# ---------------------------------------------------------------------------

def test_durable_agent_pulse_falls_back_to_yaml_on_sqlite_failure(tmp_path: Path):
    """When SQLite upsert fails in sqlite_only mode, agent-pulse.yaml must be written."""
    from superharness.commands.agent_pulse import _write_pulse, _pulse_path
    project = _make_project(tmp_path)
    yaml_path = _pulse_path(str(project))
    assert not yaml_path.exists()

    with _force_sqlite_only_with_broken_dao(), patch(
        "superharness.engine.agent_pulse_dao.upsert",
        side_effect=Exception("simulated SQLite write failure"),
    ):
        _write_pulse(str(project), "T-1", "claude-code")

    assert yaml_path.exists(), (
        "C-DURABLE violated: agent_pulse SQLite write failed in sqlite_only mode "
        "but YAML mirror was NOT written. Data silently lost."
    )


# ---------------------------------------------------------------------------
# onboard._save_state
# ---------------------------------------------------------------------------

def test_durable_onboarding_falls_back_to_yaml_on_sqlite_failure(tmp_path: Path):
    """When SQLite upsert fails in sqlite_only mode, onboarding.yaml must be written."""
    from superharness.commands.onboard import _save_state
    project = _make_project(tmp_path)
    sh = project / ".superharness"
    yaml_path = sh / "onboarding.yaml"
    assert not yaml_path.exists()

    state = {"version": 1, "config_version": 1, "steps": {"detect": "completed"}}

    with _force_sqlite_only_with_broken_dao(), patch(
        "superharness.engine.onboarding_dao.upsert",
        side_effect=Exception("simulated SQLite write failure"),
    ):
        _save_state(sh, state)

    assert yaml_path.exists(), (
        "C-DURABLE violated: onboarding SQLite write failed in sqlite_only mode "
        "but YAML mirror was NOT written. Data silently lost."
    )


# ---------------------------------------------------------------------------
# C-DURABLE-READ (v11): after SQLite write fails + crash dump fresher,
# readers must serve the fresh YAML, not the stale SQLite row.
# ---------------------------------------------------------------------------

def test_heartbeat_read_prefers_fresher_yaml_after_sqlite_failure(tmp_path: Path):
    """OLD-data in SQLite + NEW-data in crash-dump YAML → reader returns NEW-data."""
    from superharness.engine.heartbeat_contract import (
        write_heartbeat, read_heartbeat_db, AgentHeartbeat,
    )
    project = _make_project(tmp_path)

    # Step 1: SQLite OK → status=OLD-data
    write_heartbeat(str(project), AgentHeartbeat(agent_id="watcher", runtime="native", status="OLD-data"))
    assert read_heartbeat_db(str(project), "watcher").status == "OLD-data"

    # Step 2: SQLite fails on NEW write → YAML crash dump has NEW-data
    with patch(
        "superharness.engine.watcher_heartbeat_dao.upsert",
        side_effect=Exception("simulated SQLite failure"),
    ):
        write_heartbeat(str(project), AgentHeartbeat(agent_id="watcher", runtime="native", status="NEW-data"))

    # Step 3: reader must return the FRESH crash-dump data, not stale SQLite
    result = read_heartbeat_db(str(project), "watcher")
    assert result is not None
    assert result.status == "NEW-data", (
        "C-DURABLE-READ violated: stale SQLite shadows fresh crash-dump YAML"
    )


def test_list_heartbeats_prefers_fresher_yaml(tmp_path: Path):
    """list_agent_heartbeats must return YAML when YAML is newer than SQLite row."""
    from superharness.engine.heartbeat_contract import (
        write_heartbeat, list_agent_heartbeats, AgentHeartbeat,
    )
    project = _make_project(tmp_path)
    write_heartbeat(str(project), AgentHeartbeat(agent_id="watcher", runtime="native", status="OLD-data"))
    with patch(
        "superharness.engine.watcher_heartbeat_dao.upsert",
        side_effect=Exception("sim sqlite fail"),
    ):
        write_heartbeat(str(project), AgentHeartbeat(agent_id="watcher", runtime="native", status="NEW-data"))

    listed = list_agent_heartbeats(str(project))
    watcher = next((h for h in listed if h.agent_id == "watcher"), None)
    assert watcher is not None
    assert watcher.status == "NEW-data", (
        "C-DURABLE-READ violated: list_agent_heartbeats shadows fresh YAML"
    )


def test_agent_status_read_prefers_fresher_yaml(tmp_path: Path):
    """read_agent_status returns fresher YAML when SQLite row is stale."""
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    project = _make_project(tmp_path)

    write_agent_status(project, runtime="claude-code", active_task="OLD")
    assert read_agent_status(project, runtime="claude-code").active_task == "OLD"

    with patch(
        "superharness.engine.agent_runtime_status_dao.upsert",
        side_effect=Exception("sim sqlite fail"),
    ):
        write_agent_status(project, runtime="claude-code", active_task="NEW")

    result = read_agent_status(project, runtime="claude-code")
    assert result is not None
    assert result.active_task == "NEW", (
        "C-DURABLE-READ violated: agent_status shadows fresh crash dump"
    )


def test_agent_pulse_read_prefers_fresher_yaml(tmp_path: Path, capsys):
    """_read_pulse returns fresher YAML when SQLite row is stale."""
    from superharness.commands.agent_pulse import _write_pulse, _read_pulse
    project = _make_project(tmp_path)

    _write_pulse(str(project), "T-OLD", "claude-code")
    with patch(
        "superharness.engine.agent_pulse_dao.upsert",
        side_effect=Exception("sim sqlite fail"),
    ):
        _write_pulse(str(project), "T-NEW", "claude-code")

    _read_pulse(str(project), stale_minutes=60)
    out = capsys.readouterr().out
    assert "T-NEW" in out, "C-DURABLE-READ violated: _read_pulse shadows fresh YAML"


def test_onboard_load_state_prefers_fresher_yaml(tmp_path: Path):
    """_load_state returns fresher YAML when SQLite row is stale."""
    import time
    from superharness.commands.onboard import _save_state, _load_state
    project = _make_project(tmp_path)
    sh = project / ".superharness"

    _save_state(sh, {"version": 1, "config_version": 1, "steps": {"detect": "completed"}})

    # Ensure mtime advance so YAML newer than SQLite updated_at
    time.sleep(1.1)

    with patch(
        "superharness.engine.onboarding_dao.upsert",
        side_effect=Exception("sim sqlite fail"),
    ):
        _save_state(sh, {"version": 1, "config_version": 1, "steps": {
            "detect": "completed", "init": "completed",
        }})

    loaded = _load_state(sh)
    assert loaded.get("steps", {}).get("init") == "completed", (
        "C-DURABLE-READ violated: _load_state shadows fresh YAML"
    )
