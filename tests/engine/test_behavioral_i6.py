"""Tests for behavioral profile Iteration 6 — verification feedback loop.

A/B test every profile change: compare task success rate before/after.
Reinforce changes that help, revert changes that hurt.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ── Trial lifecycle ──────────────────────────────────────────────────────────

def test_start_trial_records_baseline(tmp_path: Path) -> None:
    """start_trial should record a profile_trials row with baseline."""
    from superharness.engine.behavioral import start_trial
    import time

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    # Seed some task history for baseline
    _seed_tasks(project_dir, done=8, failed=2)
    time.sleep(1)

    trial_id = start_trial(
        project_dir,
        profile_key="autonomy",
        old_value="supervised",
        new_value="autonomous",
        baseline_success_rate=0.8,
    )

    assert trial_id is not None
    assert trial_id > 0

    # Verify it's in the DB
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        r = conn.execute(
            "SELECT * FROM profile_trials WHERE id = ?", (trial_id,)
        ).fetchone()
        assert r is not None
        assert r["profile_key"] == "autonomy"
        assert r["old_value"] == "supervised"
        assert r["new_value"] == "autonomous"
        assert r["outcome"] is None  # not yet evaluated
    finally:
        conn.close()


def test_evaluate_trial_detects_improvement(tmp_path: Path) -> None:
    """evaluate_trial should return 'improved' when trial beats baseline."""
    from superharness.engine.behavioral import start_trial, evaluate_trial
    import time
    from datetime import datetime, timezone, timedelta
    import time

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    _seed_tasks(project_dir, done=8, failed=2)
    time.sleep(1)  # ensure trial timestamp is after baseline tasks

    trial_id = start_trial(
        project_dir, "autonomy", "supervised", "autonomous",
        baseline_success_rate=0.8,
    )
    time.sleep(1)

    # Simulate: after trial, 5 more tasks complete with high success
    _seed_tasks(project_dir, done=5, failed=0, prefix="trial_")

    result = evaluate_trial(project_dir, trial_id)
    assert result == "improved"


def test_evaluate_trial_detects_degradation(tmp_path: Path) -> None:
    """evaluate_trial should return 'degraded' when trial is worse than baseline."""
    from superharness.engine.behavioral import start_trial, evaluate_trial
    import time

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    _seed_tasks(project_dir, done=8, failed=2)
    time.sleep(1)

    trial_id = start_trial(
        project_dir, "autonomy", "supervised", "autonomous",
        baseline_success_rate=0.8,
    )

    # Simulate: after trial, 5 tasks complete with low success
    _seed_tasks(project_dir, done=2, failed=3, prefix="trial_")

    result = evaluate_trial(project_dir, trial_id)
    assert result == "degraded"


def test_complete_trial_reinforces_improvement(tmp_path: Path) -> None:
    """complete_trial should mark outcome and NOT revert improved changes."""
    from superharness.engine.behavioral import start_trial, complete_trial
    import time

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    _seed_tasks(project_dir, done=8, failed=2)
    trial_id = start_trial(
        project_dir, "autonomy", "supervised", "autonomous", 0.8,
    )
    _seed_tasks(project_dir, done=5, failed=0, prefix="trial_")

    result = complete_trial(project_dir, trial_id)
    assert result["outcome"] == "improved"
    assert result["reverted"] is False
    assert result["reinforced"] is True


def test_complete_trial_reverts_degradation(tmp_path: Path) -> None:
    """complete_trial should revert degraded changes."""
    from superharness.engine.behavioral import start_trial, complete_trial
    import time

    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    _seed_tasks(project_dir, done=8, failed=2)
    trial_id = start_trial(
        project_dir, "model_prefs", "standard", "opus", 0.8,
    )
    _seed_tasks(project_dir, done=2, failed=3, prefix="trial_")

    result = complete_trial(project_dir, trial_id)
    assert result["outcome"] == "degraded"
    assert result["reverted"] is True
    assert result["reinforced"] is False


# ── Helper ───────────────────────────────────────────────────────────────────

def _seed_tasks(project_dir: str, done: int, failed: int, prefix: str = "") -> None:
    from superharness.engine.db import managed_connection
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from datetime import datetime, timezone, timedelta

    # Trial tasks get a future timestamp so evaluate_trial counts them separately
    offset = timedelta(seconds=10) if prefix else timedelta(seconds=0)
    now = (datetime.now(timezone.utc) + offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)

    with managed_connection(project_dir) as conn:
        for i in range(done):
            tasks_dao.upsert(conn, TaskRow(
                id=f"{prefix}done.{i}", title=f"Done {i}", owner="claude-code",
                status="done", effort="medium", project_path=project_dir,
                development_method=None, acceptance_criteria=[], test_types=[],
                out_of_scope=[], definition_of_done=[], context=None, tdd=None,
                version=1, created_at=now, model_tier="standard",
                workflow="implementation",
            ))
        for i in range(failed):
            tasks_dao.upsert(conn, TaskRow(
                id=f"{prefix}failed.{i}", title=f"Failed {i}", owner="claude-code",
                status="failed", effort="medium", project_path=project_dir,
                development_method=None, acceptance_criteria=[], test_types=[],
                out_of_scope=[], definition_of_done=[], context=None, tdd=None,
                version=1, created_at=now, model_tier="standard",
                workflow="implementation",
            ))
