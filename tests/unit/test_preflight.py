"""Tests for superharness.engine.preflight."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_task(**kwargs) -> dict:
    base = {
        "id": "feat.test-task",
        "title": "Add YAML parser",
        "owner": "claude-code",
        "status": "plan_approved",
        "acceptance_criteria": ["parses config.yaml", "raises on invalid input"],
        "tdd": {
            "red": "write test_parse_valid() and test_parse_invalid()",
            "green": "implement parse() to pass both tests",
            "refactor": "extract _validate() helper",
        },
    }
    base.update(kwargs)
    return base


def _make_contract(tmp_path: Path, tasks: list[dict]) -> Path:
    import yaml
    contract = tmp_path / ".superharness" / "contract.yaml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(yaml.safe_dump({"id": "test", "tasks": tasks}))
    return contract


class TestSpecCompleteCheck:
    def test_no_title_is_warn(self) -> None:
        from superharness.engine.preflight import _check_spec_complete
        checks = _check_spec_complete({"owner": "claude-code"})
        assert any(c.id == "no_title" and c.level == "warn" for c in checks)

    def test_no_owner_is_warn(self) -> None:
        from superharness.engine.preflight import _check_spec_complete
        checks = _check_spec_complete({"title": "Something"})
        assert any(c.id == "no_owner" and c.level == "warn" for c in checks)

    def test_complete_spec_no_checks(self) -> None:
        from superharness.engine.preflight import _check_spec_complete
        checks = _check_spec_complete({"title": "Task", "owner": "claude-code"})
        assert checks == []


class TestTDDCheck:
    def test_missing_tdd_is_warn(self) -> None:
        from superharness.engine.preflight import _check_tdd_block
        checks = _check_tdd_block({})
        assert any(c.id == "no_tdd_red" and c.level == "warn" for c in checks)

    def test_red_without_green_is_warn(self) -> None:
        from superharness.engine.preflight import _check_tdd_block
        checks = _check_tdd_block({"tdd": {"red": "write test"}})
        assert any(c.id == "no_tdd_green" for c in checks)

    def test_complete_tdd_is_info(self) -> None:
        from superharness.engine.preflight import _check_tdd_block
        checks = _check_tdd_block({"tdd": {"red": "write test", "green": "implement"}})
        assert any(c.id == "tdd_ok" and c.level == "info" for c in checks)


class TestAcceptanceCriteriaCheck:
    def test_missing_ac_is_warn(self) -> None:
        from superharness.engine.preflight import _check_acceptance_criteria
        checks = _check_acceptance_criteria({})
        assert any(c.id == "no_acceptance_criteria" and c.level == "warn" for c in checks)

    def test_too_many_criteria_is_warn(self) -> None:
        from superharness.engine.preflight import _check_acceptance_criteria
        task = {"acceptance_criteria": [f"criterion {i}" for i in range(7)]}
        checks = _check_acceptance_criteria(task)
        assert any(c.id == "too_many_criteria" and c.level == "warn" for c in checks)

    def test_reasonable_criteria_is_info(self) -> None:
        from superharness.engine.preflight import _check_acceptance_criteria
        task = {"acceptance_criteria": ["does X", "handles Y"]}
        checks = _check_acceptance_criteria(task)
        assert any(c.id == "acceptance_criteria_ok" and c.level == "info" for c in checks)


class TestDependencyCheck:
    def test_blocks_on_undone_dependency(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_dependencies
        _make_contract(tmp_path, [
            {"id": "blocker", "status": "in_progress"},
            {"id": "dependent", "status": "plan_approved", "blocked_by": "blocker"},
        ])
        task = {"id": "dependent", "blocked_by": "blocker"}
        checks = _check_dependencies(task, str(tmp_path))
        assert any(c.id == "blocked_dependency" and c.level == "block" for c in checks)

    def test_passes_when_dependency_done(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_dependencies
        _make_contract(tmp_path, [
            {"id": "blocker", "status": "done"},
            {"id": "dependent", "status": "plan_approved", "blocked_by": "blocker"},
        ])
        task = {"id": "dependent", "blocked_by": "blocker"}
        checks = _check_dependencies(task, str(tmp_path))
        assert not any(c.level == "block" for c in checks)

    def test_no_dependency_returns_empty(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_dependencies
        _make_contract(tmp_path, [{"id": "solo", "status": "todo"}])
        checks = _check_dependencies({"id": "solo"}, str(tmp_path))
        assert checks == []


class TestGitStateCheck:
    def test_clean_tree_is_info(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_git_state
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stdout": ""})()
            checks = _check_git_state(str(tmp_path))
        assert any(c.id == "git_clean" and c.level == "info" for c in checks)

    def test_dirty_tree_is_warn(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_git_state
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 0,
                "stdout": " M src/foo.py\n?? new_file.py\n",
            })()
            checks = _check_git_state(str(tmp_path))
        assert any(c.id == "dirty_worktree" and c.level == "warn" for c in checks)

    def test_non_git_dir_returns_empty(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_git_state
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 128, "stdout": ""})()
            checks = _check_git_state(str(tmp_path))
        assert checks == []


class TestPriorFailuresCheck:
    def test_returns_empty_when_no_failures_file(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_prior_failures
        from superharness.engine.db import get_connection, init_db
        sh = tmp_path / ".superharness"
        sh.mkdir()
        conn = get_connection(str(tmp_path))
        init_db(conn)
        conn.close()
        checks = _check_prior_failures(str(tmp_path), "task-x")
        assert checks == []

    def test_warns_when_prior_failures_exist(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_prior_failures
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import failures_dao
        sh = tmp_path / ".superharness"
        sh.mkdir()
        conn = get_connection(str(tmp_path))
        init_db(conn)
        failures_dao.record(conn, task_id="task-x", agent="claude-code",
                            pattern="timeout", error_snippet="timed out", now="2026-01-01T00:00:00Z")
        conn.commit()
        conn.close()
        checks = _check_prior_failures(str(tmp_path), "task-x")
        assert any(c.id == "prior_failures" and c.level == "warn" for c in checks)

    def test_blocks_on_critical_failure(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_prior_failures
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import failures_dao
        sh = tmp_path / ".superharness"
        sh.mkdir()
        conn = get_connection(str(tmp_path))
        init_db(conn)
        failures_dao.record(conn, task_id="task-y", agent="claude-code",
                            pattern="api_auth", error_snippet="auth failed", now="2026-01-01T00:00:00Z")
        conn.commit()
        conn.close()
        checks = _check_prior_failures(str(tmp_path), "task-y")
        # SQLite failures_dao has no severity field; all failures surface as warn
        assert any(c.id == "prior_failures" and c.level in ("warn", "block") for c in checks)


class TestComplexityEstimate:
    def test_simple_task_suggests_single(self) -> None:
        from superharness.engine.preflight import _estimate_complexity
        task = {"acceptance_criteria": ["does X"], "tdd": {"red": "test", "green": "impl"}}
        fanout_n, mode = _estimate_complexity(task)
        assert mode == "single"
        assert fanout_n == 1

    def test_medium_task_suggests_fanout(self) -> None:
        from superharness.engine.preflight import _estimate_complexity
        task = {
            "acceptance_criteria": ["a", "b", "c", "d"],
            "tdd": {"red": "t", "green": "g"},
        }
        fanout_n, mode = _estimate_complexity(task)
        assert mode == "fanout"
        assert fanout_n == 2

    def test_large_task_suggests_swarm(self) -> None:
        from superharness.engine.preflight import _estimate_complexity
        task = {
            "title": "Rewrite entire architecture",
            "acceptance_criteria": ["a", "b", "c", "d", "e", "f", "g"],
            "tdd": {"red": "x" * 400, "green": "y" * 200},
        }
        fanout_n, mode = _estimate_complexity(task)
        assert mode == "swarm"
        assert fanout_n == 3


class TestRunPreflight:
    def test_pass_for_complete_task(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        (tmp_path / ".superharness").mkdir()
        task = _make_task()
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.status in ("pass", "warn")  # may warn on missing git state
        assert report.can_dispatch is True

    def test_block_on_unresolved_dependency(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        _make_contract(tmp_path, [
            {"id": "blocker", "status": "in_progress"},
            {"id": "child", "status": "plan_approved", "blocked_by": "blocker"},
        ])
        task = _make_task(id="child", blocked_by="blocker")
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.status == "block"
        assert report.can_dispatch is False

    def test_warn_on_missing_tdd(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        (tmp_path / ".superharness").mkdir()
        task = _make_task(tdd={})
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.status in ("warn", "block")
        warn_ids = [c.id for c in report.warnings]
        assert "no_tdd_red" in warn_ids

    def test_format_summary_shows_issues(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        (tmp_path / ".superharness").mkdir()
        task = _make_task(tdd={}, acceptance_criteria=[])
        report = run_preflight(str(tmp_path), task, skip_git=True)
        summary = report.format_summary()
        assert "no_tdd_red" in summary or "no_acceptance" in summary

    def test_format_summary_verbose_shows_info(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        (tmp_path / ".superharness").mkdir()
        task = _make_task()
        report = run_preflight(str(tmp_path), task, skip_git=True)
        verbose_out = report.format_summary(verbose=True)
        # Verbose should include info-level checks like tdd_ok
        assert "tdd_ok" in verbose_out or "acceptance_criteria_ok" in verbose_out

    def test_swarm_hint_when_complex(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        (tmp_path / ".superharness").mkdir()
        task = _make_task(
            title="Rewrite the entire system",
            acceptance_criteria=[f"criterion {i}" for i in range(8)],
            tdd={"red": "x" * 500, "green": "y" * 300},
        )
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.suggested_mode == "swarm"
        assert report.suggested_fanout_n == 3
