"""Tests for agent-pulse command and AgentPulse schema (Phase 2)."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml

from superharness.engine.schemas import AgentPulse, TaskStatus
from superharness.commands.agent_pulse import (
    _write_pulse,
    _read_pulse,
    _clear_pulse,
    _age_seconds,
    _pulse_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    return project


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestAgentPulseSchema:
    def test_minimal_valid(self):
        p = AgentPulse(
            task_id="T-1",
            agent="claude-code",
            last_seen="2026-04-12T10:00:00Z",
        )
        assert p.task_id == "T-1"
        assert p.status == "running"
        assert p.message is None

    def test_full_fields(self):
        p = AgentPulse(
            task_id="T-2",
            agent="codex-cli",
            status="waiting_input",
            last_seen="2026-04-12T10:00:00Z",
            message="needs approval on schema change",
            pid=12345,
        )
        assert p.status == "waiting_input"
        assert p.pid == 12345
        assert p.message == "needs approval on schema change"

    def test_extra_fields_allowed(self):
        p = AgentPulse(
            task_id="T-3",
            agent="claude-code",
            last_seen="2026-04-12T10:00:00Z",
            custom_field="extra",
        )
        assert p.custom_field == "extra"  # type: ignore[attr-defined]


class TestTaskStatusPhase2:
    def test_waiting_input_in_enum(self):
        assert TaskStatus.waiting_input == "waiting_input"

    def test_paused_in_enum(self):
        assert TaskStatus.paused == "paused"

    def test_all_original_statuses_unchanged(self):
        for s in ("todo", "plan_proposed", "plan_approved", "in_progress",
                  "report_ready", "review_passed", "done", "failed", "blocked"):
            assert TaskStatus(s).value == s


# ---------------------------------------------------------------------------
# Write/read/clear tests
# ---------------------------------------------------------------------------


class TestWritePulse:
    def test_creates_pulse_in_sqlite(self, tmp_path):
        """SQLite is SoT — write_pulse creates a SQLite row."""
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        project = _make_project(tmp_path)
        _write_pulse(str(project), "T-10", "claude-code")
        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = agent_pulse_dao.get(conn, "claude-code")
        finally:
            conn.close()
        assert row is not None, "Expected SQLite row for claude-code"
        assert row.task_id == "T-10"

    def test_pulse_content_in_sqlite(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        project = _make_project(tmp_path)
        _write_pulse(str(project), "T-20", "codex-cli", status="waiting_input",
                     message="waiting on review")
        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = agent_pulse_dao.get(conn, "codex-cli")
        finally:
            conn.close()
        assert row is not None
        assert row.task_id == "T-20"
        assert row.agent == "codex-cli"
        assert row.status == "waiting_input"
        assert row.message == "waiting on review"
        assert row.last_seen
        assert row.pid is not None

    def test_overwrites_existing_pulse(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        project = _make_project(tmp_path)
        _write_pulse(str(project), "T-30", "claude-code")
        _write_pulse(str(project), "T-31", "claude-code")
        conn = get_connection(str(project))
        try:
            init_db(conn)
            row = agent_pulse_dao.get(conn, "claude-code")
        finally:
            conn.close()
        assert row is not None
        assert row.task_id == "T-31"


class TestReadPulse:
    def test_returns_0_when_no_file(self, tmp_path):
        project = _make_project(tmp_path)
        rc = _read_pulse(str(project))
        assert rc == 0

    def test_returns_0_for_fresh_pulse(self, tmp_path, capsys):
        project = _make_project(tmp_path)
        _write_pulse(str(project), "T-40", "claude-code")
        rc = _read_pulse(str(project), stale_minutes=10)
        assert rc == 0
        out = capsys.readouterr().out
        assert "T-40" in out
        assert "claude-code" in out

    def test_returns_2_for_stale_pulse(self, tmp_path, capsys):
        project = _make_project(tmp_path)
        # Write a pulse with a timestamp 20 minutes in the past
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        pulse_file = _pulse_path(str(project))
        pulse_file.write_text(yaml.dump({
            "task_id": "T-50",
            "agent": "claude-code",
            "status": "running",
            "last_seen": old_ts,
        }))
        rc = _read_pulse(str(project), stale_minutes=10)
        assert rc == 2
        out = capsys.readouterr().out
        assert "stale" in out.lower()


class TestClearPulse:
    def test_clear_removes_sqlite_row(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_pulse_dao
        project = _make_project(tmp_path)
        _write_pulse(str(project), "T-60", "claude-code")
        conn = get_connection(str(project))
        try:
            init_db(conn)
            assert agent_pulse_dao.get(conn, "claude-code") is not None
        finally:
            conn.close()
        _clear_pulse(str(project))
        conn = get_connection(str(project))
        try:
            init_db(conn)
            assert agent_pulse_dao.get(conn, "claude-code") is None
        finally:
            conn.close()

    def test_clear_no_op_when_absent(self, tmp_path):
        project = _make_project(tmp_path)
        _clear_pulse(str(project))  # should not raise


# ---------------------------------------------------------------------------
# Age calculation
# ---------------------------------------------------------------------------


class TestAgeSeconds:
    def test_fresh_timestamp(self):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        age = _age_seconds(ts)
        assert age < 5

    def test_old_timestamp(self):
        ts = "2020-01-01T00:00:00Z"
        age = _age_seconds(ts)
        assert age > 1_000_000

    def test_invalid_returns_inf(self):
        age = _age_seconds("not-a-date")
        assert age == float("inf")
