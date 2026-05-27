"""Tests for superharness.engine.model_router."""
from __future__ import annotations

import subprocess
from importlib import resources
from unittest import mock

import pytest

from superharness.engine.model_router import (
    MODEL_MAP,
    VALID_TIERS,
    classify_task,
    resolve_model,
    resolve_tier,
)


def test_delegate_wires_chatgpt_auth_override_into_resolution_path():
    """Regression: commands/delegate.py MUST call _apply_chatgpt_auth_override
    after all model-resolution paths (CLI, task field, auto-classify via
    adapter_registry, profile, fallback, tier-reroute) so codex-cli on a
    ChatGPT account gets gpt-5.3-codex → gpt-5-codex remapped before
    invoking the codex CLI. Without this call site the bundled override
    map is dead code on the dispatch path (see
    docs/bugs/2026-05-11_discuss_dispatch_bugs.md Bug C)."""
    import inspect
    from superharness.commands import delegate as _delegate_mod
    src = inspect.getsource(_delegate_mod.delegate)
    assert "_apply_chatgpt_auth_override" in src, (
        "delegate() must call _apply_chatgpt_auth_override on the resolved "
        "model. Removing this re-introduces Bug C."
    )
    # Order matters: the override must run AFTER the tier-reroute block so
    # it covers every path. The tier-reroute imports resolve_tier; the
    # override must appear later in the function body.
    assert src.find("_apply_chatgpt_auth_override") > src.find("resolve_tier"), (
        "_apply_chatgpt_auth_override must run after the tier-reroute block "
        "so it covers every resolution path."
    )


def test_models_yaml_shipped_as_package_data():
    """Regression: engine/models.yaml MUST be packaged with the wheel.
    Without it, load_yaml_config silently falls back to {} and
    chatgpt_account_overrides becomes empty — ChatGPT-account Codex users
    then 400 on every dispatch. Bug history: dropped from the wheel for
    1.56.0 and 1.56.1; restored in 1.56.2 by adding `engine/*.yaml` to
    [tool.setuptools.package-data] in pyproject.toml."""
    import yaml as _yaml
    pkg = resources.files("superharness")
    text = (pkg / "engine" / "models.yaml").read_text()
    doc = _yaml.safe_load(text)
    assert "model_map" in doc
    assert doc.get("chatgpt_account_overrides", {}).get("gpt-5.3-codex") == "gpt-5-codex"


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

    def test_opencode_has_all_tiers(self):
        """opencode must be in MODEL_MAP with mini/standard/max entries."""
        assert "opencode" in MODEL_MAP
        for tier in VALID_TIERS:
            assert tier in MODEL_MAP["opencode"], f"opencode missing tier {tier}"

    def test_gemini_models_updated_from_legacy(self):
        """Gemini entries must use current model IDs, not legacy ones."""
        gemini = MODEL_MAP["gemini-cli"]
        assert gemini["mini"] == "gemini-2.5-flash"
        assert gemini["standard"] == "gemini-2.5-pro"
        assert gemini["max"] == "gemini-3.1-pro-preview"
        # Legacy names must not appear
        assert gemini["max"] != "gemini-ultra"
        assert "2.0" not in gemini["mini"]
        assert "2.0" not in gemini["standard"]


# ---------------------------------------------------------------------------
# Multi-agent classifier chain
# ---------------------------------------------------------------------------


