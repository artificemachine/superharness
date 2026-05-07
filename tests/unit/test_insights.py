"""TDD: shux insights — task/dispatch/agent breakdown from SQLite."""
from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path


def _setup_db(tmp_path: Path) -> str:
    project_dir = str(tmp_path)
    sh = tmp_path / ".superharness"
    sh.mkdir()
    db = sh / "state.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE inbox (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, target_agent TEXT NOT NULL,
            status TEXT NOT NULL, retry_count INTEGER DEFAULT 0,
            failed_reason TEXT, created_at TEXT NOT NULL,
            launched_at TEXT, done_at TEXT
        );
        CREATE TABLE ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, agent TEXT,
            action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
        );
        INSERT INTO tasks VALUES ('t1','Task 1','claude-code','done','2026-01-01T00:00:00Z');
        INSERT INTO tasks VALUES ('t2','Task 2','codex-cli','done','2026-01-02T00:00:00Z');
        INSERT INTO tasks VALUES ('t3','Task 3','claude-code','failed','2026-01-03T00:00:00Z');
        INSERT INTO tasks VALUES ('t4','Task 4','claude-code','archived','2026-01-04T00:00:00Z');
        INSERT INTO inbox VALUES ('i1','t1','claude-code','done',0,NULL,'2026-01-01T00:00:00Z','2026-01-01T00:01:00Z','2026-01-01T00:10:00Z');
        INSERT INTO inbox VALUES ('i2','t2','codex-cli','done',1,NULL,'2026-01-02T00:00:00Z','2026-01-02T00:01:00Z','2026-01-02T00:15:00Z');
        INSERT INTO inbox VALUES ('i3','t3','claude-code','failed',3,'exit code 1','2026-01-03T00:00:00Z',NULL,NULL);
        INSERT INTO inbox VALUES ('i4','t1','claude-code','failed',2,'quota','2026-01-01T00:00:00Z',NULL,NULL);
        INSERT INTO ledger VALUES (1,'t1','claude-code','dispatch_launched',NULL,'2026-01-01T00:01:00Z');
        INSERT INTO ledger VALUES (2,'t2','codex-cli','dispatch_launched',NULL,'2026-01-02T00:01:00Z');
        INSERT INTO ledger VALUES (3,'t3','claude-code','dispatch_failed',NULL,'2026-01-03T00:01:00Z');
        INSERT INTO ledger VALUES (4,'t3','claude-code','dispatch_failed',NULL,'2026-01-03T00:02:00Z');
        INSERT INTO ledger VALUES (5,'t3','claude-code','dispatch_failed',NULL,'2026-01-03T00:03:00Z');
    """)
    conn.commit()
    conn.close()
    return project_dir


class TestInsightsModule:
    def test_returns_dict(self, tmp_path):
        from superharness.engine.insights import get_insights
        project_dir = _setup_db(tmp_path)
        result = get_insights(project_dir)
        assert isinstance(result, dict)

    def test_has_required_sections(self, tmp_path):
        from superharness.engine.insights import get_insights
        result = get_insights(_setup_db(tmp_path))
        for key in ("tasks", "agents", "dispatch", "failures"):
            assert key in result, f"missing section: {key}"

    def test_tasks_section_counts_by_status(self, tmp_path):
        from superharness.engine.insights import get_insights
        result = get_insights(_setup_db(tmp_path))
        tasks = result["tasks"]
        assert tasks["done"] == 2
        assert tasks["failed"] == 1
        assert tasks["archived"] == 1

    def test_agents_section_counts_done_by_agent(self, tmp_path):
        from superharness.engine.insights import get_insights
        result = get_insights(_setup_db(tmp_path))
        agents = result["agents"]
        assert agents["claude-code"]["done"] == 1
        assert agents["codex-cli"]["done"] == 1

    def test_dispatch_section_has_launch_and_fail_counts(self, tmp_path):
        from superharness.engine.insights import get_insights
        result = get_insights(_setup_db(tmp_path))
        d = result["dispatch"]
        assert d["launched"] == 2
        assert d["failed"] >= 3

    def test_failures_section_lists_most_retried(self, tmp_path):
        from superharness.engine.insights import get_insights
        result = get_insights(_setup_db(tmp_path))
        f = result["failures"]
        assert isinstance(f, list)
        assert len(f) > 0
        assert "task_id" in f[0]
        assert "retry_count" in f[0]

    def test_missing_db_returns_empty_sections(self, tmp_path):
        from superharness.engine.insights import get_insights
        (tmp_path / ".superharness").mkdir()
        result = get_insights(str(tmp_path))
        assert result["tasks"] == {}
        assert result["agents"] == {}


class TestInsightsCLI:
    def test_cli_runs_without_error(self, tmp_path, capsys):
        from superharness.commands.insights import main
        _setup_db(tmp_path)
        main(["--project", str(tmp_path)])
        out = capsys.readouterr().out
        assert "tasks" in out.lower() or "done" in out.lower()

    def test_json_flag_outputs_valid_json(self, tmp_path, capsys):
        import json
        from superharness.commands.insights import main
        _setup_db(tmp_path)
        main(["--project", str(tmp_path), "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "tasks" in data
