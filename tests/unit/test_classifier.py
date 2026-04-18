"""Tests for feat.classifier-v2 — heuristic + LLM + safety floor classifier.

§4.3-4.5 spec:
  Stage 1: heuristic_classify() — keyword/count triggers, None on no match
  Stage 2: llm_classify()       — Sonnet fallback (subprocess; mocked in tests)
  Stage 3: apply_safety_floor() — file count guard, budget guard, 1M auto-promote
  classify()                    — composes all three stages
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestHeuristicClassify:
    """Stage 1: fast pattern-matching rules — no subprocess calls."""

    def test_opus_keyword_in_title_promotes_to_opus_46_xhigh(self):
        """'oauth' in title → (claude-opus-4-6, xhigh)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify("feat.oauth-integration") == ("claude-opus-4-6", "xhigh")

    def test_opus_keyword_case_insensitive(self):
        """'ARCHITECTURE' in title (case-insensitive) → (claude-opus-4-6, xhigh)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify("feat.ARCHITECTURE-overhaul") == ("claude-opus-4-6", "xhigh")

    def test_many_criteria_promotes_to_opus_47_max(self):
        """AC count > 5 → (claude-opus-4-7, max)."""
        from superharness.engine.classifier import heuristic_classify
        criteria = ["ac1", "ac2", "ac3", "ac4", "ac5", "ac6"]
        assert heuristic_classify("feat.generic-task", criteria=criteria) == ("claude-opus-4-7", "max")

    def test_many_files_promotes_to_opus_47_max(self):
        """File count > 10 → (claude-opus-4-7, max)."""
        from superharness.engine.classifier import heuristic_classify
        files = [f"src/file{i}.py" for i in range(11)]
        assert heuristic_classify("feat.generic-task", files=files) == ("claude-opus-4-7", "max")

    def test_security_test_type_with_many_criteria_promotes_to_opus_47_max(self):
        """test_types includes 'security' AND AC count > 3 → (claude-opus-4-7, max)."""
        from superharness.engine.classifier import heuristic_classify
        criteria = ["ac1", "ac2", "ac3", "ac4"]
        assert heuristic_classify(
            "feat.generic-task",
            criteria=criteria,
            test_types=["unit", "security"],
        ) == ("claude-opus-4-7", "max")

    def test_retry_with_previous_opus_46_escalates_to_opus_47(self):
        """retry_count > 0 AND previous_model == claude-opus-4-6 → (claude-opus-4-7, max)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify(
            "feat.some-task",
            retry_count=1,
            previous_model="claude-opus-4-6",
        ) == ("claude-opus-4-7", "max")

    def test_typo_fix_title_demotes_to_sonnet_low(self):
        """Title starts with 'fix.typo' AND AC ≤ 2 → (claude-sonnet-4-6, low)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify(
            "fix.typo-readme", criteria=["fix one typo"]
        ) == ("claude-sonnet-4-6", "low")

    def test_docs_title_demotes_to_sonnet_low(self):
        """Title starts with 'docs:' AND AC ≤ 2 → (claude-sonnet-4-6, low)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify("docs: update changelog") == ("claude-sonnet-4-6", "low")

    def test_chore_title_with_many_criteria_does_not_demote(self):
        """Title starts with 'chore:' BUT AC > 2 → no rule fires, returns None."""
        from superharness.engine.classifier import heuristic_classify
        criteria = ["ac1", "ac2", "ac3"]
        assert heuristic_classify("chore: update deps", criteria=criteria) is None

    def test_unit_only_with_few_files_promotes_to_sonnet_medium(self):
        """test_types == ['unit'] AND file count ≤ 2 → (claude-sonnet-4-6, medium)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify(
            "feat.some-task",
            files=["src/foo.py"],
            test_types=["unit"],
        ) == ("claude-sonnet-4-6", "medium")

    def test_no_trigger_returns_none(self):
        """Generic task with no triggers → None (proceed to Stage 2)."""
        from superharness.engine.classifier import heuristic_classify
        assert heuristic_classify("feat.generic-feature", criteria=["ac1"]) is None


class TestLLMClassify:
    """Stage 2: Sonnet subprocess fallback (mocked)."""

    def test_llm_classify_returns_sonnet_medium_on_typical_response(self):
        """Mock subprocess returns 'sonnet-4-6 medium' → (claude-sonnet-4-6, medium)."""
        from superharness.engine.classifier import llm_classify
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sonnet-4-6 medium\n"
        with patch("superharness.engine.classifier.subprocess.run", return_value=mock_result):
            assert llm_classify("feat.generic-feature", criteria=["ac1"]) == ("claude-sonnet-4-6", "medium")

    def test_llm_classify_returns_opus_46_xhigh(self):
        """Mock subprocess returns 'opus-4-6 xhigh' → (claude-opus-4-6, xhigh)."""
        from superharness.engine.classifier import llm_classify
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "opus-4-6 xhigh\n"
        with patch("superharness.engine.classifier.subprocess.run", return_value=mock_result):
            assert llm_classify("feat.complex-security-thing") == ("claude-opus-4-6", "xhigh")

    def test_llm_classify_falls_back_on_subprocess_error(self):
        """Subprocess returns non-zero → fallback (claude-sonnet-4-6, medium)."""
        from superharness.engine.classifier import llm_classify
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("superharness.engine.classifier.subprocess.run", return_value=mock_result):
            assert llm_classify("feat.whatever") == ("claude-sonnet-4-6", "medium")

    def test_llm_classify_falls_back_on_timeout(self):
        """TimeoutExpired → fallback (claude-sonnet-4-6, medium)."""
        from superharness.engine.classifier import llm_classify
        with patch(
            "superharness.engine.classifier.subprocess.run",
            side_effect=subprocess.TimeoutExpired("claude", 15),
        ):
            assert llm_classify("feat.whatever") == ("claude-sonnet-4-6", "medium")


class TestSafetyFloor:
    """Stage 3: apply_safety_floor()."""

    def test_many_files_bumps_sonnet_effort_to_high(self):
        """file count > 6 AND model == claude-sonnet-4-6 → effort bumped to at least 'high'."""
        from superharness.engine.classifier import apply_safety_floor
        files = [f"src/file{i}.py" for i in range(7)]
        model, effort = apply_safety_floor("claude-sonnet-4-6", "medium", files=files)
        assert model == "claude-sonnet-4-6"
        assert effort == "high"

    def test_many_files_does_not_affect_opus(self):
        """file count > 6 AND model == claude-opus-4-6 → no change."""
        from superharness.engine.classifier import apply_safety_floor
        files = [f"src/file{i}.py" for i in range(7)]
        model, effort = apply_safety_floor("claude-opus-4-6", "xhigh", files=files)
        assert model == "claude-opus-4-6"
        assert effort == "xhigh"

    def test_max_effort_with_large_token_count_promotes_to_1m(self):
        """effort=max AND estimated_tokens > 200K → claude-opus-4-7[1m]."""
        from superharness.engine.classifier import apply_safety_floor
        model, effort = apply_safety_floor(
            "claude-opus-4-7", "max", estimated_tokens=250_000
        )
        assert model == "claude-opus-4-7[1m]"
        assert effort == "max"

    def test_max_effort_at_threshold_does_not_promote_to_1m(self):
        """effort=max AND estimated_tokens == 200K → no change (> not >=)."""
        from superharness.engine.classifier import apply_safety_floor
        model, effort = apply_safety_floor(
            "claude-opus-4-7", "max", estimated_tokens=200_000
        )
        assert model == "claude-opus-4-7"
        assert effort == "max"

    def test_sonnet_effort_already_high_not_bumped_further(self):
        """file count > 6 AND effort already 'high' → no change (already at floor)."""
        from superharness.engine.classifier import apply_safety_floor
        files = [f"src/file{i}.py" for i in range(7)]
        model, effort = apply_safety_floor("claude-sonnet-4-6", "high", files=files)
        assert model == "claude-sonnet-4-6"
        assert effort == "high"


class TestClassify:
    """Full classify() — heuristic + LLM + safety floor integration."""

    def test_classify_uses_heuristic_for_opus_keyword(self):
        """'oauth' in title → heuristic fires, no LLM subprocess call."""
        from superharness.engine.classifier import classify
        with patch("superharness.engine.classifier.subprocess.run") as mock_run:
            model, effort = classify("feat.oauth-sso")
        mock_run.assert_not_called()
        assert model == "claude-opus-4-6"
        assert effort == "xhigh"

    def test_classify_falls_through_to_llm_when_no_heuristic(self):
        """Generic task → heuristic returns None → LLM subprocess called once."""
        from superharness.engine.classifier import classify
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sonnet-4-6 medium\n"
        with patch("superharness.engine.classifier.subprocess.run", return_value=mock_result) as mock_run:
            model, effort = classify("feat.ordinary-task", criteria=["ac1"])
        mock_run.assert_called_once()
        assert model == "claude-sonnet-4-6"
        assert effort == "medium"

    def test_classify_applies_safety_floor_after_heuristic(self):
        """Heuristic → (sonnet, low), then safety floor bumps effort when files > 6."""
        from superharness.engine.classifier import classify
        files = [f"src/file{i}.py" for i in range(7)]
        with patch("superharness.engine.classifier.subprocess.run"):
            model, effort = classify("fix.typo-readme", files=files, criteria=["one fix"])
        assert model == "claude-sonnet-4-6"
        assert effort == "high"
