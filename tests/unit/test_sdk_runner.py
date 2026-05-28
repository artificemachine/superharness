"""Tests for Agent SDK runner.

Tests mock claude_agent_sdk.query() to avoid real API calls.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("claude_agent_sdk")


def _make_result_message(result_text="OK", input_tokens=0, output_tokens=0):
    """Create a mock ResultMessage using the real class."""
    from claude_agent_sdk import ResultMessage
    msg = ResultMessage.__new__(ResultMessage)
    object.__setattr__(msg, "result", result_text)
    object.__setattr__(msg, "subtype", "success")
    object.__setattr__(msg, "stop_reason", "end_turn")
    object.__setattr__(msg, "total_cost_usd", 0.0)
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    object.__setattr__(msg, "usage", usage)
    return msg


def _make_stream_event(text=""):
    """Create a mock StreamEvent using the real class."""
    from claude_agent_sdk import StreamEvent
    event = StreamEvent.__new__(StreamEvent)
    object.__setattr__(event, "text", text)
    return event


async def _mock_query_gen(result_text="OK", input_tokens=10, output_tokens=5, stream_chunks=None):
    """Async generator that mimics query() output."""
    if stream_chunks:
        for chunk in stream_chunks:
            yield _make_stream_event(chunk)
    yield _make_result_message(result_text, input_tokens, output_tokens)


class TestSDKRunner:

    def test_sdk_available_returns_true_when_sdk_installed(self):
        from superharness.engine.sdk_runner import sdk_available
        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            assert sdk_available() is True

    def test_sdk_available_returns_false_when_sdk_missing(self):
        from superharness.engine.sdk_runner import sdk_available
        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=False):
            assert sdk_available() is False

    def test_runner_raises_runtime_error_if_sdk_unavailable(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner
        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=False):
            with pytest.raises(RuntimeError, match="claude_agent_sdk is not available"):
                SDKRunner(project_dir=tmp_path)

    def test_runner_run_returns_output(self, tmp_path):
        """run() returns dict with output text from ResultMessage."""
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", return_value=_mock_query_gen("hello world", 10, 5)):
                runner = SDKRunner(project_dir=tmp_path)
                result = runner.run("say hello")

        assert result["output"] == "hello world"

    def test_runner_passes_model_to_options(self, tmp_path):
        """run() sets model on ClaudeAgentOptions."""
        from superharness.engine.sdk_runner import SDKRunner

        captured_options = {}

        def mock_query(prompt, options=None):
            captured_options["model"] = options.model if options else None
            return _mock_query_gen("ok")

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-opus-4-6")
                runner.run("test")

        assert captured_options["model"] == "claude-opus-4-6"


class TestSDKTokenTracking:

    def test_tracks_tokens_from_result(self, tmp_path):
        """run() extracts token usage from ResultMessage."""
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", return_value=_mock_query_gen("ok", 1000, 500)):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("test")

        assert runner.total_input_tokens == 1000
        assert runner.total_output_tokens == 500
        assert runner.total_cost_usd > 0

    def test_accumulates_across_runs(self, tmp_path):
        """Token counts accumulate across multiple run() calls."""
        from superharness.engine.sdk_runner import SDKRunner

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_query_gen("first", 1000, 500)
            return _mock_query_gen("second", 2000, 1000)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("first")
                assert runner.total_input_tokens == 1000

                runner.run("second")
                assert runner.total_input_tokens == 3000
                assert runner.total_output_tokens == 1500


class TestSDKBudgetGuard:

    def test_raises_when_budget_exceeded(self, tmp_path):
        """BudgetExceededError raised when cost exceeds max_budget_usd."""
        from superharness.engine.sdk_runner import SDKRunner, BudgetExceededError

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_query_gen("cheap", 1000, 500)
            return _mock_query_gen("expensive", 100000, 50000)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6", max_budget_usd=0.50)
                runner.run("cheap call")
                assert runner.total_cost_usd < 0.50

                with pytest.raises(BudgetExceededError, match="Budget exceeded"):
                    runner.run("expensive call")

    def test_no_budget_limit_never_raises(self, tmp_path):
        """Without max_budget_usd, no BudgetExceededError."""
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", return_value=_mock_query_gen("ok", 100000, 50000)):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("big call")
                assert runner.total_cost_usd > 0


class TestSDKLogFile:

    def test_creates_log_directory(self, tmp_path):
        """run() creates parent directory for log_file if missing."""
        from superharness.engine.sdk_runner import SDKRunner

        log_file = tmp_path / "logs" / "subdir" / "test.log"

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", return_value=_mock_query_gen("ok")):
                runner = SDKRunner(project_dir=tmp_path)
                runner.run("test", log_file=log_file)

        assert log_file.parent.exists()

    def test_without_log_file_works(self, tmp_path):
        """run() without log_file works fine."""
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", return_value=_mock_query_gen("hello")):
                runner = SDKRunner(project_dir=tmp_path)
                result = runner.run("test")

        assert result["output"] == "hello"


class TestSDKSession:

    def test_reset_clears_totals(self, tmp_path):
        """reset_session() zeros out token and cost tracking."""
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", return_value=_mock_query_gen("ok", 1000, 500)):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("test")
                assert runner.total_input_tokens == 1000

                runner.reset_session()
                assert runner.total_input_tokens == 0
                assert runner.total_output_tokens == 0
                assert runner.total_cost_usd == 0.0


class TestSDKCostCalculation:

    def test_sonnet_pricing(self):
        from superharness.engine.sdk_runner import _calculate_cost
        cost = _calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == 3.0 + 15.0  # $3/M in + $15/M out

    def test_haiku_pricing(self):
        from superharness.engine.sdk_runner import _calculate_cost
        cost = _calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == 0.25 + 1.25

    def test_opus_pricing(self):
        from superharness.engine.sdk_runner import _calculate_cost
        cost = _calculate_cost("claude-opus-4-6", 1_000_000, 1_000_000)
        assert cost == 5.0 + 25.0

    def test_unknown_model_defaults_to_sonnet(self):
        from superharness.engine.sdk_runner import _calculate_cost
        cost = _calculate_cost("unknown-model", 1_000_000, 1_000_000)
        assert cost == 3.0 + 15.0
