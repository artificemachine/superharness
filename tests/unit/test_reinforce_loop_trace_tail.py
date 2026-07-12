"""Functional tests: _reinforce_loop's trace.jsonl learning step, tail-bounded.

Confirms the _tail_lines rewiring (see test_tail_lines.py) did not change
observable behavior for the normal case: an agent paused >= 3 times within
the tail window still gets a reinforce_learning/agent_deprioritized event.

Also pins the deliberate behavior change: a pause event OUTSIDE the tail
window (i.e., old enough to have scrolled off _REINFORCE_TRACE_TAIL_LINES)
must not count toward the threshold. Previously pause counting was
all-time/unbounded; see the comment above the call site in inbox_watch.py
for why that was itself a latent bug, not just a performance cost.
"""
from __future__ import annotations

import json
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


def _write_trace(project: Path, events: list[dict]) -> Path:
    trace_file = project / ".superharness" / "trace.jsonl"
    with trace_file.open("w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return trace_file


def _pause_event(agent: str) -> dict:
    return {"timestamp": "2026-07-11T09:00:00Z", "type": "reinforce_agent_pause", "agent": agent}


def _read_trace_types(project: Path) -> list[str]:
    trace_file = project / ".superharness" / "trace.jsonl"
    if not trace_file.exists():
        return []
    return [json.loads(line).get("type") for line in trace_file.read_text().splitlines() if line.strip()]


class TestReinforceLoopTraceTail:
    def test_agent_paused_three_times_within_tail_gets_deprioritized(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _reinforce_loop
        project = _make_project(tmp_path)
        _write_trace(project, [_pause_event("codex-cli")] * 3)

        _reinforce_loop(str(project))

        types = _read_trace_types(project)
        assert "reinforce_learning" in types

    def test_agent_paused_only_twice_is_not_flagged(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _reinforce_loop
        project = _make_project(tmp_path)
        _write_trace(project, [_pause_event("codex-cli")] * 2)

        _reinforce_loop(str(project))

        types = _read_trace_types(project)
        assert "reinforce_learning" not in types

    def test_pause_events_older_than_the_tail_window_do_not_count(self, tmp_path: Path):
        """The deliberate behavior change. 3 pause events exist in the file,
        but they are pushed out of the tail window by filler events, so the
        agent must NOT be flagged — recency-scoped counting, not all-time."""
        from superharness.commands.inbox_watch import _reinforce_loop, _REINFORCE_TRACE_TAIL_LINES
        project = _make_project(tmp_path)

        events = [_pause_event("codex-cli")] * 3
        # Push the pause events out of the tail window with filler.
        events += [{"timestamp": "2026-07-11T09:00:01Z", "type": "process_recovery"}] * (
            _REINFORCE_TRACE_TAIL_LINES + 10
        )
        _write_trace(project, events)

        _reinforce_loop(str(project))

        types = _read_trace_types(project)
        assert "reinforce_learning" not in types

    def test_completes_quickly_on_a_large_trace_file(self, tmp_path: Path):
        """Regression guard for the actual live incident: a large trace.jsonl
        must not make a single tick expensive. Loose bound (5s) to stay
        robust across machines while still catching an accidental revert to
        full-file reads (which took multiple seconds against 181 MB live)."""
        import time
        from superharness.commands.inbox_watch import _reinforce_loop

        project = _make_project(tmp_path)
        events = [{"timestamp": "2026-07-11T09:00:00Z", "type": "process_recovery", "i": i} for i in range(200_000)]
        _write_trace(project, events)

        start = time.monotonic()
        _reinforce_loop(str(project))
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"_reinforce_loop took {elapsed:.2f}s against a large trace file"
