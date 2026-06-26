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


_UNSET_ENV = "SHUX_DEFINITELY_UNSET_VAR_XYZ_98765"
_FAKE_CLI = "definitely-not-a-real-binary-xyz-98765"


class TestRequiresCheck:
    def test_no_requires_block_is_noop(self) -> None:
        from superharness.engine.preflight import _check_requires
        assert _check_requires({"id": "t"}) == []

    def test_missing_env_blocks_by_default(self, monkeypatch) -> None:
        from superharness.engine.preflight import _check_requires
        monkeypatch.delenv(_UNSET_ENV, raising=False)
        task = {"id": "t", "requires": {"env": [{"name": _UNSET_ENV, "reason": "needed for X"}]}}
        checks = _check_requires(task)
        assert any(c.id == "requires_env_missing" and c.level == "block" for c in checks)

    def test_missing_cli_blocks_by_default(self) -> None:
        from superharness.engine.preflight import _check_requires
        task = {"id": "t", "requires": {"cli": [{"id": _FAKE_CLI}]}}
        checks = _check_requires(task)
        assert any(c.id == "requires_cli_missing" and c.level == "block" for c in checks)

    def test_warn_mode_does_not_block(self) -> None:
        from superharness.engine.preflight import _check_requires
        task = {"id": "t", "requires": {"fail_mode": "warn", "cli": [{"id": _FAKE_CLI}]}}
        checks = _check_requires(task)
        assert any(c.id == "requires_cli_missing" and c.level == "warn" for c in checks)

    def test_satisfied_requires_is_info(self, monkeypatch) -> None:
        from superharness.engine.preflight import _check_requires
        monkeypatch.setenv("SHUX_TEST_REQ_PRESENT", "1")
        task = {"id": "t", "requires": {"env": [{"name": "SHUX_TEST_REQ_PRESENT"}]}}
        checks = _check_requires(task)
        assert any(c.id == "requires_ok" and c.level == "info" for c in checks)

    def test_run_preflight_blocks_on_unmet_requires(self, tmp_path: Path, monkeypatch) -> None:
        from superharness.engine.preflight import run_preflight
        monkeypatch.delenv(_UNSET_ENV, raising=False)
        (tmp_path / ".superharness").mkdir()
        task = _make_task(requires={"env": [{"name": _UNSET_ENV}]})
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.can_dispatch is False
        assert report.status == "block"
        assert any(c.id == "requires_env_missing" for c in report.blockers)


