"""
Tests for superharness.engine.agent_status — heartbeat contract v1.

Covers:
- Schema: AgentStatusRecord field validation, liveness enum, optional fields
- write_agent_status(): creates .superharness/agents/<runtime>.status.yaml
- read_agent_status(): parses file back, returns None when missing
- is_status_stale(): detects stale records by updated_at age
- read_all_agent_statuses(): returns dict of all runtimes without hardcoding names
- External (non-native) runtimes round-trip identically to native runtimes
- list_stale_agents(): returns list of stale runtime names
- Stale agent detection consistent across native and external runtimes
- Watcher and monitor consume heartbeat data without runtime-specific branches
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_utc(seconds_ago: int) -> str:
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup_project(tmp_path: Path) -> Path:
    """Minimal .superharness layout."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Module and class exist
# ---------------------------------------------------------------------------

def test_agent_status_module_exists() -> None:
    from tests.helpers import REPO_ROOT
    module = REPO_ROOT / "src/superharness/engine/agent_status.py"
    assert module.exists(), f"engine/agent_status.py not found at {module}"


def test_agent_status_record_class_importable() -> None:
    from superharness.engine.agent_status import AgentStatusRecord
    assert AgentStatusRecord is not None


def test_write_agent_status_importable() -> None:
    from superharness.engine.agent_status import write_agent_status
    assert callable(write_agent_status)


def test_read_agent_status_importable() -> None:
    from superharness.engine.agent_status import read_agent_status
    assert callable(read_agent_status)


def test_is_status_stale_importable() -> None:
    from superharness.engine.agent_status import is_status_stale
    assert callable(is_status_stale)


def test_read_all_agent_statuses_importable() -> None:
    from superharness.engine.agent_status import read_all_agent_statuses
    assert callable(read_all_agent_statuses)


def test_list_stale_agents_importable() -> None:
    from superharness.engine.agent_status import list_stale_agents
    assert callable(list_stale_agents)


# ---------------------------------------------------------------------------
# 2. AgentStatusRecord schema
# ---------------------------------------------------------------------------

def test_agent_status_record_required_fields() -> None:
    """runtime and updated_at are required."""
    from superharness.engine.agent_status import AgentStatusRecord
    r = AgentStatusRecord(runtime="claude-code", updated_at=_now_utc())
    assert r.runtime == "claude-code"
    assert r.updated_at is not None


def test_agent_status_record_schema_version_default() -> None:
    """schema_version defaults to '1'."""
    from superharness.engine.agent_status import AgentStatusRecord
    r = AgentStatusRecord(runtime="claude-code", updated_at=_now_utc())
    assert r.schema_version == "1"


def test_agent_status_record_liveness_default() -> None:
    """liveness defaults to 'active'."""
    from superharness.engine.agent_status import AgentStatusRecord
    r = AgentStatusRecord(runtime="claude-code", updated_at=_now_utc())
    assert r.liveness == "active"


def test_agent_status_record_optional_fields_none() -> None:
    """active_task, next_wake_at, budget are None by default."""
    from superharness.engine.agent_status import AgentStatusRecord
    r = AgentStatusRecord(runtime="claude-code", updated_at=_now_utc())
    assert r.active_task is None
    assert r.next_wake_at is None
    assert r.budget is None


def test_agent_status_record_all_fields() -> None:
    """All fields can be populated."""
    from superharness.engine.agent_status import AgentStatusRecord
    r = AgentStatusRecord(
        runtime="codex-cli",
        updated_at=_now_utc(),
        liveness="idle",
        active_task="feat.some-task",
        next_wake_at="2026-04-05T12:00:00Z",
        budget={
            "model": "claude-sonnet-4-6",
            "input_tokens": 5000,
            "output_tokens": 1200,
            "cost_usd": 0.033,
            "max_budget_usd": 2.0,
        },
    )
    assert r.runtime == "codex-cli"
    assert r.liveness == "idle"
    assert r.active_task == "feat.some-task"
    assert r.next_wake_at == "2026-04-05T12:00:00Z"
    assert r.budget["cost_usd"] == 0.033


def test_agent_status_record_valid_liveness_values() -> None:
    """All valid liveness values are accepted."""
    from superharness.engine.agent_status import AgentStatusRecord
    for liveness in ("active", "idle", "stopping", "dead"):
        r = AgentStatusRecord(runtime="test", updated_at=_now_utc(), liveness=liveness)
        assert r.liveness == liveness


# ---------------------------------------------------------------------------
# 3. write_agent_status — creates .superharness/agents/<runtime>.status.yaml
# ---------------------------------------------------------------------------

