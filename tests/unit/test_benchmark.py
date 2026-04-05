"""Tests for superharness.engine.benchmark."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _setup(tmp_path: Path) -> str:
    (tmp_path / ".superharness").mkdir()
    return str(tmp_path)


class TestRecordDispatch:
    def test_creates_benchmark_jsonl(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import record_dispatch, _benchmark_path
        project = _setup(tmp_path)
        record_dispatch(project, "feat.task-a", "claude-code", "done", 12.5, cost_usd=0.05)
        path = _benchmark_path(project)
        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["task_id"] == "feat.task-a"
        assert rec["outcome"] == "done"
        assert rec["duration_seconds"] == 12.5
        assert rec["cost_usd"] == 0.05

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import record_dispatch, load_records
        project = _setup(tmp_path)
        record_dispatch(project, "feat.a", "claude-code", "done", 10.0)
        record_dispatch(project, "feat.b", "codex-cli", "failed", 5.0)
        record_dispatch(project, "feat.a", "claude-code", "done", 8.0)
        records = load_records(project)
        assert len(records) == 3

    def test_slot_fields_recorded(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import record_dispatch, load_records
        project = _setup(tmp_path)
        record_dispatch(project, "feat.fan", "parallel-dispatch", "done", 30.0,
                        cost_usd=0.10, slot_index=2, fanout_n=4)
        records = load_records(project)
        assert records[0]["slot_index"] == 2
        assert records[0]["fanout_n"] == 4


class TestLoadRecords:
    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import load_records
        project = _setup(tmp_path)
        (tmp_path / ".superharness" / "benchmark.jsonl").write_text("")
        assert load_records(project) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import load_records
        project = _setup(tmp_path)
        assert load_records(project) == []

    def test_skips_invalid_json_lines(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import load_records
        project = _setup(tmp_path)
        path = tmp_path / ".superharness" / "benchmark.jsonl"
        path.write_text('{"task_id": "a", "outcome": "done", "duration_seconds": 1.0, "cost_usd": 0, "agent": "claude-code", "timestamp": "", "model": "", "slot_index": -1, "fanout_n": 1}\n{bad json}\n')
        records = load_records(project)
        assert len(records) == 1


class TestAggregate:
    def _populate(self, project: str) -> None:
        from superharness.engine.benchmark import record_dispatch
        record_dispatch(project, "feat.a", "claude-code", "done", 10.0, 0.05)
        record_dispatch(project, "feat.a", "claude-code", "done", 8.0, 0.04)
        record_dispatch(project, "feat.a", "claude-code", "failed", 5.0, 0.02)
        record_dispatch(project, "feat.b", "codex-cli", "done", 20.0, 0.10)

    def test_groups_by_task_id(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import aggregate, load_records
        project = _setup(tmp_path)
        self._populate(project)
        stats = aggregate(load_records(project))
        task_ids = [s.task_id for s in stats]
        assert "feat.a" in task_ids
        assert "feat.b" in task_ids

    def test_counts_successes_and_failures(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import aggregate, load_records
        project = _setup(tmp_path)
        self._populate(project)
        stats = aggregate(load_records(project))
        a = next(s for s in stats if s.task_id == "feat.a")
        assert a.total_runs == 3
        assert a.successes == 2
        assert a.failures == 1

    def test_success_rate_calculated(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import aggregate, load_records
        project = _setup(tmp_path)
        self._populate(project)
        stats = aggregate(load_records(project))
        a = next(s for s in stats if s.task_id == "feat.a")
        assert abs(a.success_rate - 2/3) < 0.01

    def test_total_cost_summed(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import aggregate, load_records
        project = _setup(tmp_path)
        self._populate(project)
        stats = aggregate(load_records(project))
        a = next(s for s in stats if s.task_id == "feat.a")
        assert abs(a.total_cost_usd - 0.11) < 0.001

    def test_sorted_by_cost_desc(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import aggregate, load_records
        project = _setup(tmp_path)
        self._populate(project)
        stats = aggregate(load_records(project))
        # feat.a total = 0.11, feat.b total = 0.10 → feat.a first
        assert stats[0].task_id == "feat.a"


class TestLeaderboard:
    def test_respects_top_n(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import record_dispatch, leaderboard
        project = _setup(tmp_path)
        for i in range(10):
            record_dispatch(project, f"task-{i}", "claude-code", "done", float(i), float(i) * 0.01)
        board = leaderboard(project, top_n=3)
        assert len(board) == 3

    def test_empty_project_returns_empty(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import leaderboard
        project = _setup(tmp_path)
        assert leaderboard(project) == []


class TestFormatLeaderboard:
    def test_shows_header_and_separator(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import record_dispatch, leaderboard, format_leaderboard
        project = _setup(tmp_path)
        record_dispatch(project, "feat.x", "claude-code", "done", 15.0, 0.07)
        board = leaderboard(project)
        output = format_leaderboard(board)
        assert "Task ID" in output
        assert "feat.x" in output
        assert "$" in output

    def test_show_agents_includes_agent_names(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import record_dispatch, leaderboard, format_leaderboard
        project = _setup(tmp_path)
        record_dispatch(project, "feat.x", "claude-code", "done", 10.0, 0.05)
        record_dispatch(project, "feat.x", "codex-cli", "done", 8.0, 0.03)
        board = leaderboard(project)
        output = format_leaderboard(board, show_agents=True)
        assert "claude-code" in output
        assert "codex-cli" in output

    def test_empty_shows_no_records_message(self, tmp_path: Path) -> None:
        from superharness.engine.benchmark import format_leaderboard
        output = format_leaderboard([])
        assert "No benchmark records" in output
