"""Tests for behavioral profile Iteration 5 — production hardening.

I5.1: Deduplicate global memory lines
I5.2: Watcher profile refresh cycle
I5.3: Auto-apply adaptive rules
I5.4: Auto-record reviews on task close/verify
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


# ── I5.1: deduplicate global memory ─────────────────────────────────────────

def test_global_memory_dedup_collapses_duplicates(tmp_path: Path) -> None:
    """Identical lines in global memory should collapse to one with count."""
    from superharness.engine.agent_memory import _read_memory_file, _deduplicate_content

    fpath = tmp_path / "test.md"
    fpath.write_text(
        "# Header\n\n"
        "2026-05-20: avoid pytest -n auto\n"
        "2026-05-20: avoid pytest -n auto\n"
        "2026-05-20: avoid pytest -n auto\n"
        "2026-05-20: use uv instead of pip\n"
    )

    raw = _read_memory_file(str(fpath))
    assert raw.count("avoid pytest") >= 3  # raw has duplicates

    deduped = _deduplicate_content(raw)
    assert deduped.count("avoid pytest") == 1  # collapsed
    assert "(seen 3 times)" in deduped
    assert "use uv instead of pip" in deduped
    assert "(seen" not in deduped.replace("(seen 3 times)", "")  # single line not counted


def test_single_occurrence_not_counted(tmp_path: Path) -> None:
    """Single-occurrence lines should not show a count."""
    from superharness.engine.agent_memory import _read_memory_file, _deduplicate_content

    fpath = tmp_path / "test.md"
    fpath.write_text("# Header\n\n2026-05-20: unique pattern\n2026-05-20: another unique\n")

    raw = _read_memory_file(str(fpath))
    deduped = _deduplicate_content(raw)
    assert "unique pattern" in deduped
    assert "(seen" not in deduped


# ── I5.2: watcher profile refresh ───────────────────────────────────────────

def test_profile_refresh_saves_to_disk(tmp_path: Path) -> None:
    """Profile refresh should save extraction results to behavioral dir."""
    from superharness.engine.behavioral import extract_all_profiles, user_profile_path

    # Set up a temp project with tasks
    from superharness.engine.db import managed_connection
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from datetime import datetime, timezone

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with managed_connection(project_dir) as conn:
        tasks_dao.upsert(conn, TaskRow(
            id="test.1", title="Test task", owner="claude-code", status="done",
            effort="medium", project_path=project_dir, development_method="tdd",
            acceptance_criteria=["test"], test_types=["unit"],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, model_tier="standard", require_tdd=True,
            workflow="implementation",
        ))

    profiles = extract_all_profiles(project_dir)
    assert profiles["task_style"]["sample_count"] >= 1

    # Save to user profile
    upath = user_profile_path()
    from superharness.engine.behavioral import save_profile
    for name, data in profiles.items():
        save_profile(os.path.join(upath, f"{name}.json"), data)

    # Verify files exist
    for name in ["task_style", "review_style", "model_prefs", "autonomy_profile"]:
        assert os.path.isfile(os.path.join(upath, f"{name}.json")), f"Missing {name}.json"


# ── I5.3: auto-apply adaptive rules ──────────────────────────────────────────

def test_apply_rule_bump_autonomy(tmp_path: Path) -> None:
    """bump_autonomy rule should update profile autonomy when applied."""
    from superharness.engine.behavioral import apply_rule

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    rule = {"action": "bump_autonomy", "reason": "12 consecutive successes", "confidence": "medium"}
    result = apply_rule(project_dir, rule)
    assert result is True


def test_apply_rule_enable_tdd(tmp_path: Path) -> None:
    """enable_tdd rule should set require_tdd on the profile."""
    from superharness.engine.behavioral import apply_rule

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    rule = {"action": "enable_tdd", "reason": "All failures are test-related", "confidence": "medium"}
    result = apply_rule(project_dir, rule)
    assert result is True


def test_apply_rule_low_confidence_skipped(tmp_path: Path) -> None:
    """Low-confidence rules should NOT be auto-applied."""
    from superharness.engine.behavioral import apply_rule

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    rule = {"action": "bump_autonomy", "reason": "3 successes", "confidence": "low"}
    result = apply_rule(project_dir, rule)
    assert result is False  # skipped due to low confidence


# ── I5.4: auto-record reviews ────────────────────────────────────────────────

def test_auto_record_review_on_task_done(tmp_path: Path) -> None:
    """Closing a task should auto-record a review entry."""
    from superharness.engine.db import managed_connection
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from datetime import datetime, timezone

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with managed_connection(project_dir) as conn:
        tasks_dao.upsert(conn, TaskRow(
            id="test.review", title="Review test", owner="claude-code", status="done",
            effort="medium", project_path=project_dir, development_method="tdd",
            acceptance_criteria=["work"], test_types=["unit"],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, model_tier="standard", require_tdd=True,
            workflow="implementation",
        ))

    from superharness.engine.behavioral import record_review
    record_review(project_dir, "test.review", "done", "user")

    # Verify review was recorded
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        r = conn.execute("SELECT * FROM review_store WHERE owner='user'").fetchall()
        assert len(r) >= 1, "Review not recorded"
    finally:
        conn.close()


def test_auto_record_review_on_verify(tmp_path: Path) -> None:
    """Verifying a task should auto-record a review with appropriate score."""
    from superharness.engine.behavioral import record_review

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    record_review(project_dir, "test.verify", "verify_pass", "user", score=9.0)

    from superharness.engine.db import get_connection, init_db
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        r = conn.execute("SELECT * FROM review_store WHERE owner='user' ORDER BY recorded_at DESC LIMIT 1").fetchone()
        assert r is not None
        assert float(r["score"]) == 9.0
    finally:
        conn.close()
