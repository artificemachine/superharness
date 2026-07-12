"""Unit tests: _should_run's cooldown must survive process boundaries.

Root cause (found live, 2026-07-11): _should_run gated auto-actions
(operator_memory, auto_retry, auto_fallback_owner, auto_recover,
auto_bootstrap, auto_enqueue_todo, auto_peer_approve,
auto_enqueue_approved, reinforce) with an in-memory dict, keyed by action
name, using time.monotonic(). The watcher that calls it is, by design, a
fresh Python process every tick (see watch(): `if once or not foreground:
_run_scripts(...)` — one cycle, exit 0, the operator respawns it). Every
fresh process starts with an empty dict, so `last = _AUTO_COOLDOWNS.get(
action, 0)` is always 0, so `now - 0 < threshold` is always False, so
_should_run returns True unconditionally on every single tick regardless
of the cooldown argument. A "runs every 5 minutes" gate does nothing when
the process living the loop line to line doesn't outlive one tick.

Confirmed live: reinforce's 300s cooldown claim was defeated this way,
causing a 181 MB trace.jsonl full re-parse (1.38M json.loads calls) on
every ~5-7s watcher tick instead of every 5 minutes.

The fix makes the cooldown state outlive the process: persisted per
(project, action) in the project's SQLite state, not process memory.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn)
    conn.close()
    return project


def _seed_last_run(project: Path, action: str, seconds_ago: float) -> None:
    """Directly write a persisted last-run timestamp, bypassing _should_run,
    to deterministically test 'cooldown elapsed' / 'cooldown not elapsed'
    without sleeping in the test."""
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        "INSERT INTO watcher_cooldowns (action, last_run_epoch) VALUES (?, ?) "
        "ON CONFLICT(action) DO UPDATE SET last_run_epoch = excluded.last_run_epoch",
        (action, time.time() - seconds_ago),
    )
    conn.commit()
    conn.close()


class TestShouldRunSurvivesProcessRespawn:
    def test_first_call_ever_runs(self, tmp_path: Path):
        """No prior record for this action: must run (never block on missing history)."""
        from superharness.commands.inbox_watch import _should_run
        project = _make_project(tmp_path)
        assert _should_run(str(project), "reinforce", cooldown=300) is True

    def test_a_fresh_process_respects_a_cooldown_recorded_by_an_earlier_process(self, tmp_path: Path):
        """This is the actual bug. The watcher is a NEW Python process every
        tick, so nothing about this test's own in-memory state may be relied
        on — the persisted row from _seed_last_run must be the only thing
        that makes _should_run return False here."""
        from superharness.commands.inbox_watch import _should_run
        project = _make_project(tmp_path)
        _seed_last_run(project, "reinforce", seconds_ago=10)  # ran 10s ago
        assert _should_run(str(project), "reinforce", cooldown=300) is False

    def test_cooldown_elapsed_runs_again(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _should_run
        project = _make_project(tmp_path)
        _seed_last_run(project, "reinforce", seconds_ago=301)  # just past 300s
        assert _should_run(str(project), "reinforce", cooldown=300) is True

    def test_running_updates_the_persisted_timestamp(self, tmp_path: Path):
        """A True return must itself persist, so the NEXT process (not just
        the current one) sees the updated last-run time."""
        from superharness.commands.inbox_watch import _should_run
        project = _make_project(tmp_path)
        assert _should_run(str(project), "reinforce", cooldown=300) is True
        # Immediately "restart" by calling again — simulates the next tick's
        # fresh process reading what THIS call wrote.
        assert _should_run(str(project), "reinforce", cooldown=300) is False

    def test_actions_are_independent(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _should_run
        project = _make_project(tmp_path)
        _seed_last_run(project, "reinforce", seconds_ago=1)
        # A different action with no record of its own must still run.
        assert _should_run(str(project), "auto_retry", cooldown=10) is True

    def test_projects_are_independent(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _should_run
        project_a = _make_project(tmp_path / "a")
        project_b = _make_project(tmp_path / "b")
        _seed_last_run(project_a, "reinforce", seconds_ago=1)
        # project_b has never run reinforce; project_a's cooldown must not leak.
        assert _should_run(str(project_b), "reinforce", cooldown=300) is True

    def test_default_cooldown_used_when_unspecified(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _should_run, _AUTO_DEFAULT_COOLDOWN
        project = _make_project(tmp_path)
        _seed_last_run(project, "some_action", seconds_ago=_AUTO_DEFAULT_COOLDOWN - 1)
        assert _should_run(str(project), "some_action") is False
        _seed_last_run(project, "some_action", seconds_ago=_AUTO_DEFAULT_COOLDOWN + 1)
        assert _should_run(str(project), "some_action") is True