def test_write_agent_status_creates_sqlite_row(tmp_path: Path) -> None:
    """SQLite is SoT — write_agent_status creates SQLite row, not YAML file."""
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    write_agent_status(project, runtime="claude-code")
    record = read_agent_status(project, runtime="claude-code")
    assert record is not None, "Expected SQLite row for claude-code"
    assert record.runtime == "claude-code"


def test_write_agent_status_creates_agents_dir(tmp_path: Path) -> None:
    """write_agent_status writes to SQLite — agents/ dir creation is incidental in dual mode."""
    import os as _os
    project = _setup_project(tmp_path)
    monkey_env = _os.environ.get("STATE_BACKEND")
    _os.environ["STATE_BACKEND"] = "dual"
    try:
        from superharness.engine.agent_status import write_agent_status
        write_agent_status(project, runtime="claude-code")
        agents_dir = project / ".superharness" / "agents"
        assert agents_dir.exists()
    finally:
        if monkey_env is None:
            _os.environ.pop("STATE_BACKEND", None)
        else:
            _os.environ["STATE_BACKEND"] = monkey_env


def test_write_agent_status_required_keys_sqlite(tmp_path: Path) -> None:
    """SQLite row has schema_version, runtime, updated_at, liveness, active_task."""
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    write_agent_status(project, runtime="claude-code", active_task="feat.test")
    record = read_agent_status(project, runtime="claude-code")
    assert record is not None
    assert record.schema_version == "1"
    assert record.runtime == "claude-code"
    assert record.updated_at
    assert record.liveness == "active"
    assert record.active_task == "feat.test"


def test_write_agent_status_external_runtime(tmp_path: Path) -> None:
    """External/non-native runtimes use the same write path (SQLite)."""
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    write_agent_status(project, runtime="my-custom-bot")
    record = read_agent_status(project, runtime="my-custom-bot")
    assert record is not None
    assert record.runtime == "my-custom-bot"


