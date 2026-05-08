"""End-to-end test: the runaway-retry bug we observed in production.

Reproduces the exact pathology that produced max_retries=65 with 3
stale inbox items for a single discussion task:

  - Discussion directory missing → every dispatch fails identically
  - Pre-fix: failed_reason='unknown: unclassified...' wiped the
    'recovery_N' marker each cycle, so auto-recover bumped max_retries
    forever and never escalated.
  - Post-fix: recovery_count lives in its own column, max_retries has
    an absolute ceiling, and identical-error loops escalate the task
    to waiting_input.

Also verifies operator memory now learns from these unclassified
failures via the unknown:<hash> signature path.
"""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine.failure_patterns import (
    record_failure,
    unknown_signature,
)
from superharness.engine.operator_memory import OperatorMemory
from superharness.commands.inbox_watch import (
    _ABSOLUTE_MAX_RETRIES,
    _IDENTICAL_FAILURE_THRESHOLD,
    _auto_recover_exhausted_failures_sqlite,
)


NOW = "2026-05-08T00:00:00Z"
SNIPPET = (
    "Discussion directory not found: "
    "/proj/.superharness/discussions/discuss-xyz"
)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    (p / ".superharness").mkdir(parents=True)
    conn = get_connection(str(p))
    init_db(conn, str(p))
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at) "
        "VALUES ('discuss-xyz/round-1', 'd', 'claude-code', 'in_progress', ?, ?)",
        (NOW, NOW),
    )
    # Three inbox items mirror the real production state: one per agent,
    # all failed with the same unknown error.
    for i, agent in enumerate(("claude-code", "codex-cli", "gemini-cli")):
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, "
            "max_retries, recovery_count, failed_reason, created_at) "
            "VALUES (?, 'discuss-xyz/round-1', ?, 'failed', 3, 3, 0, "
            "'unknown: unclassified failure (exit code 1)', ?)",
            (f"i{i}", agent, NOW),
        )
    conn.commit()
    conn.close()
    return str(p)


def test_e2e_identical_error_loop_escalates_after_threshold(project):
    """Simulate the production failure pattern. After enough identical
    failures recorded against the task, the next auto_recover cycle
    must escalate to waiting_input — no infinite reroutes."""
    # Record N identical failures in the failures table (this is what
    # the dispatcher does on every failed launch).
    for _ in range(_IDENTICAL_FAILURE_THRESHOLD + 1):
        record_failure(project, "discuss-xyz/round-1", SNIPPET, agent="claude-code")

    _auto_recover_exhausted_failures_sqlite(project)

    conn = get_connection(project)
    try:
        task_status = conn.execute(
            "SELECT status FROM tasks WHERE id='discuss-xyz/round-1'"
        ).fetchone()["status"]
        # All inbox rows for this task should now be closed (status=failed
        # with escalated reason); none in pending/launched.
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM inbox "
            "WHERE task_id='discuss-xyz/round-1' "
            "AND status IN ('pending','launched','running')"
        ).fetchone()["n"]
    finally:
        conn.close()

    assert task_status == "waiting_input"
    assert active == 0


def test_e2e_max_retries_never_grows_past_ceiling(project):
    """If we keep cycling auto_recover the inbox max_retries must never
    exceed _ABSOLUTE_MAX_RETRIES — the production runaway hit 65."""
    # Drive auto_recover repeatedly. Each cycle a re-routed row is
    # marked failed again so the next cycle re-enters auto_recover.
    conn = get_connection(project)
    try:
        for _ in range(_ABSOLUTE_MAX_RETRIES + 5):
            _auto_recover_exhausted_failures_sqlite(project)
            # Mark every pending row as failed again to simulate the
            # next dispatch failing with the same unknown error.
            conn.execute(
                "UPDATE inbox SET status='failed', retry_count=max_retries, "
                "failed_reason='unknown: unclassified failure (exit code 1)' "
                "WHERE status='pending'"
            )
            conn.commit()

        max_seen = conn.execute(
            "SELECT MAX(max_retries) AS m FROM inbox "
            "WHERE task_id='discuss-xyz/round-1'"
        ).fetchone()["m"]
    finally:
        conn.close()

    assert max_seen <= _ABSOLUTE_MAX_RETRIES, (
        f"max_retries grew to {max_seen}, ceiling was {_ABSOLUTE_MAX_RETRIES}"
    )


def test_e2e_operator_memory_learns_from_unclassified_error(project):
    """The dominant production failure was an unclassified 'Discussion
    directory not found' error. Memory must seed an entry for it via
    the unknown:<hash> signature so the watcher can detect repeats."""
    record_failure(project, "discuss-xyz/round-1", SNIPPET, agent="claude-code")

    db_path = f"{project}/.superharness/state.sqlite3"
    om = OperatorMemory(db_path)
    sig = unknown_signature(SNIPPET)
    entry = om.find_pattern(sig)
    assert entry is not None
    # Resolution captures the first line of the error so a human can
    # read the dashboard pill and immediately know the fix.
    assert "Discussion directory not found" in entry["resolution"]
