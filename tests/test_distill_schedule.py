"""Iteration 5 — schedulable nightly distillation.

A `kind: "distill"` schedule entry runs distillation via the existing watcher
loop (cmd_run), honoring quiet hours, advancing next_run even on failure, and
leaving existing task-id schedules untouched.
"""
from __future__ import annotations

from datetime import timedelta

from superharness.commands import schedule
from superharness.commands import distill as distill_cmd


def _past_iso():
    return (schedule._now_utc() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_due(project_dir, entry):
    path = schedule._scheduled_path(str(project_dir))
    entry.setdefault("cron", "0 3 * * *")
    entry["next_run"] = _past_iso()
    schedule._save_schedules(path, [entry])
    return path


def test_register_internal_job(clean_harness):
    """`shux distill --schedule` registers a kind=distill entry."""
    rc = distill_cmd.main(["--project", str(clean_harness), "--schedule", "0 3 * * *"])
    assert rc == 0
    schedules = schedule._load_schedules(schedule._scheduled_path(str(clean_harness)))
    distill_jobs = [s for s in schedules if s.get("kind") == "distill"]
    assert len(distill_jobs) == 1
    assert distill_jobs[0]["cron"] == "0 3 * * *"


def test_schedule_default_cron(clean_harness):
    """Bare --schedule uses the 3am default."""
    distill_cmd.main(["--project", str(clean_harness), "--schedule"])
    schedules = schedule._load_schedules(schedule._scheduled_path(str(clean_harness)))
    assert any(s.get("cron") == "0 3 * * *" for s in schedules if s.get("kind") == "distill")


def test_run_fires_due_distill(clean_harness, monkeypatch):
    """cmd_run invokes the distill job when due and advances next_run."""
    fired = {"n": 0}
    monkeypatch.setattr(schedule, "_run_distill_job", lambda pd: fired.__setitem__("n", fired["n"] + 1) or True)
    path = _write_due(clean_harness, {"task_id": "__distill__", "kind": "distill"})

    schedule.cmd_run(str(clean_harness))
    assert fired["n"] == 1
    after = schedule._load_schedules(path)[0]
    assert after["next_run"] > _past_iso()  # advanced


def test_quiet_window_skips(clean_harness, monkeypatch):
    """Distill job respects quiet hours."""
    fired = {"n": 0}
    monkeypatch.setattr(schedule, "_run_distill_job", lambda pd: fired.__setitem__("n", fired["n"] + 1) or True)
    _write_due(clean_harness, {"task_id": "__distill__", "kind": "distill"})
    # A quiet window covering the entire day.
    schedule.cmd_run(str(clean_harness), quiet_hours=[{"start": "00:00", "end": "23:59"}])
    assert fired["n"] == 0


def test_existing_task_schedules_unchanged(clean_harness, monkeypatch):
    """A plain task schedule still enqueues via inbox_enqueue."""
    calls = {"n": 0}
    monkeypatch.setattr(schedule.inbox_enqueue, "main", lambda argv: calls.__setitem__("n", calls["n"] + 1) or 0)
    _write_due(clean_harness, {"task_id": "real-task", "agent": "claude-code"})
    schedule.cmd_run(str(clean_harness))
    assert calls["n"] == 1


def test_distill_exception_advances_next_run(clean_harness, monkeypatch):
    """A failing distill job does not wedge the watcher; next_run still advances."""
    def boom(pd):
        raise RuntimeError("distill blew up")

    monkeypatch.setattr(schedule, "_run_distill_job", boom)
    path = _write_due(clean_harness, {"task_id": "__distill__", "kind": "distill"})
    rc = schedule.cmd_run(str(clean_harness))  # must not raise
    assert rc == 0
    after = schedule._load_schedules(path)[0]
    assert after["next_run"] > _past_iso()
