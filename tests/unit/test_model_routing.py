"""Unit tests for Iter 3: ModelRouter — role-based model selection."""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.model_router_roles import ModelRouter, _DEFAULT_ROUTING


class TestModelRouterDefaults:
    def test_orchestrator_uses_opus(self):
        router = ModelRouter()
        assert router.model_for("orchestrator") == "claude-opus-4-6"

    def test_worker_uses_sonnet(self):
        router = ModelRouter()
        assert router.model_for("worker") == "claude-sonnet-4-6"

    def test_validator_uses_sonnet(self):
        router = ModelRouter()
        assert router.model_for("validator") == "claude-sonnet-4-6"

    def test_code_reviewer_uses_sonnet(self):
        router = ModelRouter()
        assert router.model_for("code_reviewer") == "claude-sonnet-4-6"

    def test_unknown_role_returns_sonnet_fallback(self):
        router = ModelRouter()
        assert router.model_for("nonexistent") == "claude-sonnet-4-6"


class TestModelRouterOverrides:
    def test_custom_validator_model(self):
        router = ModelRouter(overrides={"validator": "claude-haiku-4-5-20251001"})
        assert router.model_for("validator") == "claude-haiku-4-5-20251001"

    def test_override_does_not_affect_other_roles(self):
        router = ModelRouter(overrides={"validator": "claude-haiku-4-5-20251001"})
        assert router.model_for("worker") == "claude-sonnet-4-6"
        assert router.model_for("orchestrator") == "claude-opus-4-6"

    def test_all_routes_merges_overrides(self):
        router = ModelRouter(overrides={"worker": "claude-haiku-4-5-20251001"})
        routes = router.all_routes()
        assert routes["worker"] == "claude-haiku-4-5-20251001"
        assert routes["orchestrator"] == _DEFAULT_ROUTING["orchestrator"]


class TestModelRouterFromProject:
    def test_from_project_without_profile_returns_defaults(self, tmp_path: Path):
        router = ModelRouter.from_project(str(tmp_path))
        assert router.model_for("orchestrator") == "claude-opus-4-6"

    def test_from_project_reads_profile_yaml(self, tmp_path: Path):
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "profile.yaml").write_text(
            "model_routing:\n  validator: claude-haiku-4-5-20251001\n"
        )
        router = ModelRouter.from_project(str(tmp_path))
        assert router.model_for("validator") == "claude-haiku-4-5-20251001"
        assert router.model_for("worker") == "claude-sonnet-4-6"

    def test_from_project_without_model_routing_section(self, tmp_path: Path):
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "profile.yaml").write_text("autonomy: oversight\n")
        router = ModelRouter.from_project(str(tmp_path))
        assert router.model_for("worker") == "claude-sonnet-4-6"
