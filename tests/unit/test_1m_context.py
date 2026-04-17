"""Tests for feat.1m-context-tier — auto-promotion to claude-opus-4-7[1m].

§3.3 spec: should_use_1m_context(effort, estimated_input_tokens, context_1m=False)
Three paths to max-1m:
  1. Auto: effort=max AND estimated_input_tokens > 200_000
  2. Operator pin: context_1m=True (any token count, but effort must be max)
  3. --1m-context flag in delegate (covered by flag-existence test)
"""
from __future__ import annotations

import pytest


class TestShouldUse1mContext:
    """Unit tests for taxonomy.should_use_1m_context()."""

    def test_auto_promotion_above_threshold(self):
        """effort=max + 200_001 tokens → True (auto-promote)."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("max", 200_001) is True

    def test_auto_promotion_at_threshold_is_false(self):
        """effort=max + exactly 200_000 tokens → False (> not >=)."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("max", 200_000) is False

    def test_auto_promotion_below_threshold(self):
        """effort=max + 50_000 tokens → False."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("max", 50_000) is False

    def test_only_fires_for_max_effort(self):
        """effort=xhigh + 500_000 tokens → False (1m is max-only)."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("xhigh", 500_000) is False

    def test_non_max_efforts_never_promote(self):
        """low/medium/high never promote regardless of token count."""
        from superharness.engine.taxonomy import should_use_1m_context
        for effort in ("low", "medium", "high"):
            assert should_use_1m_context(effort, 1_000_000) is False, effort

    def test_context_1m_override_triggers_at_any_token_count(self):
        """context_1m=True overrides threshold when effort=max."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("max", 100, context_1m=True) is True

    def test_context_1m_override_ignored_for_non_max_effort(self):
        """context_1m=True has no effect when effort!=max."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("xhigh", 100, context_1m=True) is False

    def test_context_1m_false_does_not_block_auto_promotion(self):
        """context_1m=False still allows auto-promotion when tokens > threshold."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("max", 300_000, context_1m=False) is True

    def test_zero_tokens_never_promotes(self):
        """Zero token estimate → False (even with max effort)."""
        from superharness.engine.taxonomy import should_use_1m_context
        assert should_use_1m_context("max", 0) is False


class TestContractTaskContext1mField:
    """ContractTask schema must accept optional context_1m bool."""

    def test_context_1m_defaults_to_none(self):
        from superharness.engine.schemas import ContractTask
        task = ContractTask(
            id="t1", title="test", owner="claude-code",
            status="in_progress", effort="max",
        )
        assert task.context_1m is None

    def test_context_1m_true_accepted(self):
        from superharness.engine.schemas import ContractTask
        task = ContractTask(
            id="t1", title="test", owner="claude-code",
            status="in_progress", effort="max", context_1m=True,
        )
        assert task.context_1m is True

    def test_context_1m_false_accepted(self):
        from superharness.engine.schemas import ContractTask
        task = ContractTask(
            id="t1", title="test", owner="claude-code",
            status="in_progress", effort="max", context_1m=False,
        )
        assert task.context_1m is False


class TestDelegate1mContextFlag:
    """delegate CLI must expose --1m-context flag."""

    def test_delegate_argparse_has_1m_context_flag(self):
        """--1m-context is a registered argument in the delegate parser."""
        from superharness.commands.delegate import _build_parser
        parser = _build_parser()
        opts = parser.parse_args(["--to", "claude-code", "--1m-context"])
        assert opts.context_1m is True

    def test_delegate_1m_context_defaults_false(self):
        """--1m-context defaults to False when not supplied."""
        from superharness.commands.delegate import _build_parser
        parser = _build_parser()
        opts = parser.parse_args(["--to", "claude-code"])
        assert opts.context_1m is False
