"""Tests for orchestrator mode in delegate command.

When --orchestrate is passed, delegate uses Opus to decompose the task,
then writes subtasks to contract.yaml and dispatches sub-agents.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from superharness.engine.orchestrator import RoutingPlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal .superharness project structure."""
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()

    contract = {
        "id": "C-001",
        "created": "2026-01-01",
        "created_by": "owner",
        "status": "active",
        "tasks": [
            {
                "id": "T-42",
                "title": "Add rate limiting to API",
                "owner": "claude-code",
                "status": "plan_approved",
                "project_path": str(tmp_path),
                "acceptance_criteria": [
                    "Rate limiter rejects >100 req/min per IP",
                    "Redis backend for counters",
                ],
            }
        ],
    }
    with open(harness / "contract.yaml", "w") as f:
        yaml.safe_dump(contract, f)

    profile = {
        "project_name": "test",
        "created": "2026-01-01",
        "autonomy": "autonomous",
        "primary_agent": "claude-code",
        "stack": "python",
    }
    with open(harness / "profile.yaml", "w") as f:
        yaml.safe_dump(profile, f)

    (harness / "ledger.md").write_text("# Ledger\n")

    return tmp_path


MOCK_ROUTING = RoutingPlan(
    owner="claude-code",
    tier="standard",
    effort="medium",
    decompose=True,
    rationale="cross-cutting feature with multiple concerns",
    subtasks=[
        {
            "id": "T-42.1",
            "title": "Write rate limiter middleware",
            "owner": "codex-cli",
            "model_tier": "standard",
            "effort": "medium",
            "estimated_tokens": 45000,
        },
        {
            "id": "T-42.2",
            "title": "Add Redis backend",
            "owner": "claude-code",
            "model_tier": "mini",
            "effort": "low",
            "estimated_tokens": 12000,
        },
    ],
    total_estimated_cost_usd=0.30,
    recommended_budget_usd=2.00,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecordDecomposition:
    def test_subtasks_written_to_sqlite(self, tmp_path):
        from superharness.commands.delegate import _record_decomposition
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        _record_decomposition(str(project), "T-42", MOCK_ROUTING)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            # 1. Verify separate rows
            row1 = tasks_dao.get(conn, "T-42.1")
            row2 = tasks_dao.get(conn, "T-42.2")
            assert row1.title == "Write rate limiter middleware"
            assert row1.parent_id == "T-42"
            assert row2.title == "Add Redis backend"
            assert row2.parent_id == "T-42"

            # 2. Verify parent extras_json
            parent = tasks_dao.get(conn, "T-42")
            import json

            extras = json.loads(parent.extras_json)
            assert "subtasks" in extras
            assert len(extras["subtasks"]) == 2
            assert extras["budget_usd"] == pytest.approx(2.00, abs=0.01)
        finally:
            conn.close()

    def test_cost_fields_persisted(self, tmp_path):
        from superharness.commands.delegate import _record_decomposition
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        _record_decomposition(str(project), "T-42", MOCK_ROUTING)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            parent = tasks_dao.get(conn, "T-42")
            import json

            extras = json.loads(parent.extras_json)
            assert extras["estimated_cost_usd"] == pytest.approx(0.30, abs=0.01)
            assert extras["budget_usd"] == pytest.approx(2.00, abs=0.01)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Orchestrate mode in delegate
# ---------------------------------------------------------------------------


class TestOrchestrateMode:
    def test_orchestrate_flag_triggers_decomposition(self, tmp_path):
        """--orchestrate causes delegate to decompose before dispatch."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.engine.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.route.return_value = MOCK_ROUTING

            with patch("superharness.commands.delegate._launch_agent"):
                with patch(
                    "superharness.commands.delegate.sdk_available", return_value=False
                ):
                    rc = delegate(
                        project_dir=str(project),
                        target="claude-code",
                        task_id="T-42",
                        print_only=True,
                        non_interactive=False,
                        codex_bypass=False,
                        orchestrate=True,
                        no_auto_model=True,
                    )

            mock_instance.route.assert_called_once()
            assert rc == 0

    def test_orchestrate_prints_cost_summary(self, tmp_path, capsys):
        """--orchestrate prints decomposition and cost before dispatch."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.engine.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.route.return_value = MOCK_ROUTING

            with patch("superharness.commands.delegate._launch_agent"):
                with patch(
                    "superharness.commands.delegate.sdk_available", return_value=False
                ):
                    delegate(
                        project_dir=str(project),
                        target="claude-code",
                        task_id="T-42",
                        print_only=True,
                        non_interactive=False,
                        codex_bypass=False,
                        orchestrate=True,
                        no_auto_model=True,
                    )

        captured = capsys.readouterr()
        assert "T-42.1" in captured.out
        assert "T-42.2" in captured.out

    def test_orchestrate_works_for_codex_cli(self, tmp_path):
        """--orchestrate now works for codex-cli, not just claude-code."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.engine.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.route.return_value = MOCK_ROUTING

            with patch("superharness.commands.delegate._launch_agent"):
                with patch(
                    "superharness.commands.delegate.sdk_available", return_value=False
                ):
                    rc = delegate(
                        project_dir=str(project),
                        target="codex-cli",
                        task_id="T-42",
                        print_only=True,
                        non_interactive=False,
                        codex_bypass=False,
                        orchestrate=True,
                        no_auto_model=True,
                    )

        mock_instance.route.assert_called_once()
        # owner in task_data should reflect the actual target
        call_args = mock_instance.route.call_args[0][0]
        assert call_args["owner"] == "codex-cli"
        assert rc == 0


# ---------------------------------------------------------------------------
# F-02: --no-orchestrate must be honored on the non-JSON CLI path
# ---------------------------------------------------------------------------


class TestNoOrchestrateFlagNonJsonPath:
    def test_no_orchestrate_skips_orchestrator_via_main(self, tmp_path):
        """`shux delegate --no-orchestrate` (non-JSON CLI entry) must not
        invoke the Orchestrator at all. Previously the non-JSON call site
        omitted `no_orchestrate=opts.no_orchestrate` when calling
        `delegate(...)`, so the flag was silently ignored."""
        from superharness.commands.delegate import main as delegate_main
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.engine.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.route.return_value = MOCK_ROUTING

            with patch("superharness.commands.delegate._launch_agent"):
                with patch(
                    "superharness.commands.delegate.sdk_available",
                    return_value=False,
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        delegate_main(
                            [
                                "--to",
                                "claude-code",
                                "--task",
                                "T-42",
                                "--project",
                                str(project),
                                "--no-orchestrate",
                            ]
                        )

        assert exc_info.value.code == 0
        mock_instance.route.assert_not_called()


# ---------------------------------------------------------------------------
# F-01: an explicit --to target must not be overridden by orchestrator routing
# ---------------------------------------------------------------------------


MOCK_ROUTING_REROUTE = RoutingPlan(
    owner="codex-cli",
    tier="standard",
    effort="high",
    decompose=False,
    rationale="orchestrator thinks codex-cli is the better fit",
    subtasks=[],
    total_estimated_cost_usd=0.0,
    recommended_budget_usd=0.0,
)


class TestExplicitTargetWinsOverOrchestrator:
    def test_explicit_to_target_is_not_overridden(self, tmp_path):
        """An explicitly requested --to target always wins over the
        orchestrator's owner pick. The orchestrator may still set
        tier/effort, but never the dispatch target. Changing the agent
        stays reserved for the explicit --force-reassign path
        (superharness.commands.inbox_enqueue)."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        captured_target = {}

        def _fake_launch(target, *args, **kwargs):
            captured_target["target"] = target

        with patch("superharness.engine.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.route.return_value = MOCK_ROUTING_REROUTE

            with patch(
                "superharness.commands.delegate._launch_agent",
                side_effect=_fake_launch,
            ):
                with patch(
                    "superharness.commands.delegate.sdk_available",
                    return_value=False,
                ):
                    rc = delegate(
                        project_dir=str(project),
                        target="opencode",
                        task_id="T-42",
                        print_only=False,
                        non_interactive=False,
                        codex_bypass=False,
                        no_auto_model=True,
                    )

        assert rc == 0
        mock_instance.route.assert_called_once()
        assert captured_target.get("target") == "opencode", (
            "explicit --to opencode must win over orchestrator owner codex-cli"
        )
