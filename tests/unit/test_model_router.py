"""Tests for superharness.engine.model_router."""
from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from superharness.engine.model_router import (
    MODEL_MAP,
    VALID_EFFORTS,
    VALID_TIERS,
    classify_task,
    resolve_model,
    resolve_tier,
)


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    @pytest.mark.parametrize("tier,expected", [
        ("mini", "haiku"),
        ("standard", "sonnet"),
        ("max", "opus"),
    ])
    def test_claude_code_tiers(self, tier, expected):
        assert resolve_model("claude-code", tier) == expected

    @pytest.mark.parametrize("tier,expected", [
        ("mini", "gpt-5.2"),
        ("standard", "gpt-5.3-codex"),
        ("max", "gpt-5.4"),
    ])
    def test_codex_cli_tiers(self, tier, expected):
        assert resolve_model("codex-cli", tier) == expected

    def test_unknown_target_returns_sonnet(self):
        assert resolve_model("unknown-agent", "standard") == "sonnet"

    def test_unknown_tier_returns_sonnet(self):
        assert resolve_model("claude-code", "nonexistent") == "sonnet"


# ---------------------------------------------------------------------------
# resolve_tier
# ---------------------------------------------------------------------------


class TestResolveTier:
    @pytest.mark.parametrize("name", ["mini", "standard", "max"])
    def test_valid_tier_names(self, name):
        assert resolve_tier(name) == name

    @pytest.mark.parametrize("name", ["sonnet", "haiku", "opus", "gpt-5.4", ""])
    def test_non_tier_names_return_none(self, name):
        assert resolve_tier(name) is None


# ---------------------------------------------------------------------------
# classify_task
# ---------------------------------------------------------------------------


class TestClassifyTask:
    def test_returns_parsed_tier_and_effort(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="mini low\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            tier, effort = classify_task("Fix typo in README")
        assert tier == "mini"
        assert effort == "low"

    def test_returns_standard_medium_on_subprocess_failure(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            tier, effort = classify_task("Some task")
        assert tier == "standard"
        assert effort == "medium"

    def test_returns_fallback_on_timeout(self):
        with mock.patch(
            "superharness.engine.model_router.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10),
        ):
            tier, effort = classify_task("Some task")
        assert tier == "standard"
        assert effort == "medium"

    def test_returns_fallback_on_missing_cli(self):
        with mock.patch(
            "superharness.engine.model_router.subprocess.run",
            side_effect=FileNotFoundError("claude not found"),
        ):
            tier, effort = classify_task("Some task")
        assert tier == "standard"
        assert effort == "medium"

    def test_returns_fallback_on_single_word_output(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="standard\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            tier, effort = classify_task("Some task")
        assert tier == "standard"
        assert effort == "medium"

    def test_invalid_tier_falls_back(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="huge high\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            tier, effort = classify_task("Some task")
        assert tier == "standard"
        assert effort == "high"

    def test_invalid_effort_falls_back(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="mini extreme\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            tier, effort = classify_task("Some task")
        assert tier == "mini"
        assert effort == "medium"

    def test_criteria_and_files_passed_to_prompt(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="standard medium\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result) as mock_run:
            classify_task(
                "Implement search",
                criteria=["must pass tests", "coverage > 80%"],
                files=["src/search.py"],
                previously_failed=True,
            )
        call_args = mock_run.call_args
        prompt_arg = call_args[0][0][-1]  # last arg is the prompt
        assert "must pass tests" in prompt_arg
        assert "src/search.py" in prompt_arg
        assert "Previously failed: yes" in prompt_arg

    def test_max_tier_output(self):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="max high\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            tier, effort = classify_task("Architecture redesign")
        assert tier == "max"
        assert effort == "high"


# ---------------------------------------------------------------------------
# MODEL_MAP completeness
# ---------------------------------------------------------------------------


class TestModelMapCompleteness:
    def test_all_targets_have_all_tiers(self):
        for target, tier_map in MODEL_MAP.items():
            for tier in VALID_TIERS:
                assert tier in tier_map, f"{target} missing tier {tier}"
