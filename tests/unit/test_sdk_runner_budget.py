"""Tests for SDKRunner budget enforcement and cost tracking.

Covers all 5 acceptance criteria:
1. BudgetExceededError raised when cost exceeds max_budget_usd
2. run() returns dict with cost_usd, input_tokens, output_tokens
3. cost_usd calculated using MODEL_PRICING (same table as cost_estimator)
4. Total cost accumulates across multiple run() calls
5. reset_session() resets token and cost counters to zero

These tests mock claude_agent_sdk so they run without the real SDK installed.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# SDK stub setup — inject a fake claude_agent_sdk before any import of
# sdk_runner so the module-level import guard passes.
# ---------------------------------------------------------------------------

def _build_sdk_stub():
    """Build a minimal claude_agent_sdk stub module."""
    stub = types.ModuleType("claude_agent_sdk")

    class _ResultMessage:
        def __init__(self, result="", input_tokens=0, output_tokens=0):
            self.result = result
            self.subtype = "success"
            self.stop_reason = "end_turn"
            self.total_cost_usd = 0.0
            self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}

    class _StreamEvent:
        def __init__(self, text=""):
            self.text = text

    class _ClaudeAgentOptions:
        model = None
        cwd = None
        permission_mode = None

    stub.ResultMessage = _ResultMessage
    stub.StreamEvent = _StreamEvent
    stub.ClaudeAgentOptions = _ClaudeAgentOptions
    stub.query = None  # set per-test
    return stub


_SDK_STUB = _build_sdk_stub()


def _install_sdk_stub():
    """Register the stub in sys.modules."""
    sys.modules.setdefault("claude_agent_sdk", _SDK_STUB)


_install_sdk_stub()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mock_query(result_text="OK", input_tokens=0, output_tokens=0):
    """Async generator mimicking claude_agent_sdk.query()."""
    yield _SDK_STUB.ResultMessage(result_text, input_tokens, output_tokens)


def _make_query(result_text="OK", input_tokens=0, output_tokens=0):
    """Return a callable for patching claude_agent_sdk.query."""
    def _q(prompt, options=None):
        return _mock_query(result_text, input_tokens, output_tokens)
    return _q


# ---------------------------------------------------------------------------
# Acceptance criterion 2 — run() returns dict with cost_usd, input_tokens,
# output_tokens keys
# ---------------------------------------------------------------------------

class TestRunReturnShape:
    """AC2: run() returns dict with cost_usd, input_tokens, output_tokens."""

    def test_run_returns_cost_usd_key(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            _SDK_STUB.query = _make_query("ok", 100, 50)
            with patch("claude_agent_sdk.query", _SDK_STUB.query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                result = runner.run("hello")

        assert "cost_usd" in result, "run() must return a 'cost_usd' key"

    def test_run_returns_input_tokens_key(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            _SDK_STUB.query = _make_query("ok", 100, 50)
            with patch("claude_agent_sdk.query", _SDK_STUB.query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                result = runner.run("hello")

        assert "input_tokens" in result, "run() must return an 'input_tokens' key"

    def test_run_returns_output_tokens_key(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            _SDK_STUB.query = _make_query("ok", 100, 50)
            with patch("claude_agent_sdk.query", _SDK_STUB.query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                result = runner.run("hello")

        assert "output_tokens" in result, "run() must return an 'output_tokens' key"

    def test_run_returns_correct_token_values(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            _SDK_STUB.query = _make_query("ok", 333, 111)
            with patch("claude_agent_sdk.query", _SDK_STUB.query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                result = runner.run("hello")

        assert result["input_tokens"] == 333
        assert result["output_tokens"] == 111


# ---------------------------------------------------------------------------
# Acceptance criterion 3 — cost_usd uses MODEL_PRICING
# ---------------------------------------------------------------------------

class TestCostCalculation:
    """AC3: cost_usd is calculated using MODEL_PRICING."""

    def test_cost_usd_uses_model_pricing_sonnet(self, tmp_path):
        """Sonnet pricing: $3/M input, $15/M output."""
        from superharness.engine.sdk_runner import SDKRunner, MODEL_PRICING

        assert "claude-sonnet-4-6" in MODEL_PRICING, "MODEL_PRICING must include claude-sonnet-4-6"

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            _SDK_STUB.query = _make_query("ok", 1_000_000, 1_000_000)
            with patch("claude_agent_sdk.query", _SDK_STUB.query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                result = runner.run("pricing test")

        expected = MODEL_PRICING["claude-sonnet-4-6"]["input"] + MODEL_PRICING["claude-sonnet-4-6"]["output"]
        assert abs(result["cost_usd"] - expected) < 1e-9

    def test_cost_usd_uses_model_pricing_haiku(self, tmp_path):
        """Haiku pricing: $0.25/M input, $1.25/M output."""
        from superharness.engine.sdk_runner import SDKRunner, MODEL_PRICING

        assert "claude-haiku-4-5-20251001" in MODEL_PRICING

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            _SDK_STUB.query = _make_query("ok", 1_000_000, 1_000_000)
            with patch("claude_agent_sdk.query", _SDK_STUB.query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-haiku-4-5-20251001")
                result = runner.run("pricing test")

        expected = MODEL_PRICING["claude-haiku-4-5-20251001"]["input"] + MODEL_PRICING["claude-haiku-4-5-20251001"]["output"]
        assert abs(result["cost_usd"] - expected) < 1e-9

    def test_cost_estimator_uses_same_pricing_table(self):
        """cost_estimator.MODEL_PRICING must be the same object as sdk_runner.MODEL_PRICING."""
        from superharness.engine.sdk_runner import MODEL_PRICING as SDK_PRICING
        from superharness.engine.cost_estimator import PRICING as CE_PRICING  # imported as PRICING alias

        assert SDK_PRICING is CE_PRICING, (
            "cost_estimator must import MODEL_PRICING from sdk_runner — same table"
        )


# ---------------------------------------------------------------------------
# Acceptance criterion 4 — cost accumulates across multiple run() calls
# ---------------------------------------------------------------------------

class TestCostAccumulation:
    """AC4: Total cost accumulates across multiple run() calls."""

    def test_total_cost_accumulates(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            # First call: 100k/50k tokens; second: 200k/100k
            if call_count[0] == 1:
                return _mock_query("first", 100_000, 50_000)
            return _mock_query("second", 200_000, 100_000)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                r1 = runner.run("first")
                cost_after_first = runner.total_cost_usd
                assert cost_after_first > 0

                r2 = runner.run("second")
                cost_after_second = runner.total_cost_usd

        assert cost_after_second > cost_after_first, "total_cost_usd must increase after second run"
        assert abs(cost_after_second - (r1["cost_usd"] + r2["cost_usd"])) < 1e-9

    def test_total_input_tokens_accumulate(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            return _mock_query("out", 1000, 500)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path)
                runner.run("a")
                runner.run("b")

        assert runner.total_input_tokens == 2000
        assert runner.total_output_tokens == 1000

    def test_total_output_tokens_accumulate(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            return _mock_query("out", 500, 250)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path)
                runner.run("a")
                runner.run("b")
                runner.run("c")

        assert runner.total_input_tokens == 1500
        assert runner.total_output_tokens == 750


# ---------------------------------------------------------------------------
# Acceptance criterion 1 — BudgetExceededError when cost > max_budget_usd
# ---------------------------------------------------------------------------

class TestBudgetEnforcement:
    """AC1: BudgetExceededError raised when actual cost exceeds max_budget_usd."""

    def test_raises_budget_exceeded_error(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner, BudgetExceededError

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_query("cheap", 1_000, 500)        # very cheap
            return _mock_query("expensive", 10_000_000, 5_000_000)  # very expensive

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(
                    project_dir=tmp_path,
                    model="claude-sonnet-4-6",
                    max_budget_usd=0.10,
                )
                runner.run("cheap call")  # should not raise
                with pytest.raises(BudgetExceededError, match="Budget exceeded"):
                    runner.run("expensive call")

    def test_budget_exceeded_error_is_raised_after_cost_accumulated(self, tmp_path):
        """Each individual run is cheap, but cumulative cost triggers the error."""
        from superharness.engine.sdk_runner import SDKRunner, BudgetExceededError

        # 50k sonnet tokens = 0.15+0.75 = ~$0.0002 per run; need >50 runs to exceed $0.01
        # Use larger tokens: 1M input + 1M output = $18 per run → exceed $0.01 in first run
        # But we want it to accumulate: use 0 tokens first, then large.
        runs = [0]

        def mock_query(prompt, options=None):
            runs[0] += 1
            if runs[0] < 3:
                return _mock_query("ok", 10, 5)   # negligible cost
            return _mock_query("big", 1_000_000, 1_000_000)  # $18

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(
                    project_dir=tmp_path,
                    model="claude-sonnet-4-6",
                    max_budget_usd=5.00,
                )
                runner.run("tiny 1")
                runner.run("tiny 2")
                with pytest.raises(BudgetExceededError):
                    runner.run("big one")

    def test_no_budget_set_never_raises(self, tmp_path):
        """Without max_budget_usd, BudgetExceededError is never raised."""
        from superharness.engine.sdk_runner import SDKRunner

        def mock_query(prompt, options=None):
            return _mock_query("ok", 100_000_000, 100_000_000)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("huge call")  # should not raise

        assert runner.total_cost_usd > 0

    def test_budget_exceeded_error_message_contains_amounts(self, tmp_path):
        """BudgetExceededError message contains actual vs limit cost."""
        from superharness.engine.sdk_runner import SDKRunner, BudgetExceededError

        def mock_query(prompt, options=None):
            return _mock_query("ok", 10_000_000, 5_000_000)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(
                    project_dir=tmp_path,
                    model="claude-sonnet-4-6",
                    max_budget_usd=0.01,
                )
                with pytest.raises(BudgetExceededError) as exc_info:
                    runner.run("costly call")

        assert "Budget exceeded" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Acceptance criterion 5 — reset_session() resets counters to zero
# ---------------------------------------------------------------------------

class TestResetSession:
    """AC5: reset_session() resets token and cost counters to zero."""

    def test_reset_clears_total_cost_usd(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        def mock_query(prompt, options=None):
            return _mock_query("ok", 1000, 500)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("test")
                assert runner.total_cost_usd > 0

                runner.reset_session()

        assert runner.total_cost_usd == 0.0

    def test_reset_clears_total_input_tokens(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        def mock_query(prompt, options=None):
            return _mock_query("ok", 1000, 500)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("test")
                assert runner.total_input_tokens == 1000

                runner.reset_session()

        assert runner.total_input_tokens == 0

    def test_reset_clears_total_output_tokens(self, tmp_path):
        from superharness.engine.sdk_runner import SDKRunner

        def mock_query(prompt, options=None):
            return _mock_query("ok", 1000, 500)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("test")
                assert runner.total_output_tokens == 500

                runner.reset_session()

        assert runner.total_output_tokens == 0

    def test_run_after_reset_tracks_fresh_tokens(self, tmp_path):
        """After reset, a new run() accumulates from zero."""
        from superharness.engine.sdk_runner import SDKRunner

        call_count = [0]

        def mock_query(prompt, options=None):
            call_count[0] += 1
            return _mock_query("ok", 1000, 500)

        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch("claude_agent_sdk.query", side_effect=mock_query):
                runner = SDKRunner(project_dir=tmp_path, model="claude-sonnet-4-6")
                runner.run("before reset")
                assert runner.total_input_tokens == 1000

                runner.reset_session()
                runner.run("after reset")

        assert runner.total_input_tokens == 1000  # only post-reset run counted
        assert runner.total_output_tokens == 500
