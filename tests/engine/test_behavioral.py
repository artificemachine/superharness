"""Tests for behavioral profile engine — RED tests for Iteration 4.

Covers: extraction, confidence scoring, EWMA decay, hysteresis, adaptive rules,
project/user separation, context sizing, CLI visibility.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def behavioral():
    from superharness.engine import behavioral
    return behavioral


# ── RED: profile extraction ──────────────────────────────────────────────────

def test_extract_task_style(behavioral, tmp_path: Path) -> None:
    """Should extract task decomposition patterns from SQLite."""
    profile = behavioral.extract_task_style(str(tmp_path))
    assert isinstance(profile, dict)
    assert "default_effort" in profile
    assert "tdd_required" in profile
    assert "test_types" in profile
    assert "confidence" in profile
    assert "sample_count" in profile


def test_extract_review_style(behavioral, tmp_path: Path) -> None:
    """Should extract review strictness from review_store."""
    profile = behavioral.extract_review_style(str(tmp_path))
    assert isinstance(profile, dict)
    assert "strictness" in profile
    assert "sample_count" in profile


def test_extract_model_prefs(behavioral, tmp_path: Path) -> None:
    """Should extract model preferences by task type."""
    profile = behavioral.extract_model_prefs(str(tmp_path))
    assert isinstance(profile, dict)


def test_extract_autonomy_profile(behavioral, tmp_path: Path) -> None:
    """Should extract autonomy calibration from task history."""
    profile = behavioral.extract_autonomy_profile(str(tmp_path))
    assert isinstance(profile, dict)


def test_extract_all_profiles(behavioral, tmp_path: Path) -> None:
    """Should extract all profile types in one call."""
    profiles = behavioral.extract_all_profiles(str(tmp_path))
    assert "task_style" in profiles
    assert "review_style" in profiles
    assert "model_prefs" in profiles
    assert "autonomy_profile" in profiles


# ── RED: confidence scoring ──────────────────────────────────────────────────

def test_confidence_low_for_few_samples(behavioral) -> None:
    """Confidence should be 'low' when sample_count < 5."""
    assert behavioral.confidence_level(2) == "low"
    assert behavioral.confidence_level(0) == "low"


def test_confidence_medium_for_moderate_samples(behavioral) -> None:
    """Confidence should be 'medium' when 5–20 samples."""
    assert behavioral.confidence_level(5) == "medium"
    assert behavioral.confidence_level(12) == "medium"
    assert behavioral.confidence_level(20) == "medium"


def test_confidence_high_for_many_samples(behavioral) -> None:
    """Confidence should be 'high' when sample_count > 20."""
    assert behavioral.confidence_level(21) == "high"
    assert behavioral.confidence_level(100) == "high"


# ── RED: EWMA decay ──────────────────────────────────────────────────────────

def test_ewma_weight_recent_stronger(behavioral) -> None:
    """EWMA should give higher weight to recent data."""
    w1 = behavioral.ewma_weight(age_days=1, halflife_days=30)
    w2 = behavioral.ewma_weight(age_days=60, halflife_days=30)
    assert w1 > w2


def test_ewma_weight_zero_for_very_old(behavioral) -> None:
    """EWMA weight should approach zero for data older than 5x halflife."""
    w = behavioral.ewma_weight(age_days=300, halflife_days=30)
    assert w < 0.01


# ── RED: hysteresis ──────────────────────────────────────────────────────────

def test_hysteresis_no_change_in_neutral_zone(behavioral) -> None:
    """Hysteresis should return None (no change) in neutral zone."""
    # 5 successes, 1 failure → neutral (between upgrade=10 and downgrade=3)
    result = behavioral.hysteresis_check(
        successes=5, failures=1,
        upgrade_threshold=10, downgrade_threshold=3,
    )
    assert result == "neutral"


def test_hysteresis_upgrade_on_success(behavioral) -> None:
    """Hysteresis should return 'upgrade' when above threshold."""
    result = behavioral.hysteresis_check(
        successes=12, failures=0,
        upgrade_threshold=10, downgrade_threshold=3,
    )
    assert result == "upgrade"


def test_hysteresis_downgrade_on_failure(behavioral) -> None:
    """Hysteresis should return 'downgrade' when below threshold."""
    result = behavioral.hysteresis_check(
        successes=1, failures=5,
        upgrade_threshold=10, downgrade_threshold=3,
    )
    assert result == "downgrade"


# ── RED: adaptive rules ──────────────────────────────────────────────────────

def test_rule_autonomous_success_bumps_autonomy(behavioral) -> None:
    """10 consecutive autonomous successes should bump autonomy up."""
    rules = behavioral.evaluate_rules(
        project_dir="/tmp",
        task_history={"autonomous_successes": 10, "autonomous_failures": 0},
        review_history={"avg_score": 8.5, "recent_failures": 0},
    )
    assert any(r["action"] == "bump_autonomy" for r in rules)


def test_rule_repeated_rejection_lowers_autonomy(behavioral) -> None:
    """4 of last 5 plans rejected should lower autonomy."""
    rules = behavioral.evaluate_rules(
        project_dir="/tmp",
        task_history={"plan_rejections": 4, "plan_approvals": 1},
        review_history={},
    )
    assert any(r["action"] == "lower_autonomy" for r in rules)


def test_rule_high_quality_relaxes_review(behavioral) -> None:
    """Reviews averaging >8/10 should relax review gate."""
    rules = behavioral.evaluate_rules(
        project_dir="/tmp",
        task_history={},
        review_history={"review_count": 10, "avg_score": 8.5, "failures": 0},
    )
    assert any(r["action"] == "relax_review" for r in rules)


# ── RED: project/user separation ─────────────────────────────────────────────

def test_user_profile_stored_globally(behavioral) -> None:
    """User profile should be stored in ~/.config/superharness/behavioral/"""
    path = behavioral.user_profile_path()
    assert ".config" in path
    assert "behavioral" in path


def test_project_profile_stored_locally(behavioral, tmp_path: Path) -> None:
    """Project profile should be stored in .superharness/behavioral/"""
    path = behavioral.project_profile_path(str(tmp_path))
    assert ".superharness" in path
    assert "behavioral" in path


def test_project_promotes_to_user_after_threshold(behavioral) -> None:
    """Identical project pattern across 3 projects should promote to user."""
    result = behavioral.should_promote_to_user(
        pattern_key="conventions.formatter",
        project_count=3,
        threshold=3,
    )
    assert result is True


def test_project_not_promoted_below_threshold(behavioral) -> None:
    """Pattern in <3 projects should NOT promote to user."""
    result = behavioral.should_promote_to_user(
        pattern_key="conventions.formatter",
        project_count=2,
        threshold=3,
    )
    assert result is False


# ── RED: context sizing ──────────────────────────────────────────────────────

def test_profile_tier_summary_always_fits(behavioral) -> None:
    """Summary tier should be 1-2 sentences, safe for all models."""
    profile = {"task_style": {"default_effort": "medium", "tdd_required": True}}
    text = behavioral.format_profile_for_context(profile, tier="summary")
    assert len(text) < 500
    assert "TDD" in text


def test_profile_tier_full_includes_all(behavioral) -> None:
    """Full tier should include complete profile."""
    profile = {"task_style": {"default_effort": "medium"}, "review_style": {"strictness": 0.7}}
    text = behavioral.format_profile_for_context(profile, tier="full")
    assert "medium" in text
    assert "strictness" in text


# ── RED: serialization ───────────────────────────────────────────────────────

def test_save_and_load_profile(behavioral, tmp_path: Path) -> None:
    """Profile should round-trip through JSON serialization."""
    profile = {
        "task_style": {
            "default_effort": "medium",
            "tdd_required": True,
            "confidence": "medium",
            "sample_count": 10,
            "updated_at": "2026-05-21T00:00:00Z",
        }
    }
    behavioral.save_profile(tmp_path / "test.json", profile)
    loaded = behavioral.load_profile(tmp_path / "test.json")
    assert loaded["task_style"]["default_effort"] == "medium"
    assert loaded["task_style"]["tdd_required"] is True


def test_empty_profile_graceful(behavioral, tmp_path: Path) -> None:
    """Loading a missing profile should return empty dict, not crash."""
    profile = behavioral.load_profile(tmp_path / "nonexistent.json")
    assert profile == {}
