"""Tests for superharness.engine.model_router."""
from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from superharness.engine.model_router import (
    MODEL_MAP,
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
        ("mini", "claude-haiku-4-5-20251001"),
        ("standard", "claude-sonnet-4-6"),
        ("max", "claude-opus-4-7"),
    ])
    def test_claude_code_tiers(self, tier, expected):
        assert resolve_model("claude-code", tier) == expected

    @pytest.mark.parametrize("tier,expected", [
        ("mini", "gpt-5.1-codex-mini"),
        ("standard", "gpt-5.3-codex"),
        ("max", "gpt-5.4"),
    ])
    def test_codex_cli_tiers(self, tier, expected):
        # Force apikey auth so chatgpt_account_overrides does not rewrite
        # gpt-5.3-codex → gpt-5-codex (bundled default since the discuss-
        # dispatch fix).
        from superharness.engine.model_router import _reset_codex_auth_cache
        _reset_codex_auth_cache()
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="Logged in using API key", stderr="")
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            assert resolve_model("codex-cli", tier) == expected

    def test_unknown_target_returns_sonnet(self):
        assert resolve_model("unknown-agent", "standard") == "claude-sonnet-4-6"

    def test_unknown_tier_returns_sonnet(self):
        assert resolve_model("claude-code", "nonexistent") == "claude-sonnet-4-6"


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


# ---------------------------------------------------------------------------
# Codex auth-mode detection + ChatGPT-account routing override
# ---------------------------------------------------------------------------


class TestDetectCodexAuthMode:
    def setup_method(self):
        from superharness.engine.model_router import _reset_codex_auth_cache
        _reset_codex_auth_cache()

    def teardown_method(self):
        from superharness.engine.model_router import _reset_codex_auth_cache
        _reset_codex_auth_cache()

    def test_chatgpt_account_detected(self):
        from superharness.engine.model_router import detect_codex_auth_mode
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Logged in using ChatGPT", stderr="",
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            assert detect_codex_auth_mode() == "chatgpt"

    def test_apikey_detected(self):
        from superharness.engine.model_router import detect_codex_auth_mode
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Logged in using API key", stderr="",
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            assert detect_codex_auth_mode() == "apikey"

    def test_unknown_when_codex_not_installed(self):
        from superharness.engine.model_router import detect_codex_auth_mode
        with mock.patch(
            "superharness.engine.model_router.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            assert detect_codex_auth_mode() == "unknown"

    def test_memoized_across_calls(self):
        from superharness.engine.model_router import detect_codex_auth_mode
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Logged in using ChatGPT", stderr="",
        )
        with mock.patch(
            "superharness.engine.model_router.subprocess.run", return_value=fake,
        ) as run:
            detect_codex_auth_mode()
            detect_codex_auth_mode()
            detect_codex_auth_mode()
        assert run.call_count == 1, "auth mode lookup must be memoized"


class TestChatgptAuthOverride:
    def setup_method(self):
        from superharness.engine.model_router import _reset_codex_auth_cache
        _reset_codex_auth_cache()

    def teardown_method(self):
        from superharness.engine.model_router import _reset_codex_auth_cache
        _reset_codex_auth_cache()

    def _project_with_overrides(self, tmp_path, overrides: dict[str, str]):
        import yaml as _yaml
        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True, exist_ok=True)
        (sh / "models.yaml").write_text(_yaml.safe_dump({
            "model_map": {
                "codex-cli": {
                    "mini": "gpt-5.1-codex-mini",
                    "standard": "gpt-5.3-codex",
                    "max": "gpt-5.4",
                },
            },
            "chatgpt_account_overrides": overrides,
        }))
        return tmp_path

    def test_no_override_when_model_not_in_map(self, tmp_path):
        """No override applies when the resolved model is not a key in
        chatgpt_account_overrides (here: codex-cli max → gpt-5.4)."""
        proj = self._project_with_overrides(tmp_path, {})
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="Logged in using ChatGPT", stderr="")
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            from superharness.engine.model_router import resolve_model, _load_model_map
            _load_model_map.__globals__["_cached_project_maps"].clear()
            assert resolve_model("codex-cli", "max", str(proj)) == "gpt-5.4"

    def test_override_applied_on_chatgpt_auth(self, tmp_path):
        proj = self._project_with_overrides(
            tmp_path, {"gpt-5.3-codex": "gpt-5-codex"},
        )
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="Logged in using ChatGPT", stderr="")
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            from superharness.engine.model_router import resolve_model, _load_model_map
            _load_model_map.__globals__["_cached_project_maps"].clear()
            assert resolve_model("codex-cli", "standard", str(proj)) == "gpt-5-codex"

    def test_override_skipped_on_apikey_auth(self, tmp_path):
        proj = self._project_with_overrides(
            tmp_path, {"gpt-5.3-codex": "gpt-5-codex"},
        )
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="Logged in using API key", stderr="")
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            from superharness.engine.model_router import resolve_model, _load_model_map
            _load_model_map.__globals__["_cached_project_maps"].clear()
            assert resolve_model("codex-cli", "standard", str(proj)) == "gpt-5.3-codex"

    def test_override_does_not_affect_other_targets(self, tmp_path):
        proj = self._project_with_overrides(
            tmp_path, {"gpt-5.3-codex": "gpt-5-codex"},
        )
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="Logged in using ChatGPT", stderr="")
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            from superharness.engine.model_router import resolve_model, _load_model_map
            _load_model_map.__globals__["_cached_project_maps"].clear()
            assert resolve_model("claude-code", "standard", str(proj)) == "claude-sonnet-4-6"

    def test_bundled_default_overrides_gpt53codex_on_chatgpt_auth(self, tmp_path):
        """Regression: bundled models.yaml must ship a default
        chatgpt_account_overrides mapping for gpt-5.3-codex so users on a
        ChatGPT-account Codex don't 400 on every `shux discuss` round."""
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="Logged in using ChatGPT", stderr="")
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake):
            from superharness.engine.model_router import resolve_model, _load_model_map
            _load_model_map.__globals__["_cached_project_maps"].clear()
            # No project override — exercises the bundled models.yaml.
            assert resolve_model("codex-cli", "standard", str(tmp_path)) == "gpt-5-codex"
