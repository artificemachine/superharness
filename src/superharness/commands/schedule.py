"""shux schedule — cron-like scheduled task dispatch.

Writes to `.superharness/scheduled.yaml`; the inbox watcher picks up entries
whose next_run time has passed and enqueues them automatically.

Subcommands:
  add    <task-id> --cron "H H * * *"   Register a recurring dispatch schedule
  list                                   Show all schedules and their next-run time
  remove <task-id>                       Remove a schedule
  run                                    Evaluate all schedules and enqueue due tasks (called by watcher)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional


_SCHEDULED_FILE = "scheduled.yaml"

# Imported at module level so tests can patch superharness.commands.schedule.inbox_enqueue
from superharness.commands import inbox_enqueue  # noqa: E402


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_str() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _scheduled_path(project_dir: str) -> str:
    return os.path.join(project_dir, ".superharness", _SCHEDULED_FILE)


def _load_schedules(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    import yaml
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("schedules", [])


def _save_schedules(path: str, schedules: list[dict]) -> None:
    import yaml
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"schedules": schedules}, f, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Minimal cron expression parser (minute hour dom month dow)
# Supports: * and integer values only — enough for common scheduling patterns.
# ---------------------------------------------------------------------------

_CRON_FIELDS = ("minute", "hour", "dom", "month", "dow")
_CRON_RANGES = {
    "minute": (0, 59),
    "hour":   (0, 23),
    "dom":    (1, 31),
    "month":  (1, 12),
    "dow":    (0, 6),
}


def _parse_cron(expr: str) -> dict:
    """Parse a 5-field cron expression into a dict of field→value|None (None = *)."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(parts)}: {expr!r}")
    result: dict[str, Optional[int]] = {}
    for field, part in zip(_CRON_FIELDS, parts):
        if part == "*":
            result[field] = None
        else:
            try:
                val = int(part)
            except ValueError:
                raise ValueError(f"cron field '{field}' must be '*' or an integer, got: {part!r}")
            lo, hi = _CRON_RANGES[field]
            if not (lo <= val <= hi):
                raise ValueError(f"cron field '{field}' value {val} out of range [{lo}, {hi}]")
            result[field] = val
    return result


def _next_run(cron_expr: str, after: datetime) -> datetime:
    """Return the next datetime after `after` that matches `cron_expr`."""
    parsed = _parse_cron(cron_expr)
    # Advance by 1 minute to ensure we find a time strictly after `after`
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Walk forward up to 527040 minutes (366 days) to find a match
    for _ in range(527040):
        match = (
            (parsed["minute"] is None or candidate.minute == parsed["minute"]) and
            (parsed["hour"]   is None or candidate.hour   == parsed["hour"])   and
            (parsed["dom"]    is None or candidate.day    == parsed["dom"])     and
            (parsed["month"]  is None or candidate.month  == parsed["month"])  and
            (parsed["dow"]    is None or candidate.weekday() % 7 == parsed["dow"])
        )
        if match:
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"Could not find next run time for cron expression: {cron_expr!r}")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


DISTILL_JOB_ID = "__distill__"


