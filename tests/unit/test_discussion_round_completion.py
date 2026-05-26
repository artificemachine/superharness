"""Tests for round completion detection — DB + disk file scanning."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
import yaml


def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    return conn


class TestRoundCompletionDetection:

    def test_disk_files_counted_as_submitted(self, tmp_path):
        """Round YAML files on disk are counted even without DB submissions."""
        conn = _setup_db(tmp_path)
        disc_dir = tmp_path / ".superharness" / "discussions" / "disc-test"
        disc_dir.mkdir(parents=True)
        
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-test', 'test', '[\"claude-code\",\"codex-cli\",\"gemini-cli\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        conn.commit()

        # Write round files for 2 of 3 agents (enough for n-1=2)
        for agent in ["claude-code", "codex-cli"]:
            path = disc_dir / f"round-1-{agent}.yaml"
            path.write_text(yaml.dump({"discussion_id": "disc-test", "round": 1,
                                       "agent": agent, "verdict": "agree"}))

        # Simulate the consensus check logic
        from superharness.engine import discussions_dao
        rounds = discussions_dao.get_rounds(conn, "disc-test")
        verdicts = {}
        for r in rounds:
            verdicts[r.agent] = str(r.verdict or "").lower()

        disc = discussions_dao.get(conn, "disc-test")
        for agent in disc.owners:
            if agent not in verdicts:
                yaml_path = os.path.join(str(disc_dir), f"round-1-{agent}.yaml")
                if os.path.isfile(yaml_path):
                    verdicts[agent] = "file_on_disk"

        total = len(disc.owners)
        required = max(2, total - 1) if total > 1 else 2
        assert len(verdicts) >= required, f"Need {required}, have {len(verdicts)}"
        assert len(verdicts) == 2
        conn.close()

    def test_db_wins_over_disk(self, tmp_path):
        """DB submission takes priority over disk file."""
        conn = _setup_db(tmp_path)
        disc_dir = tmp_path / ".superharness" / "discussions" / "disc-db"
        disc_dir.mkdir(parents=True)

        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-db', 'test', '[\"claude-code\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        from superharness.engine import discussions_dao
        discussions_dao.add_round(conn, discussion_id="disc-db", round_number=1,
                                  agent="claude-code", verdict="agree",
                                  content="DB submission", now="2026-01-01T01:00:00Z")
        # Also write a disk file with different verdict
        path = disc_dir / "round-1-claude-code.yaml"
        path.write_text(yaml.dump({"verdict": "disagree"}))
        conn.commit()

        rounds = discussions_dao.get_rounds(conn, "disc-db")
        verdicts = {}
        for r in rounds:
            verdicts[r.agent] = str(r.verdict or "").lower()

        assert verdicts.get("claude-code") == "agree"  # DB wins
        conn.close()

    def test_no_disk_no_db_not_submitted(self, tmp_path):
        """Agent with no DB and no disk file is NOT counted."""
        conn = _setup_db(tmp_path)
        disc_dir = tmp_path / ".superharness" / "discussions" / "disc-none"
        disc_dir.mkdir(parents=True)

        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-none', 'test', '[\"claude-code\",\"codex-cli\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        conn.commit()

        # Only write file for claude-code
        path = disc_dir / "round-1-claude-code.yaml"
        path.write_text(yaml.dump({"verdict": "agree"}))

        from superharness.engine import discussions_dao
        disc = discussions_dao.get(conn, "disc-none")
        verdicts = {}
        for agent in disc.owners:
            yaml_path = os.path.join(str(disc_dir), f"round-1-{agent}.yaml")
            if os.path.isfile(yaml_path):
                verdicts[agent] = "file_on_disk"

        assert "claude-code" in verdicts
        assert "codex-cli" not in verdicts  # no disk file
        assert len(verdicts) == 1
        # 2 owners, n-1=1, 1 submitted → NOT enough (floor is 2)
        required = max(2, 2 - 1)
        assert required == 2
        assert len(verdicts) < required
        conn.close()
