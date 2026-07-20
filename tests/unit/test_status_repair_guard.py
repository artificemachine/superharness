"""Iteration 3 — `shux status --fix` must not force-close discussions whose
agents it just confirmed alive.

Before this fix, `_repair_missing_agents` declared `repaired = []` and
returned it at the end of the function, but every branch inside only ever
appended to `report` — so the caller's `if repaired:` guard at the call site
in `main()` never fired, and every stuck discussion was force-closed
regardless of what the repair step found. In the 2026-07-20 audit this
printed "operator plist already loaded" immediately before closing the
discussion anyway.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from superharness.commands import status as status_mod
from superharness.commands.status import _repair_missing_agents
from superharness.engine.db import get_connection, init_db


# ---------------------------------------------------------------------------
# _repair_missing_agents — direct unit tests
# ---------------------------------------------------------------------------

def _write_operator_plist(home: Path, agent: str) -> None:
    la_dir = home / "Library" / "LaunchAgents"
    la_dir.mkdir(parents=True, exist_ok=True)
    label = f"com.superharness.operator.{agent}"
    (la_dir / f"{label}.plist").write_text(
        "<?xml version=\"1.0\"?><plist><dict><key>KeepAlive</key><true/></dict></plist>"
    )


class TestRepairMissingAgents:
    def test_repair_returns_agent_when_binary_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        _write_operator_plist(tmp_path, "claude-code")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/local/bin/{name}")

        with patch("superharness.engine.launchd_health.is_loaded", return_value=True):
            repaired, report = _repair_missing_agents("/fake/project", ["claude-code"])

        assert "claude-code" in repaired
        assert any("binary found" in line for line in report)

    def test_repair_omits_agent_when_binary_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: None)

        repaired, report = _repair_missing_agents("/fake/project", ["codex-cli"])

        assert "codex-cli" not in repaired
        assert any("NOT on PATH" in line for line in report)


# ---------------------------------------------------------------------------
# main() --fix caller branch — stubbed repair result
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path) -> Path:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    return tmp_path


def _make_stuck_discussion(project_dir: Path, disc_id: str, participants: list[str]) -> None:
    """Insert a discussion + inbox rows + heartbeats matching every condition
    `_detect_stuck_discussions` checks: active, all inbox items dispatched
    for >=2 agents, zero verdicts, and every participant's heartbeat missing
    or zombie."""
    conn = get_connection(str(project_dir))
    init_db(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO discussions (id, topic, owners, status, created_at) VALUES (?,?,?,?,?)",
        (disc_id, "test topic", json.dumps(participants), "active", now),
    )
    for i, agent in enumerate(participants):
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, created_at) VALUES (?,?,?,?,?)",
            (f"{disc_id}-inbox-{i}", f"{disc_id}/round-1", agent, "done", now),
        )
        conn.execute(
            "INSERT INTO agent_heartbeats (agent, status, updated_at, created_at) VALUES (?,?,?,?)",
            (agent, "zombie", now, now),
        )
    conn.commit()
    conn.close()


class TestFixCallerBranch:
    def test_fix_skips_close_when_agents_repaired(self, tmp_path, capsys):
        project_dir = _make_project(tmp_path)
        _make_stuck_discussion(project_dir, "disc-repaired", ["claude-code", "codex-cli"])

        with patch.object(
            status_mod, "_repair_missing_agents",
            return_value=(["claude-code", "codex-cli"], ["  ✅ claude-code: binary found (/x)"]),
        ):
            status_mod.main(["--project", str(project_dir), "--fix"])

        out = capsys.readouterr().out
        assert "Skipping discussion close" in out

        conn = get_connection(str(project_dir))
        init_db(conn)
        row = conn.execute("SELECT status FROM discussions WHERE id=?", ("disc-repaired",)).fetchone()
        conn.close()
        assert row["status"] == "active", "discussion must stay open when agents were repaired"

    def test_fix_closes_when_nothing_repaired(self, tmp_path, capsys):
        project_dir = _make_project(tmp_path)
        _make_stuck_discussion(project_dir, "disc-unrepaired", ["claude-code", "codex-cli"])

        with patch.object(
            status_mod, "_repair_missing_agents",
            return_value=([], ["  ❌ claude-code: binary NOT on PATH — install it first"]),
        ):
            status_mod.main(["--project", str(project_dir), "--fix"])

        out = capsys.readouterr().out
        assert "Skipping discussion close" not in out

        conn = get_connection(str(project_dir))
        init_db(conn)
        row = conn.execute("SELECT status FROM discussions WHERE id=?", ("disc-unrepaired",)).fetchone()
        conn.close()
        assert row["status"] == "failed_participant", "discussion must still force-close when nothing was repaired"
