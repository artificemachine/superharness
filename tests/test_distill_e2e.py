"""Iteration 5 — full distillation loop end to end.

Seed the cheap write path (handoffs+ledger) → scheduled distill job runs →
lesson lands capped+tagged in project pitfalls.md → promotion is invoked →
the lesson injects into dispatch context, and a fresh recall hit has no caveat.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from superharness.commands import schedule
from superharness.engine import agent_memory, recall


def test_full_loop_with_promotion(clean_harness, monkeypatch):
    from tests.helpers import seed_sqlite_handoff, seed_sqlite_ledger

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seed_sqlite_handoff(clean_harness, "t1", content="decided SQLite is the single source of truth", now=now)
    seed_sqlite_ledger(clean_harness, action="VERIFY passed for t1", now=now)

    # Deterministic LLM: one durable lesson.
    monkeypatch.setattr(
        "superharness.commands.distill.default_llm_fn",
        lambda s, u: '{"lessons": [{"text": "SQLite is the SSOT", "type": "project", "confidence": 0.9}]}',
    )

    # Spy on promotion to confirm the nightly job invokes it.
    promoted = {"n": 0}
    real_promote = agent_memory.promote_all_project_memory
    monkeypatch.setattr(
        agent_memory, "promote_all_project_memory",
        lambda pd: promoted.__setitem__("n", promoted["n"] + 1) or real_promote(pd),
    )

    # Register a due distill schedule and fire it through the watcher path.
    path = schedule._scheduled_path(str(clean_harness))
    past = (schedule._now_utc() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    schedule._save_schedules(path, [{"task_id": "__distill__", "kind": "distill",
                                     "cron": "0 3 * * *", "next_run": past}])
    schedule.cmd_run(str(clean_harness))

    # 1. lesson landed in project pitfalls.md, confidence-tagged
    pitfalls = Path(agent_memory.project_memory_dir(str(clean_harness))) / "pitfalls.md"
    text = pitfalls.read_text()
    assert "SQLite is the SSOT" in text
    assert "src=distill" in text

    # 2. promotion was invoked by the nightly job
    assert promoted["n"] == 1

    # 3. lesson injects into dispatch context
    ctx = agent_memory.get_dispatch_memory_context(str(clean_harness))
    assert "SQLite is the SSOT" in ctx

    # 4. fresh recall hit (the seeded handoff) carries no staleness caveat
    out = recall.format_results(recall.search(Path(str(clean_harness)), ["sqlite"]), max_fresh_days=14)
    assert "days old" not in out