def test_write_agent_status_with_budget(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    budget = {"model": "claude-sonnet-4-6", "input_tokens": 1000, "output_tokens": 500,
               "cost_usd": 0.01, "max_budget_usd": 5.0}
    write_agent_status(project, runtime="claude-code", budget=budget)
    record = read_agent_status(project, runtime="claude-code")
    assert record is not None
    assert record.budget is not None
    assert record.budget.get("model") == "claude-sonnet-4-6"
    assert record.budget.get("cost_usd") == 0.01


# ---------------------------------------------------------------------------
# 4. read_agent_status — parses file back
# ---------------------------------------------------------------------------

def test_read_agent_status_returns_none_when_missing(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import read_agent_status
    result = read_agent_status(project, runtime="claude-code")
    assert result is None


def test_read_agent_status_round_trip(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    write_agent_status(project, runtime="claude-code",
                       liveness="idle", active_task="feat.abc")
    result = read_agent_status(project, runtime="claude-code")
    assert result is not None
    assert result.runtime == "claude-code"
    assert result.liveness == "idle"
    assert result.active_task == "feat.abc"


def test_read_agent_status_external_runtime(tmp_path: Path) -> None:
    """External runtimes are parsed identically to native runtimes."""
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_agent_status
    write_agent_status(project, runtime="external-bot",
                       liveness="active", active_task="feat.xyz")
    result = read_agent_status(project, runtime="external-bot")
    assert result is not None
    assert result.runtime == "external-bot"
    assert result.active_task == "feat.xyz"


def test_read_agent_status_bad_yaml_returns_none(tmp_path: Path) -> None:
    """Corrupt status file returns None rather than raising."""
    project = _setup_project(tmp_path)
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir()
    (agents_dir / "bad-agent.status.yaml").write_text("{{bad yaml: ][", encoding="utf-8")
    from superharness.engine.agent_status import read_agent_status
    result = read_agent_status(project, runtime="bad-agent")
    assert result is None


# ---------------------------------------------------------------------------
# 5. is_status_stale — staleness detection
# ---------------------------------------------------------------------------

def test_is_status_stale_fresh_record(tmp_path: Path) -> None:
    """A record with updated_at=now is not stale."""
    from superharness.engine.agent_status import AgentStatusRecord, is_status_stale
    r = AgentStatusRecord(runtime="claude-code", updated_at=_now_utc())
    assert not is_status_stale(r, stale_seconds=120)


def test_is_status_stale_old_record(tmp_path: Path) -> None:
    """A record with updated_at 5 minutes ago is stale with 120s threshold."""
    from superharness.engine.agent_status import AgentStatusRecord, is_status_stale
    r = AgentStatusRecord(runtime="claude-code", updated_at=_past_utc(300))
    assert is_status_stale(r, stale_seconds=120)


def test_is_status_stale_boundary(tmp_path: Path) -> None:
    """A record exactly at the stale_seconds boundary is considered stale."""
    from superharness.engine.agent_status import AgentStatusRecord, is_status_stale
    r = AgentStatusRecord(runtime="claude-code", updated_at=_past_utc(120))
    assert is_status_stale(r, stale_seconds=120)


def test_is_status_stale_external_runtime_same_behavior(tmp_path: Path) -> None:
    """External runtimes use identical stale detection logic as native."""
    from superharness.engine.agent_status import AgentStatusRecord, is_status_stale
    old = AgentStatusRecord(runtime="my-external-bot", updated_at=_past_utc(300))
    fresh = AgentStatusRecord(runtime="my-external-bot", updated_at=_now_utc())
    assert is_status_stale(old, stale_seconds=120)
    assert not is_status_stale(fresh, stale_seconds=120)


def test_is_status_stale_unparseable_timestamp() -> None:
    """If updated_at is unparseable, record is treated as stale."""
    from superharness.engine.agent_status import AgentStatusRecord, is_status_stale
    r = AgentStatusRecord(runtime="test", updated_at="not-a-timestamp")
    assert is_status_stale(r, stale_seconds=120)


# ---------------------------------------------------------------------------
# 6. read_all_agent_statuses — reads all runtimes without hardcoding names
# ---------------------------------------------------------------------------

def test_read_all_agent_statuses_empty_when_no_dir(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import read_all_agent_statuses
    result = read_all_agent_statuses(project)
    assert result == {}


def test_read_all_agent_statuses_returns_all(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_all_agent_statuses
    write_agent_status(project, runtime="claude-code")
    write_agent_status(project, runtime="codex-cli")
    write_agent_status(project, runtime="my-external-bot")
    result = read_all_agent_statuses(project)
    assert "claude-code" in result
    assert "codex-cli" in result
    assert "my-external-bot" in result
    assert len(result) == 3


def test_read_all_agent_statuses_no_hardcoded_runtimes(tmp_path: Path) -> None:
    """read_all_agent_statuses discovers runtimes dynamically, not by name."""
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, read_all_agent_statuses
    # Write an unusual runtime name
    write_agent_status(project, runtime="gemini-pro-agent")
    result = read_all_agent_statuses(project)
    assert "gemini-pro-agent" in result
    assert result["gemini-pro-agent"].runtime == "gemini-pro-agent"


def test_read_all_skips_invalid_files(tmp_path: Path) -> None:
    """read_all_agent_statuses skips corrupt files without failing."""
    project = _setup_project(tmp_path)
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir()
    (agents_dir / "bad.status.yaml").write_text("{{not: valid yaml", encoding="utf-8")
    from superharness.engine.agent_status import write_agent_status, read_all_agent_statuses
    write_agent_status(project, runtime="claude-code")
    result = read_all_agent_statuses(project)
    assert "claude-code" in result
    assert "bad" not in result  # bad file skipped


# ---------------------------------------------------------------------------
# 7. list_stale_agents — returns list of stale runtime names
# ---------------------------------------------------------------------------

def test_list_stale_agents_empty_when_none_stale(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    from superharness.engine.agent_status import write_agent_status, list_stale_agents
    write_agent_status(project, runtime="claude-code")
    stale = list_stale_agents(project, stale_seconds=120)
    assert stale == []


def test_list_stale_agents_finds_stale(tmp_path: Path) -> None:
    """Manually write a stale status file; list_stale_agents returns it."""
    project = _setup_project(tmp_path)
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir()
    stale_record = {
        "schema_version": "1",
        "runtime": "old-bot",
        "updated_at": _past_utc(600),
        "liveness": "active",
        "active_task": None,
        "next_wake_at": None,
        "budget": None,
    }
    (agents_dir / "old-bot.status.yaml").write_text(
        yaml.dump(stale_record, default_flow_style=False), encoding="utf-8"
    )
    from superharness.engine.agent_status import list_stale_agents
    stale = list_stale_agents(project, stale_seconds=120)
    assert "old-bot" in stale


def test_list_stale_agents_consistent_native_and_external(tmp_path: Path) -> None:
    """Stale detection is identical for native and external runtimes."""
    project = _setup_project(tmp_path)
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir()

    for runtime in ("claude-code", "codex-cli", "my-external-bot"):
        record = {
            "schema_version": "1",
            "runtime": runtime,
            "updated_at": _past_utc(600),
            "liveness": "active",
            "active_task": None,
            "next_wake_at": None,
            "budget": None,
        }
        (agents_dir / f"{runtime}.status.yaml").write_text(
            yaml.dump(record, default_flow_style=False), encoding="utf-8"
        )

    from superharness.engine.agent_status import list_stale_agents
    stale = list_stale_agents(project, stale_seconds=120)
    assert set(stale) == {"claude-code", "codex-cli", "my-external-bot"}


# ---------------------------------------------------------------------------
# 8. Watcher integration: _heartbeat_age_seconds still works (compat)
# ---------------------------------------------------------------------------

def test_watcher_heartbeat_file_still_compatible(tmp_path: Path) -> None:
    """The legacy watcher.heartbeat plain-text file is still read correctly."""
    from superharness.commands.inbox_watch import _heartbeat_age_seconds
    project = _setup_project(tmp_path)
    hb_file = project / ".superharness" / "watcher.heartbeat"
    hb_file.write_text(_now_utc() + "\n", encoding="utf-8")
    age = _heartbeat_age_seconds(str(project))
    assert age is not None
    assert age < 5  # should be very fresh


def test_watcher_heartbeat_stale_detected(tmp_path: Path) -> None:
    """Stale watcher.heartbeat detected by _heartbeat_age_seconds."""
    from superharness.commands.inbox_watch import _heartbeat_age_seconds
    project = _setup_project(tmp_path)
    hb_file = project / ".superharness" / "watcher.heartbeat"
    hb_file.write_text(_past_utc(300) + "\n", encoding="utf-8")
    age = _heartbeat_age_seconds(str(project))
    assert age is not None
    assert age >= 300


# ---------------------------------------------------------------------------
# 9. Monitor-layer status projection: no runtime-specific branches
# ---------------------------------------------------------------------------

def test_agent_status_health_no_hardcoded_runtimes(tmp_path: Path) -> None:
    """agent_status_health returns status for any runtime without hardcoding names."""
    from superharness.engine.agent_status import write_agent_status, agent_status_health
    project = _setup_project(tmp_path)
    write_agent_status(project, runtime="my-custom-runtime", active_task="feat.test")
    result = agent_status_health(project, stale_seconds=120)
    assert isinstance(result, dict)
    assert "agents" in result
    assert "my-custom-runtime" in result["agents"]


def test_agent_status_health_marks_stale_agents(tmp_path: Path) -> None:
    """agent_status_health marks stale agents with level='warn'."""
    from superharness.engine.agent_status import agent_status_health
    project = _setup_project(tmp_path)
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir()
    stale_record = {
        "schema_version": "1",
        "runtime": "stale-bot",
        "updated_at": _past_utc(600),
        "liveness": "active",
        "active_task": None,
        "next_wake_at": None,
        "budget": None,
    }
    (agents_dir / "stale-bot.status.yaml").write_text(
        yaml.dump(stale_record, default_flow_style=False), encoding="utf-8"
    )
    result = agent_status_health(project, stale_seconds=120)
    assert result["agents"]["stale-bot"]["level"] == "warn"


def test_agent_status_health_marks_fresh_agents_ok(tmp_path: Path) -> None:
    """agent_status_health marks fresh agents with level='ok'."""
    from superharness.engine.agent_status import write_agent_status, agent_status_health
    project = _setup_project(tmp_path)
    write_agent_status(project, runtime="fresh-bot")
    result = agent_status_health(project, stale_seconds=120)
    assert result["agents"]["fresh-bot"]["level"] == "ok"


def test_agent_status_health_empty_when_no_agents(tmp_path: Path) -> None:
    """agent_status_health returns empty agents dict when nothing written."""
    from superharness.engine.agent_status import agent_status_health
    project = _setup_project(tmp_path)
    result = agent_status_health(project, stale_seconds=120)
    assert result["agents"] == {}


# ---------------------------------------------------------------------------
# 10. Status file template exists in protocol/templates/
# ---------------------------------------------------------------------------

def test_agent_status_template_exists() -> None:
    from tests.helpers import REPO_ROOT
    template = REPO_ROOT / "protocol/templates/agent-status.yaml"
    assert template.exists(), f"protocol/templates/agent-status.yaml not found at {template}"


def test_agent_status_template_has_required_keys() -> None:
    from tests.helpers import REPO_ROOT
    template = REPO_ROOT / "protocol/templates/agent-status.yaml"
    data = yaml.safe_load(template.read_text(encoding="utf-8"))
    for key in ("schema_version", "runtime", "updated_at", "liveness"):
        assert key in data, f"agent-status.yaml template missing key: {key}"