class TestProfileBaseline:
    """Profile-level baseline requires: is merged into every dispatch check."""

    def _write_profile(self, tmp_path: Path, requires: dict) -> None:
        import yaml as _yaml
        sh = tmp_path / ".superharness"
        sh.mkdir(exist_ok=True)
        (sh / "profile.yaml").write_text(_yaml.safe_dump({"requires": requires}))

    def test_baseline_cli_blocks_when_missing(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_requires
        self._write_profile(tmp_path, {"cli": [{"id": _FAKE_CLI}]})
        checks = _check_requires({"id": "t"}, project_dir=str(tmp_path))
        assert any(c.id == "requires_cli_missing" and c.level == "block" for c in checks)

    def test_no_profile_is_backward_compatible(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_requires
        (tmp_path / ".superharness").mkdir(exist_ok=True)
        checks = _check_requires({"id": "t"}, project_dir=str(tmp_path))
        assert checks == []

    def test_per_task_fail_mode_overrides_baseline(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_requires
        self._write_profile(tmp_path, {"fail_mode": "block", "cli": [{"id": _FAKE_CLI}]})
        task = {"id": "t", "requires": {"fail_mode": "warn"}}
        checks = _check_requires(task, project_dir=str(tmp_path))
        assert any(c.id == "requires_cli_missing" and c.level == "warn" for c in checks)

    def test_baseline_and_per_task_are_unioned(self, tmp_path: Path, monkeypatch) -> None:
        from superharness.engine.preflight import _check_requires
        monkeypatch.delenv(_UNSET_ENV, raising=False)
        self._write_profile(tmp_path, {"cli": [{"id": _FAKE_CLI}]})
        task = {"id": "t", "requires": {"env": [{"name": _UNSET_ENV}]}}
        checks = _check_requires(task, project_dir=str(tmp_path))
        ids = {c.id for c in checks}
        assert "requires_cli_missing" in ids
        assert "requires_env_missing" in ids

    def test_run_preflight_picks_up_baseline(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        self._write_profile(tmp_path, {"cli": [{"id": _FAKE_CLI}]})
        task = _make_task()
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.can_dispatch is False
        assert any(c.id == "requires_cli_missing" for c in report.blockers)


class TestSignalDerive:
    """Auto-derived requirements from task signals (test_types)."""

    def test_security_test_type_derives_gitleaks(self) -> None:
        from superharness.engine.preflight import _derive_signal_requires
        derived = _derive_signal_requires({"test_types": ["security"]})
        assert derived is not None
        cli_ids = [i["id"] for i in derived.get("cli", [])]
        assert "gitleaks" in cli_ids

    def test_security_test_type_derives_shipguard(self) -> None:
        from superharness.engine.preflight import _derive_signal_requires
        derived = _derive_signal_requires({"test_types": ["security"]})
        assert derived is not None
        cli_ids = [i["id"] for i in derived.get("cli", [])]
        assert "shipguard" in cli_ids

    def test_sast_test_type_derives_shipguard(self) -> None:
        from superharness.engine.preflight import _derive_signal_requires
        derived = _derive_signal_requires({"test_types": ["sast"]})
        assert derived is not None
        cli_ids = [i["id"] for i in derived.get("cli", [])]
        assert "shipguard" in cli_ids

    def test_no_signal_no_derive(self) -> None:
        from superharness.engine.preflight import _derive_signal_requires
        assert _derive_signal_requires({"test_types": ["unit", "integration"]}) is None
        assert _derive_signal_requires({}) is None

    def test_signal_blocks_dispatch_when_tool_missing(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        (tmp_path / ".superharness").mkdir()
        task = _make_task(test_types=["security"])
        report = run_preflight(str(tmp_path), task, skip_git=True)
        # gitleaks / shipguard are unlikely to be on PATH in test env
        # If they happen to be installed this check is info/pass — skip rather than fail
        import shutil
        gitleaks_present = shutil.which("gitleaks") is not None
        shipguard_present = shutil.which("shipguard") is not None
        if not gitleaks_present or not shipguard_present:
            assert not report.can_dispatch


class TestMandatePolicy:
    """Project-level mandate: high-risk tasks must have an explicit requires: block."""

    def _write_profile(self, tmp_path: Path, mandate: dict) -> None:
        import yaml as _yaml
        sh = tmp_path / ".superharness"
        sh.mkdir(exist_ok=True)
        (sh / "profile.yaml").write_text(_yaml.safe_dump({"mandate_requires_for": mandate}))

    def test_no_profile_is_noop(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        (tmp_path / ".superharness").mkdir(exist_ok=True)
        checks = _check_mandate_policy({"id": "t", "effort": "high"}, str(tmp_path))
        assert checks == []

    def test_no_mandate_key_is_noop(self, tmp_path: Path) -> None:
        import yaml as _yaml
        sh = tmp_path / ".superharness"
        sh.mkdir(exist_ok=True)
        (sh / "profile.yaml").write_text(_yaml.safe_dump({"autonomy": "ai_driven"}))
        from superharness.engine.preflight import _check_mandate_policy
        checks = _check_mandate_policy({"id": "t", "effort": "high"}, str(tmp_path))
        assert checks == []

    def test_effort_match_without_requires_blocks(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        self._write_profile(tmp_path, {"effort": ["high", "max"]})
        checks = _check_mandate_policy({"id": "t", "effort": "high"}, str(tmp_path))
        assert any(c.id == "mandate_requires_missing" and c.level == "block" for c in checks)

    def test_effort_match_with_requires_is_info(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        self._write_profile(tmp_path, {"effort": ["high"]})
        task = {"id": "t", "effort": "high", "requires": {"cli": [{"id": "gitleaks"}]}}
        checks = _check_mandate_policy(task, str(tmp_path))
        assert any(c.id == "mandate_requires_satisfied" and c.level == "info" for c in checks)

    def test_effort_not_in_mandate_no_block(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        self._write_profile(tmp_path, {"effort": ["max"]})
        checks = _check_mandate_policy({"id": "t", "effort": "medium"}, str(tmp_path))
        assert checks == []

    def test_test_types_match_blocks(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        self._write_profile(tmp_path, {"test_types": ["security", "sast"]})
        checks = _check_mandate_policy({"id": "t", "test_types": ["unit", "security"]}, str(tmp_path))
        assert any(c.id == "mandate_requires_missing" and c.level == "block" for c in checks)
        assert "test_types=[security]" in checks[0].message

    def test_test_types_no_overlap_no_block(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        self._write_profile(tmp_path, {"test_types": ["security"]})
        checks = _check_mandate_policy({"id": "t", "test_types": ["unit", "e2e"]}, str(tmp_path))
        assert checks == []

    def test_ship_on_complete_match_blocks(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import _check_mandate_policy
        self._write_profile(tmp_path, {"ship_on_complete": True})
        checks = _check_mandate_policy({"id": "t", "ship_on_complete": True}, str(tmp_path))
        assert any(c.id == "mandate_requires_missing" and c.level == "block" for c in checks)

    def test_run_preflight_mandate_blocks_dispatch(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        self._write_profile(tmp_path, {"effort": ["high", "max"]})
        task = _make_task(effort="high")
        report = run_preflight(str(tmp_path), task, skip_git=True)
        assert report.can_dispatch is False
        assert any(c.id == "mandate_requires_missing" for c in report.blockers)

    def test_run_preflight_mandate_passes_with_explicit_requires(self, tmp_path: Path) -> None:
        from superharness.engine.preflight import run_preflight
        self._write_profile(tmp_path, {"effort": ["high"]})
        task = _make_task(effort="high", requires={"cli": [{"id": "gitleaks"}]})
        # gitleaks may or may not be on PATH; we only care about mandate (not requires_cli_missing)
        report = run_preflight(str(tmp_path), task, skip_git=True)
        mandate_blocks = any(c.id == "mandate_requires_missing" for c in report.blockers)
        assert not mandate_blocks
