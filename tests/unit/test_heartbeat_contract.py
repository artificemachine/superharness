"""
Tests for heartbeat contract v1 — runtime-agnostic agent status schema.

Verifies:
  - Schema parsing and serialization
  - Stale detection
  - Per-agent heartbeat listing
  - Runtime-agnostic write/read (external runtimes)
  - Watcher writes structured heartbeat alongside legacy timestamp
  - Stale recovery consistent across runtimes
"""
from __future__ import annotations

import os
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT


def _import_contract():
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from superharness.engine import heartbeat_contract
    return heartbeat_contract


def _setup_project(tmp_path: Path) -> Path:
    (tmp_path / ".superharness").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Module exists
# ---------------------------------------------------------------------------

def test_heartbeat_contract_module_exists() -> None:
    module = REPO_ROOT / "src/superharness/engine/heartbeat_contract.py"
    assert module.exists(), f"heartbeat_contract.py not found at {module}"


# ---------------------------------------------------------------------------
# 2. Write and read round-trip
# ---------------------------------------------------------------------------

def test_write_and_read_heartbeat(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    hc = _import_contract()
    hb = hc.AgentHeartbeat(agent_id="watcher", runtime="native", status="idle")
    hc.write_heartbeat(str(project), hb)
    # SQLite is SoT — read via the SQLite-first API
    read_back = hc.read_heartbeat_db(str(project), "watcher")
    assert read_back is not None
    assert read_back.agent_id == "watcher"
    assert read_back.runtime == "native"
    assert read_back.status == "idle"


# ---------------------------------------------------------------------------
# 3. Required schema fields present after write
# ---------------------------------------------------------------------------

def test_heartbeat_required_fields(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    hc = _import_contract()
    hb = hc.AgentHeartbeat(agent_id="watcher", runtime="native")
    hc.write_heartbeat(str(project), hb)
    read_back = hc.read_heartbeat_db(str(project), "watcher")
    assert read_back is not None
    assert read_back.schema_version == "1"
    assert read_back.agent_id == "watcher"
    assert read_back.runtime == "native"
    assert read_back.written_at  # non-empty
    assert read_back.status in ("idle", "running", "dispatching", "stale")


# ---------------------------------------------------------------------------
# 4. Optional fields round-trip
# ---------------------------------------------------------------------------

def test_heartbeat_optional_fields_roundtrip(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    hc = _import_contract()
    budget = hc.AgentBudget(tokens_used=1234, tokens_limit=100000, cost_usd=0.05)
    hb = hc.AgentHeartbeat(
        agent_id="claude-code",
        runtime="codex-cli",
        pid=99999,
        status="running",
        active_task="feat.heartbeat-contract-v1",
        next_wake_at="2026-04-06T00:00:00Z",
        budget=budget,
    )
    hc.write_heartbeat(str(project), hb)
    read_back = hc.read_heartbeat_db(str(project), "claude-code")
    assert read_back is not None
    assert read_back.pid == 99999
    assert read_back.active_task == "feat.heartbeat-contract-v1"
    assert read_back.next_wake_at == "2026-04-06T00:00:00Z"
    assert read_back.budget is not None
    assert read_back.budget.tokens_used == 1234
    assert read_back.budget.cost_usd == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# 5. Stale heartbeat detection
# ---------------------------------------------------------------------------

def test_stale_heartbeat_detection(tmp_path: Path) -> None:
    hc = _import_contract()
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hb = hc.AgentHeartbeat(agent_id="watcher", written_at=old_ts)
    assert hc.is_stale(hb, stale_seconds=120) is True


# ---------------------------------------------------------------------------
# 6. Fresh heartbeat is not stale
# ---------------------------------------------------------------------------

def test_fresh_heartbeat_not_stale(tmp_path: Path) -> None:
    hc = _import_contract()
    hb = hc.AgentHeartbeat(agent_id="watcher")  # written_at = now
    assert hc.is_stale(hb, stale_seconds=120) is False


# ---------------------------------------------------------------------------
# 7. Missing / invalid heartbeat file → returns None
# ---------------------------------------------------------------------------

def test_missing_heartbeat_returns_none(tmp_path: Path) -> None:
    hc = _import_contract()
    result = hc.read_heartbeat(str(tmp_path / "nonexistent.heartbeat.yaml"))
    assert result is None


def test_invalid_heartbeat_returns_none(tmp_path: Path) -> None:
    hc = _import_contract()
    bad_file = tmp_path / "bad.heartbeat.yaml"
    bad_file.write_text("not: valid: yaml: [[[")
    result = hc.read_heartbeat(str(bad_file))
    assert result is None


# ---------------------------------------------------------------------------
# 8. list_agent_heartbeats
# ---------------------------------------------------------------------------

def test_list_agent_heartbeats(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    hc = _import_contract()
    hc.write_heartbeat(str(project), hc.AgentHeartbeat(agent_id="watcher", runtime="native"))
    hc.write_heartbeat(str(project), hc.AgentHeartbeat(agent_id="claude-code", runtime="native"))
    listed = hc.list_agent_heartbeats(str(project))
    agent_ids = [hb.agent_id for hb in listed]
    assert "watcher" in agent_ids
    assert "claude-code" in agent_ids


def test_list_agent_heartbeats_empty_project(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    hc = _import_contract()
    listed = hc.list_agent_heartbeats(str(project))
    assert listed == []


# ---------------------------------------------------------------------------
# 9. Runtime-agnostic: external runtime writes YAML, watcher reads it
# ---------------------------------------------------------------------------

def test_external_runtime_heartbeat_readable(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    hc = _import_contract()
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "external-agent.heartbeat.yaml").write_text(textwrap.dedent("""\
        schema_version: "1"
        agent_id: external-agent
        runtime: external
        status: running
        active_task: feat.some-task
        written_at: "2026-04-05T14:30:45Z"
    """))
    listed = hc.list_agent_heartbeats(str(project))
    ext = next((h for h in listed if h.agent_id == "external-agent"), None)
    assert ext is not None, "External agent heartbeat not found"
    assert ext.runtime == "external"
    assert ext.active_task == "feat.some-task"
    assert ext.status == "running"


# ---------------------------------------------------------------------------
# 10. age_seconds utility
# ---------------------------------------------------------------------------

def test_age_seconds_fresh(tmp_path: Path) -> None:
    hc = _import_contract()
    hb = hc.AgentHeartbeat(agent_id="watcher")
    age = hc.age_seconds(hb)
    assert 0 <= age < 5


def test_age_seconds_old(tmp_path: Path) -> None:
    hc = _import_contract()
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hb = hc.AgentHeartbeat(agent_id="watcher", written_at=old_ts)
    age = hc.age_seconds(hb)
    assert age >= 595


# ---------------------------------------------------------------------------
# 11. Watcher path is canonical (watcher.heartbeat.yaml, not in agents/)
# ---------------------------------------------------------------------------

def test_watcher_heartbeat_path(tmp_path: Path) -> None:
    hc = _import_contract()
    path = hc.heartbeat_path(str(tmp_path), "watcher")
    assert path.endswith("watcher.heartbeat.yaml")
    assert "agents" not in path


def test_agent_heartbeat_path(tmp_path: Path) -> None:
    hc = _import_contract()
    path = hc.heartbeat_path(str(tmp_path), "claude-code")
    assert "agents" in path
    assert path.endswith("claude-code.heartbeat.yaml")


# ---------------------------------------------------------------------------
# 12. Stale recovery consistent across all runtimes
# ---------------------------------------------------------------------------

def test_stale_recovery_consistent_across_runtimes() -> None:
    hc = _import_contract()
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for runtime in ("native", "codex-cli", "external", "custom-runtime"):
        hb = hc.AgentHeartbeat(agent_id="test-agent", runtime=runtime, written_at=old_ts)
        assert hc.is_stale(hb, stale_seconds=120) is True, f"Stale detection failed for runtime={runtime}"
    for runtime in ("native", "codex-cli", "external", "custom-runtime"):
        hb = hc.AgentHeartbeat(agent_id="test-agent", runtime=runtime)
        assert hc.is_stale(hb, stale_seconds=120) is False, f"Fresh heartbeat incorrectly stale for runtime={runtime}"


# ---------------------------------------------------------------------------
# 13. inbox_watch writes structured heartbeat alongside legacy timestamp
# ---------------------------------------------------------------------------

def test_inbox_watch_writes_structured_heartbeat(tmp_path: Path) -> None:
    """After _run_scripts, legacy timestamp file exists and SQLite has watcher heartbeat row."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from superharness.commands.inbox_watch import _run_scripts_heartbeat
    from superharness.engine.heartbeat_contract import read_heartbeat_db

    project = _setup_project(tmp_path)
    _run_scripts_heartbeat(str(project))

    legacy = project / ".superharness" / "watcher.heartbeat"
    assert legacy.exists(), "Legacy timestamp heartbeat not written"
    # SQLite is SoT — watcher heartbeat must be in SQLite, not YAML
    hb = read_heartbeat_db(str(project), "watcher")
    assert hb is not None, "Watcher heartbeat not in SQLite"
    assert hb.agent_id == "watcher"


# ---------------------------------------------------------------------------
# 14. status.py _heartbeat_status falls back to legacy when structured absent
# ---------------------------------------------------------------------------

def test_status_falls_back_to_legacy_heartbeat(tmp_path: Path) -> None:
    """_heartbeat_status returns ok when only legacy timestamp file exists."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from superharness.commands.status import _heartbeat_status

    project = _setup_project(tmp_path)
    # Write only legacy timestamp
    legacy = project / ".superharness" / "watcher.heartbeat"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    legacy.write_text(ts + "\n")

    level, detail = _heartbeat_status(str(project), str(project / ".superharness"))
    assert level == "ok", f"Expected ok with fresh legacy heartbeat, got {level}: {detail}"


def test_status_uses_structured_heartbeat_when_present(tmp_path: Path) -> None:
    """_heartbeat_status prefers structured YAML when both files exist."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from superharness.commands.status import _heartbeat_status
    from superharness.engine.heartbeat_contract import write_heartbeat, AgentHeartbeat

    project = _setup_project(tmp_path)
    hb = AgentHeartbeat(agent_id="watcher", runtime="native", status="idle")
    write_heartbeat(str(project), hb)

    level, detail = _heartbeat_status(str(project), str(project / ".superharness"))
    assert level == "ok", f"Expected ok with fresh structured heartbeat, got {level}: {detail}"


# ---------------------------------------------------------------------------
# 16. _heartbeat_status falls back to source project when worker heartbeat stale
# ---------------------------------------------------------------------------

def test_status_worker_stale_falls_back_to_source(tmp_path: Path) -> None:
    """When watcher.yaml points to a worker dir whose heartbeat is stale,
    _heartbeat_status must fall back to the source project heartbeat.

    Regression: shux operator start writes heartbeats to project_dir, not the
    worker directory, causing permanent false-positive stale reports for projects
    that were previously managed via the launchd watcher_worker path."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from superharness.commands.status import _heartbeat_status

    project = _setup_project(tmp_path)
    worker = tmp_path / "worker"
    (worker / ".superharness").mkdir(parents=True)

    (project / ".superharness" / "watcher.yaml").write_text(
        f'watcher_project: "{worker.as_posix()}"\ninterval_seconds: 30\n',
        encoding="utf-8",
    )
    # Worker heartbeat is weeks old (simulates abandoned launchd worker)
    (worker / ".superharness" / "watcher.heartbeat").write_text(
        "2026-01-01T00:00:00Z\n", encoding="utf-8"
    )
    # Operator wrote a fresh heartbeat to the source project
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / ".superharness" / "watcher.heartbeat").write_text(fresh + "\n", encoding="utf-8")

    level, detail = _heartbeat_status(str(project), str(project / ".superharness"))
    assert level == "ok", (
        f"Expected ok via source-project fallback, got {level}: {detail}"
    )
    assert "worker project" not in detail, (
        f"Source-project fallback must not carry worker-project label: {detail}"
    )