def cmd_add(project_dir: str, task_id: str, cron_expr: str,
            agent: Optional[str] = None, kind: str = "task") -> int:
    """Register a scheduled job (a task dispatch, or an internal job like distill)."""
    try:
        _parse_cron(cron_expr)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    path = _scheduled_path(project_dir)
    schedules = _load_schedules(path)

    # Update existing entry if task_id already registered
    for s in schedules:
        if s.get("task_id") == task_id:
            s["cron"] = cron_expr
            s["agent"] = agent
            s["kind"] = kind
            s["next_run"] = _next_run(cron_expr, _now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")
            s["updated_at"] = _now_str()
            _save_schedules(path, schedules)
            print(f"Updated schedule for {task_id}: {cron_expr}  next={s['next_run']}")
            return 0

    next_run = _next_run(cron_expr, _now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")
    schedules.append({
        "task_id": task_id,
        "kind": kind,
        "cron": cron_expr,
        "agent": agent,
        "next_run": next_run,
        "created_at": _now_str(),
        "enqueue_count": 0,
    })
    _save_schedules(path, schedules)
    print(f"Scheduled {task_id} ({kind}): {cron_expr}  next={next_run}")
    return 0


def add_distill_schedule(project_dir: str, cron_expr: str = "0 3 * * *") -> int:
    """Register the nightly memory-distillation job."""
    return cmd_add(project_dir, DISTILL_JOB_ID, cron_expr, agent=None, kind="distill")


def cmd_list(project_dir: str) -> int:
    """List all schedules and their next-run time."""
    path = _scheduled_path(project_dir)
    schedules = _load_schedules(path)
    if not schedules:
        print("No schedules.")
        return 0
    now = _now_utc()
    fmt = "{:<20} {:<18} {:<22} {:<6} {}"
    print(fmt.format("TASK", "CRON", "NEXT RUN", "COUNT", "AGENT"))
    print("-" * 80)
    for s in schedules:
        next_run = s.get("next_run", "?")
        # Indicate overdue schedules
        try:
            nr = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
            if nr < now:
                next_run += " (overdue)"
        except (ValueError, AttributeError):
            pass
        print(fmt.format(
            str(s.get("task_id", ""))[:20],
            str(s.get("cron", ""))[:18],
            next_run[:22],
            str(s.get("enqueue_count", 0)),
            str(s.get("agent") or ""),
        ))
    return 0


def cmd_remove(project_dir: str, task_id: str) -> int:
    """Remove a schedule entry."""
    path = _scheduled_path(project_dir)
    schedules = _load_schedules(path)
    before = len(schedules)
    schedules = [s for s in schedules if s.get("task_id") != task_id]
    if len(schedules) == before:
        print(f"No schedule found for task: {task_id}", file=sys.stderr)
        return 1
    _save_schedules(path, schedules)
    print(f"Removed schedule for {task_id}")
    return 0


def _in_quiet_window(now: datetime, quiet_hours: list[dict] | None) -> bool:
    """Return True if *now* falls inside any configured quiet window.

    Each entry in *quiet_hours* is a dict with ``start`` and ``end`` as
    "HH:MM" strings in UTC.  Example: ``[{"start": "22:00", "end": "06:00"}]``.
    """
    if not quiet_hours:
        return False
    now_hm = now.hour * 60 + now.minute
    for window in quiet_hours:
        try:
            sh, sm = (int(x) for x in window["start"].split(":"))
            eh, em = (int(x) for x in window["end"].split(":"))
        except (KeyError, ValueError, TypeError):
            continue
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        if start_m <= end_m:
            if start_m <= now_hm < end_m:
                return True
        else:
            if now_hm >= start_m or now_hm < end_m:
                return True
    return False


def _run_distill_job(project_dir: str) -> bool:
    """Run one distillation pass: gather → distill → apply → promote.

    Imported lazily so the schedule module stays light and tests can patch.
    Returns True when the job ran (regardless of how many lessons it produced).
    """
    from superharness.engine import distiller, agent_memory
    from superharness.commands.distill import default_llm_fn

    transcript = distiller.gather_candidates(project_dir, since_days=None)
    lessons = distiller.distill(transcript, llm_fn=default_llm_fn)
    agent_memory.apply_lessons(lessons, project_dir)
    agent_memory.promote_all_project_memory(project_dir)
    return True


def _fire(s: dict, project_dir: str, dry_run: bool) -> bool:
    """Execute one due schedule entry. Returns True if it fired (non-dry-run)."""
    kind = s.get("kind", "task")
    if kind == "distill":
        if dry_run:
            print("[dry-run] would run memory distillation")
            return False
        if _run_distill_job(project_dir):
            print("Ran scheduled distillation")
            return True
        return False

    # Default: task dispatch.
    task_id = s.get("task_id")
    agent = s.get("agent")
    if dry_run:
        print(f"[dry-run] would enqueue: {task_id} (agent={agent or 'auto'})")
        return False
    rc = inbox_enqueue.main(
        ["--project", project_dir, "--task", task_id] + (["--to", agent] if agent else [])
    )
    if rc == 0:
        print(f"Enqueued scheduled task: {task_id}")
        return True
    return False


def cmd_run(project_dir: str, dry_run: bool = False,
            quiet_hours: list[dict] | None = None) -> int:
    """Evaluate all schedules; fire any whose next_run has passed.

    Called by the watcher (or manually). Each due entry fires by kind
    (task dispatch or internal job). A firing failure is logged but never
    wedges the watcher — next_run still advances so the job retries next cycle.
    """
    path = _scheduled_path(project_dir)
    schedules = _load_schedules(path)
    if not schedules:
        print("No schedules.")
        return 0

    now = _now_utc()
    fired_count = 0
    updated = False

    if _in_quiet_window(now, quiet_hours):
        print("Quiet window active — skipping scheduled dispatch.")
        return 0

    for s in schedules:
        task_id = s.get("task_id")
        cron_expr = s.get("cron")
        next_run_str = s.get("next_run")

        if not task_id or not cron_expr or not next_run_str:
            continue

        try:
            next_run = datetime.fromisoformat(next_run_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        if next_run > now:
            continue  # not due yet

        try:
            if _fire(s, project_dir, dry_run):
                fired_count += 1
        except Exception as e:  # never let one job wedge the watcher
            import logging
            logging.getLogger(__name__).warning(
                "scheduled job %s failed: %s", task_id, e
            )

        # Advance next_run regardless of fire outcome (failures retry next cycle).
        if not dry_run:
            try:
                s["next_run"] = _next_run(cron_expr, now).strftime("%Y-%m-%dT%H:%M:%SZ")
                s["enqueue_count"] = int(s.get("enqueue_count", 0)) + 1
                s["last_enqueued_at"] = _now_str()
                updated = True
            except ValueError:
                pass

    if updated and not dry_run:
        _save_schedules(path, schedules)

    print(f"Scheduled run complete: {fired_count} fired, {len(schedules)} total schedules")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="schedule",
        description="superharness scheduled dispatch (cron-like task runner)",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="subcmd")

    # add
    p = sub.add_parser("add", help="Register a cron schedule for a task")
    p.add_argument("task_id", help="Task ID to schedule")
    p.add_argument("--cron", required=True, help='5-field cron expression, e.g. "0 9 * * 1"')
    p.add_argument("--agent", default=None, help="Target agent (claude-code or codex-cli)")
    p.add_argument("--project", "-p", default=None)

    # list
    p = sub.add_parser("list", help="Show all schedules")
    p.add_argument("--project", "-p", default=None)

    # remove
    p = sub.add_parser("remove", help="Remove a schedule")
    p.add_argument("task_id", help="Task ID to remove")
    p.add_argument("--project", "-p", default=None)

    # run
    p = sub.add_parser("run", help="Fire any due schedules (called by watcher)")
    p.add_argument("--dry-run", action="store_true", help="Preview without enqueuing")
    p.add_argument("--project", "-p", default=None)

    opts = parser.parse_args(argv)
    if not opts.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    project_dir = os.path.realpath(getattr(opts, "project", None) or os.getcwd())

    if opts.subcmd == "add":
        rc = cmd_add(project_dir, opts.task_id, opts.cron, opts.agent)
    elif opts.subcmd == "list":
        rc = cmd_list(project_dir)
    elif opts.subcmd == "remove":
        rc = cmd_remove(project_dir, opts.task_id)
    elif opts.subcmd == "run":
        rc = cmd_run(project_dir, dry_run=opts.dry_run)
    else:
        print(f"Unknown subcommand: {opts.subcmd}", file=sys.stderr)
        rc = 2

    return rc


if __name__ == "__main__":
    sys.exit(main())
