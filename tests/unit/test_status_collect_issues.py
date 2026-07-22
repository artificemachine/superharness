"""Regression test: `_collect_issues` must not report a clean bill of health
when the retry-alert count is nonzero.

Found by /gauntlet Stage 5 (ux), 2026-07-22: `shux status` prints a
`retry-alert: threshold=3 high=46 ...` line, then unconditionally falls
through to "No issues found. All clean." two lines later — `retry_high`
was computed for the summary line but never passed into `_collect_issues`,
the function that decides whether any issues exist. A status command that
can contradict its own numbers is a real risk for anything gating
automation on it.
"""
from __future__ import annotations


def _empty_health():
    inbox_health = {
        "counts": {}, "orphaned": [], "duplicates": {}, "stale_pending": [],
        "stale_launched": [], "dead_pid": [], "discussion_orphans": [],
        "missing_task": [], "stale_items": [],
    }
    disc_health = {"counts": {}, "consensus_unclosed": [], "stale_active": []}
    task_health = {
        "counts": {}, "no_timestamp": [], "stuck_inprogress": [],
        "stuck_plan": [], "stuck_noreview": [], "stuck_waiting": [],
    }
    return inbox_health, disc_health, task_health


def test_collect_issues_flags_nonzero_retry_alert():
    from superharness.commands.status import _collect_issues

    inbox_health, disc_health, task_health = _empty_health()

    issues, fixes = _collect_issues(
        "/tmp/proj", "ok", "", "ok", "",
        inbox_health, disc_health, task_health,
        retry_high=2, retry_high_ids=["auto-abc123", "auto-def456"],
    )

    assert issues, "a nonzero retry-alert count must produce at least one issue"
    assert any("retry budget" in i for i in issues)


def test_collect_issues_clean_when_retry_high_is_zero():
    from superharness.commands.status import _collect_issues

    inbox_health, disc_health, task_health = _empty_health()

    issues, fixes = _collect_issues(
        "/tmp/proj", "ok", "", "ok", "",
        inbox_health, disc_health, task_health,
        retry_high=0, retry_high_ids=[],
    )

    assert issues == [], "zero retry-alert must not itself produce an issue"