class TestMultiAgentClassifier:
    def test_classifier_agents_list_has_four_entries(self):
        from superharness.engine.model_router import _CLASSIFIER_AGENTS
        assert len(_CLASSIFIER_AGENTS) == 4

    def test_classifier_agent_names_are_registered(self):
        from superharness.engine.model_router import _CLASSIFIER_AGENTS
        names = [a for a, _ in _CLASSIFIER_AGENTS]
        assert "claude-code" in names
        assert "gemini-cli" in names
        assert "opencode" in names
        assert "codex-cli" in names

    def test_classifier_templates_use_model_and_prompt(self):
        from superharness.engine.model_router import _CLASSIFIER_AGENTS
        for _, template in _CLASSIFIER_AGENTS:
            cmd = " ".join(template)
            assert "{model}" in cmd, f"missing {{model}} in {template}"
            assert "{prompt}" in cmd, f"missing {{prompt}} in {template}"

    def test_try_classify_returns_tier_effort(self):
        from superharness.engine.model_router import _try_classify
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="max high\n", stderr=""
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            result = _try_classify(
                "claude-code",
                ["claude", "--model", "{model}", "-p", "{prompt}"],
                "haiku",
                "test prompt",
            )
        assert result is not None
        assert result == ("max", "high")

    def test_try_classify_returns_none_on_subprocess_failure(self):
        from superharness.engine.model_router import _try_classify
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with mock.patch("superharness.engine.model_router.subprocess.run", return_value=fake_result):
            result = _try_classify(
                "gemini-cli",
                ["gemini", "-m", "{model}", "-p", "{prompt}"],
                "gemini-2.5-flash",
                "test prompt",
            )
        assert result is None

    def test_try_classify_returns_none_on_timeout(self):
        from superharness.engine.model_router import _try_classify
        with mock.patch(
            "superharness.engine.model_router.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5),
        ):
            result = _try_classify(
                "opencode",
                ["opencode", "run", "-m", "{model}", "{prompt}"],
                "deepseek-chat",
                "test prompt",
            )
        assert result is None

    def test_try_classify_returns_none_on_missing_cli(self):
        from superharness.engine.model_router import _try_classify
        with mock.patch(
            "superharness.engine.model_router.subprocess.run",
            side_effect=FileNotFoundError("not found"),
        ):
            result = _try_classify(
                "codex-cli",
                ["codex", "exec", "-m", "{model}", "{prompt}"],
                "gpt-5.1-codex-mini",
                "test prompt",
            )
        assert result is None

    def test_classify_task_tries_first_agent_and_succeeds(self):
        """First agent (claude/haiku) responds → no other agents tried."""
        from superharness.engine.model_router import classify_task, _try_classify
        real_try = _try_classify

        call_count = {"count": 0}

        def counting_try(agent, cmd_template, model, prompt):
            call_count["count"] += 1
            if agent == "claude-code":
                return ("standard", "medium")
            return None

        with mock.patch(
            "superharness.engine.model_router._try_classify",
            side_effect=counting_try,
        ):
            tier, effort = classify_task("Some task")

        assert tier == "standard"
        assert effort == "medium"
        assert call_count["count"] == 1  # Only first agent tried

    def test_classify_task_falls_through_to_second_agent(self):
        """First agent fails, second agent (gemini) responds."""
        from superharness.engine.model_router import classify_task, _try_classify
        real_try = _try_classify

        call_count = {"count": 0}

        def fallthrough_try(agent, cmd_template, model, prompt):
            call_count["count"] += 1
            if agent == "claude-code":
                return None  # Haiku down
            if agent == "gemini-cli":
                return ("max", "high")
            return None

        with mock.patch(
            "superharness.engine.model_router._try_classify",
            side_effect=fallthrough_try,
        ):
            tier, effort = classify_task("Complex architecture task")

        assert tier == "max"
        assert effort == "high"
        assert call_count["count"] == 2

    def test_classify_task_all_agents_fail_falls_back(self):
        """All four agents fail → returns standard/medium."""
        from superharness.engine.model_router import classify_task

        with mock.patch(
            "superharness.engine.model_router._try_classify",
            return_value=None,
        ):
            tier, effort = classify_task("Some task")

        assert tier == "standard"
        assert effort == "medium"

    def test_classify_task_skips_agent_without_mini_model(self):
        """Agent without mini model in the map → skipped gracefully."""
        from superharness.engine.model_router import classify_task
        real_map = MODEL_MAP

        # Remove gemini's mini entry to simulate missing config
        broken_map = dict(real_map)
        broken_map["gemini-cli"] = {"standard": "gpt-4", "max": "gpt-4o"}

        with mock.patch(
            "superharness.engine.model_router._load_model_map",
            return_value=broken_map,
        ), mock.patch(
            "superharness.engine.model_router._try_classify",
        ) as mock_try:
            mock_try.return_value = None
            tier, effort = classify_task("Some task")

        assert tier == "standard"
        assert effort == "medium"
        # gemini-cli was never passed to _try_classify (no mini model)
        gemini_called = any(
            call_args[0][0] == "gemini-cli"
            for call_args in mock_try.call_args_list
        )
        assert not gemini_called, "gemini-cli should be skipped when mini model is missing"


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
