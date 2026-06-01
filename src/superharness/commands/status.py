"""status command — full project health dashboard. One command, complete picture."""
from __future__ import annotations

import glob
import os
import platform
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

from superharness.engine.yaml_helpers import safe_load

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Watcher / heartbeat checks
# ---------------------------------------------------------------------------

def _watcher_status_darwin(project_dir: str) -> tuple[str, str]:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(project_dir))
    label = f"com.superharness.inbox.{slug}"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    r = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return "bad", "not loaded"
    out = r.stdout
    state = next((line.split("=", 1)[1].strip() for line in out.splitlines() if "state =" in line), "")
    last_exit = next((line.split("=", 1)[1].strip() for line in out.splitlines() if "last exit code =" in line), "")
    run_interval = next((re.search(r"run interval = (\d+)", line) for line in out.splitlines() if "run interval" in line), None)
    interval_s = run_interval.group(1) if run_interval else "unknown"
    if state in ("running", "active"):
        return "ok", f"loaded state={state} interval={interval_s}s exit={last_exit or 'unknown'}"
    if state == "not running" and last_exit in ("0", "(never exited)"):
        return "ok", f"loaded idle interval={interval_s}s"
    return "warn", f"loaded state={state or 'unknown'} exit={last_exit or 'unknown'}"


def _watcher_status_linux(project_dir: str) -> tuple[str, str]:
    if not subprocess.run(["which", "systemctl"], capture_output=True).returncode == 0:
        return "warn", "no launchd/systemd watcher check available on Linux"
    unit = f"superharness-watcher@{os.path.basename(project_dir)}.service"
    r = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
    active = r.stdout.strip()
    if active == "active":
        return "ok", f"systemd unit active ({unit})"
    if active:
        return "warn", f"systemd unit {unit} is {active}"
    return "warn", f"systemd unit {unit} not found"


def _watcher_project(project_dir: str) -> str:
    watcher_cfg = os.path.join(project_dir, ".superharness", "watcher.yaml")
    if not os.path.isfile(watcher_cfg):
        return project_dir
    data = safe_load(watcher_cfg, dict) or {}
    candidate = os.path.realpath(str(data.get("watcher_project", "") or ""))
    if candidate and os.path.isdir(os.path.join(candidate, ".superharness")):
        return candidate
    return project_dir


def _read_project_heartbeat(check_dir: str, via_worker: bool, stale_seconds: int) -> tuple[str, str]:
    """Read the watcher heartbeat from check_dir and return (status, detail).

    Checks the structured YAML heartbeat first, then falls back to the legacy
    plain-text file. This is the single source of truth for one directory.
    """
    suffix = " (worker project)" if via_worker else ""

    try:
        from superharness.engine.heartbeat_contract import (
            heartbeat_path,
            read_heartbeat,
            read_heartbeat_db,
            age_seconds as hb_age_seconds,
        )
        # SQLite primary — source of truth
        hb = read_heartbeat_db(check_dir, "watcher")
        if hb is None:
            # YAML fallback (legacy)
            structured_path = heartbeat_path(check_dir, "watcher")
            if os.path.isfile(structured_path):
                hb = read_heartbeat(structured_path)
        if hb is not None:
            age = hb_age_seconds(hb)
            if age < 0:
                return "missing", "invalid heartbeat timestamp"
            age_min = age // 60
            if age >= stale_seconds:
                return "stale", f"last heartbeat {age_min}m ago{suffix}"
            return "ok", f"last heartbeat {age}s ago{suffix}"
    except Exception as e:
        logger.warning("status.py unexpected error: %s", e, exc_info=True)

    hb_file = os.path.join(check_dir, ".superharness", "watcher.heartbeat")
    if not os.path.isfile(hb_file):
        return "missing", "no heartbeat file"
    with open(hb_file) as f:
        hb_ts = f.readline().strip()
    if not hb_ts:
        return "missing", "empty heartbeat file"
    try:
        hb_dt = datetime.fromisoformat(hb_ts.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        age = int((now_dt - hb_dt).total_seconds())
        age_min = age // 60
        if age >= stale_seconds:
            return "stale", f"last heartbeat {age_min}m ago{suffix}"
        return "ok", f"last heartbeat {age}s ago{suffix}"
    except Exception as e:
        logger.warning("status.py unexpected error: %s", e, exc_info=True)
        return "missing", "invalid heartbeat timestamp"


def _heartbeat_status(project_dir: str, harness_dir: str) -> tuple[str, str]:
    watcher_project = _watcher_project(project_dir)
    hb_project = watcher_project if watcher_project != project_dir else project_dir
    via_worker = hb_project != project_dir
    stale_seconds = 120

    result = _read_project_heartbeat(hb_project, via_worker, stale_seconds)

    # shux operator start writes heartbeats to project_dir, not the worker directory.
    # When the worker-project heartbeat is stale or missing, fall back to project_dir
    # so that an operator-spawned watcher is not permanently reported as down.
    if via_worker and result[0] in ("stale", "missing"):
        src = _read_project_heartbeat(project_dir, False, stale_seconds)
        if src[0] == "ok":
            return src

    return result


# ---------------------------------------------------------------------------
# Inbox health — deep scan for orphans, duplicates, stale items
# ---------------------------------------------------------------------------

_STALE_PENDING_MINUTES = 60   # pending > 1h is suspicious
_STALE_LAUNCHED_MINUTES = 120  # launched > 2h with no PID is suspicious


def _deep_inbox_health(project_dir: str) -> dict:
    """Full inbox health scan. Returns all issues with item details."""
    from superharness.engine.state_reader import get_inbox_items, get_tasks

    inbox = get_inbox_items(project_dir)
    tasks = get_tasks(project_dir)
    now = datetime.now(timezone.utc)

    # Build task status lookup
    task_status: dict[str, str] = {}
    for t in tasks:
        if isinstance(t, dict):
            task_status[str(t.get("id", ""))] = str(t.get("status", ""))

    TERMINAL = frozenset({"done", "archived", "failed", "stopped"})

    result: dict = {
        "orphaned": [],          # inbox items whose task is terminal
        "duplicates": defaultdict(list),  # "task_id|agent" → list of item_dicts (pending only)
        "stale_pending": [],     # pending > 1h
        "stale_launched": [],    # launched > 2h, no recent activity
        "dead_pid": [],          # launched/running with dead PID
        "missing_task": [],      # inbox items whose task_id not in contract
        "discussion_orphans": [], # inbox items for discussion tasks that are archived
        "stale_items": [],       # items with status='stale' (dead data, should be deleted)
        "counts": {},
        "items": [],
    }

    pending_by_task_agent: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for item in inbox:
        if not isinstance(item, dict):
            continue
        result["items"].append(item)
        st = str(item.get("status", ""))
        result["counts"][st] = result["counts"].get(st, 0) + 1

        # Collect stale items (dead data — should be deleted)
        if st == "stale":
            result["stale_items"].append({
                "inbox_id": item.get("id", "?"),
                "task_id": str(item.get("task", item.get("task_id", ""))),
            })

        # Normalize task id (YAML 'task' vs SQLite 'task_id')
        tid = str(item.get("task", item.get("task_id", "")))

        # Check: orphaned (task is terminal but inbox still active)
        if st in ("pending", "launched", "running", "paused") and tid:
            ts = task_status.get(tid)
            if ts and ts in TERMINAL:
                result["orphaned"].append({
                    "inbox_id": item.get("id", "?"),
                    "task_id": tid,
                    "inbox_status": st,
                    "task_status": ts,
                })

        # Check: missing task
        if tid and tid not in task_status:
            result["missing_task"].append({
                "inbox_id": item.get("id", "?"),
                "task_id": tid,
                "status": st,
            })

        # Check: discussion orphan (discussion task archived but round items still active)
        if tid and ("/round-" in tid or tid.startswith("discuss-")):
            ts = task_status.get(tid)
            if ts and ts in TERMINAL and st in ("pending", "launched", "running"):
                result["discussion_orphans"].append({
                    "inbox_id": item.get("id", "?"),
                    "task_id": tid,
                    "inbox_status": st,
                    "task_status": ts,
                })

        # Check: duplicates (same task + same target_agent, multiple pending).
        # Multi-participant discussions intentionally enqueue one pending item
        # per participant under the same task_id, so the dedup key must include
        # the agent — otherwise every N-participant discussion false-positives
        # and `--fix` silently marks N-1 participants as stale.
        if st == "pending" and tid:
            agent = str(item.get("to", item.get("target_agent", "")))
            pending_by_task_agent[(tid, agent)].append(item)

        # Check: stale pending (pending too long)
        if st == "pending":
            created = item.get("created_at", "")
            if created:
                try:
                    t = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    age_min = int((now - t).total_seconds() / 60)
                    if age_min >= _STALE_PENDING_MINUTES:
                        result["stale_pending"].append({
                            "inbox_id": item.get("id", "?"),
                            "task_id": tid,
                            "age_min": age_min,
                            "agent": str(item.get("to", item.get("target_agent", "?"))),
                        })
                except (ValueError, TypeError):
                    pass

        # Check: stale launched (launched too long, no PID or dead PID)
        if st in ("launched", "running"):
            launched = item.get("launched_at", "")
            pid = item.get("pid")
            if launched:
                try:
                    t = datetime.fromisoformat(str(launched).replace("Z", "+00:00"))
                    age_min = int((now - t).total_seconds() / 60)
                    if age_min >= _STALE_LAUNCHED_MINUTES:
                        result["stale_launched"].append({
                            "inbox_id": item.get("id", "?"),
                            "task_id": tid,
                            "age_min": age_min,
                            "pid": pid,
                        })
                except (ValueError, TypeError):
                    pass
            # Dead PID check
            if pid:
                try:
                    os.kill(int(pid), 0)
                except (OSError, ValueError):
                    result["dead_pid"].append({
                        "inbox_id": item.get("id", "?"),
                        "task_id": tid,
                        "status": st,
                        "pid": pid,
                    })

    # Compile duplicates. Key is "{task_id}|{agent}" so each consumer can
    # parse it back, and so the same task_id with different agents stays
    # separated.
    for (tid, agent), items in pending_by_task_agent.items():
        if len(items) > 1:
            result["duplicates"][f"{tid}|{agent}"] = [
                {"inbox_id": i.get("id", "?"),
                 "created_at": i.get("created_at", "?"),
                 "task_id": tid,
                 "agent": agent}
                for i in items
            ]

    return result


# ---------------------------------------------------------------------------
# Discussion health
# ---------------------------------------------------------------------------

def _deep_discussion_health(project_dir: str) -> dict:
    """Full discussion health scan (SQLite-only, post-YAML removal)."""
    result: dict = {
        "counts": {},
        "consensus_unclosed": [],
        "stale_active": [],
    }
    now = datetime.now(timezone.utc)

    # SQLite-only (YAML removal v1.41+)
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        for row in discussions_dao.get_all(conn):
            st = row.status
            if st:
                result["counts"][st] = result["counts"].get(st, 0) + 1
            if st == "consensus":
                result["consensus_unclosed"].append({
                    "id": row.id,
                    "topic": row.topic or "(no topic)",
                })
            if st == "active":
                # Check age from created_at
                created = getattr(row, "created_at", None)
                if created:
                    try:
                        t = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                        age_h = (now - t).total_seconds() / 3600
                        if age_h >= 24:
                            result["stale_active"].append({
                                "id": row.id,
                                "topic": row.topic or "(no topic)",
                                "age_h": int(age_h),
                            })
                    except (ValueError, TypeError):
                        pass
    finally:
        conn.close()

    return result


# ---------------------------------------------------------------------------
# Task health
# ---------------------------------------------------------------------------

def _deep_task_health(project_dir: str) -> dict:
    """Full task health scan."""
    from superharness.engine.state_reader import get_tasks
    now = datetime.now(timezone.utc)

    tasks = get_tasks(project_dir)
    result: dict = {
        "counts": {},
        "stuck_waiting": [],       # waiting_input tasks with age
        "stuck_noreview": [],       # report_ready tasks with age
        "stuck_inprogress": [],     # in_progress tasks with age
        "stuck_plan": [],           # plan_proposed/plan_approved with age
        "no_timestamp": [],         # in_progress/waiting_input with no timestamp
    }

    for t in tasks:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", "todo"))
        tid = str(t.get("id", "?"))

        # Count by status group
        if st in ("report_ready", "review_requested", "review_passed", "review_failed", "pr_open"):
            result["counts"]["review"] = result["counts"].get("review", 0) + 1
        elif st in ("plan_proposed", "plan_approved"):
            result["counts"]["plan"] = result["counts"].get("plan", 0) + 1
        else:
            result["counts"][st] = result["counts"].get(st, 0) + 1

        if st in ("archived", "done"):
            continue

        # Age calculation
        age_min = None
        for ts_field in ("updated_at", "in_progress_at", "report_ready_at",
                          "plan_proposed_at", "launched_at", "created_at"):
            ts = t.get(ts_field, "")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    age_min = int((now - dt).total_seconds() / 60)
                except (ValueError, TypeError):
                    pass
                break

        owner = str(t.get("owner", "?"))
        title = str(t.get("title", ""))[:60]

        entry = {"id": tid, "owner": owner, "title": title, "age_min": age_min}

        if st == "waiting_input":
            if age_min is None and t.get("updated_at") is None:
                result["no_timestamp"].append(entry)
            else:
                result["stuck_waiting"].append(entry)
        elif st == "report_ready":
            result["stuck_noreview"].append(entry)
        elif st == "in_progress":
            if age_min is None and t.get("updated_at") is None and t.get("in_progress_at") is None:
                result["no_timestamp"].append(entry)
            else:
                result["stuck_inprogress"].append(entry)
        elif st in ("plan_proposed", "plan_approved"):
            result["stuck_plan"].append(entry)

    return result


# ---------------------------------------------------------------------------
# Issue collector and printer
# ---------------------------------------------------------------------------

def _detect_stuck_discussions(project_dir: str) -> list[dict]:
    """Detect active discussions where all inbox items are dispatched/done
    but zero verdicts have been submitted and no participant agents are running.
    
    Returns a list of dicts with id, round, age_min, verdicts, participants,
    and missing_agents for each stuck discussion.
    """
    from datetime import datetime, timezone
    import json as _json
    
    stuck = []
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            now = datetime.now(timezone.utc)
            active = discussions_dao.get_all(conn, status="active")
            for disc in active:
                # Check inbox items: all must be dispatched or done
                inbox_rows = conn.execute(
                    "SELECT target_agent, status FROM inbox WHERE task_id LIKE ?",
                    (f"{disc.id}/round-%",),
                ).fetchall()
                if not inbox_rows:
                    continue
                dispatched_done = {r["target_agent"] for r in inbox_rows 
                                   if r["status"] in ("dispatched", "done")}
                others = {r["target_agent"] for r in inbox_rows 
                          if r["status"] not in ("dispatched", "done", "cancelled")}
                if others:
                    continue  # still has pending/running items
                
                # Check verdicts
                rounds = discussions_dao.get_rounds(conn, disc.id)
                verdict_agents = {r.agent for r in rounds if r.agent != "_advance"}
                
                participants = _json.loads(disc.owners) if isinstance(disc.owners, str) else (disc.owners or [])
                
                # Only flag if zero verdicts AND dispatched to at least 2 agents
                if verdict_agents or len(dispatched_done) < 2:
                    continue
                
                # Check agent heartbeats
                missing = []
                for p in participants:
                    hb = conn.execute(
                        "SELECT status, updated_at FROM agent_heartbeats WHERE agent=?",
                        (p,),
                    ).fetchone()
                    if not hb or hb["status"] in ("zombie", None):
                        missing.append(p)
                
                if not missing:
                    continue  # agents might still respond
                
                # Compute age
                age_min = 0
                if disc.created_at:
                    try:
                        t = datetime.fromisoformat(str(disc.created_at).replace("Z", "+00:00"))
                        age_min = int((now - t).total_seconds() / 60)
                    except (ValueError, TypeError):
                        pass
                
                stuck.append({
                    "id": disc.id,
                    "round": 1,
                    "age_min": age_min,
                    "verdicts": len(verdict_agents),
                    "participants": len(participants),
                    "missing_agents": missing,
                })
        finally:
            conn.close()
    except Exception:
        pass
    return stuck


def _repair_missing_agents(project_dir: str, agents: list[str]) -> tuple[list[str], list[str]]:
    """Investigate why each agent is unavailable and attempt repair.
    
    Returns (repaired_agents, report_lines).
    """
    import shutil
    from pathlib import Path
    
    repaired = []
    report = []
    
    for agent in agents:
        # 1. Check if agent binary exists
        binary = shutil.which(agent)
        if not binary:
            binary = shutil.which(agent.replace("-", ""))
        
        if binary:
            report.append(f"  ✅ {agent}: binary found ({binary})")
        else:
            report.append(f"  ❌ {agent}: binary NOT on PATH — install it first")
            continue
        
        # 2. Check for any launchd operator plist with KeepAlive=true
        found_loaded = False
        for plist in Path.home().glob("Library/LaunchAgents/com.superharness.operator.*.plist"):
            try:
                content = plist.read_text()
            except Exception:
                continue
            if "KeepAlive" not in content:
                continue
            label = plist.stem
            try:
                from superharness.engine.launchd_health import is_loaded, bootstrap
                if is_loaded(label):
                    report.append(f"  ✅ operator plist {label} already loaded")
                    found_loaded = True
                    break
            except Exception:
                pass
        
        if not found_loaded:
            report.append(f"  ⚠️  No loaded operator found — run: shux operator install")
    
    return repaired, report


def _collect_issues(project_dir: str,
                     watcher_level: str, watcher_msg: str,
                     heartbeat_status: str, heartbeat_detail: str,
                     inbox_health: dict,
                     disc_health: dict,
                     task_health: dict) -> tuple[list[str], list[str]]:
    """Collect all issues and corresponding fix commands.
    Returns (issues, fixes) lists of human-readable strings.
    """
    issues: list[str] = []
    fixes: list[str] = []

    def add(issue: str, fix: str | None = None) -> None:
        issues.append(issue)
        if fix:
            fixes.append(fix)

    # Watcher
    if watcher_level in ("bad", "warn"):
        add(f"watcher: {watcher_msg}")
    if heartbeat_status == "stale":
        add(f"heartbeat stale: {heartbeat_detail}", "shux operator start")
    elif heartbeat_status == "missing":
        add(f"heartbeat missing: {heartbeat_detail}", "shux operator start")

    # Inbox: orphans (task terminal, inbox still pending)
    if inbox_health["orphaned"]:
        n = len(inbox_health["orphaned"])
        sample = inbox_health["orphaned"][:3]
        ids = ", ".join(o["inbox_id"] for o in sample)
        add(f"{n} orphaned inbox item(s) — task is done/archived but inbox still pending: {ids}",
            "shux inbox gc")

    # Inbox: duplicates (per (task, agent) pair)
    for key, dups in inbox_health["duplicates"].items():
        tid = dups[0].get("task_id", key)
        agent = dups[0].get("agent", "?")
        add(f"duplicate pending: task '{tid}' agent '{agent}' has {len(dups)} inbox items — auto-enqueue may be stuck",
            "shux inbox gc  (or stop auto-dispatch for this task)")

    # Inbox: stale pending
    if inbox_health["stale_pending"]:
        n = len(inbox_health["stale_pending"])
        sample = inbox_health["stale_pending"][:3]
        ids = ", ".join(f"{s['inbox_id']}({s['age_min']}m)" for s in sample)
        add(f"{n} stale pending item(s) — enqueued >1h ago but never dispatched: {ids}",
            "shux dispatch  (or check watcher is running)")

    # Inbox: stale launched
    if inbox_health["stale_launched"]:
        n = len(inbox_health["stale_launched"])
        sample = inbox_health["stale_launched"][:3]
        ids = ", ".join(f"{s['inbox_id']}({s['age_min']}m)" for s in sample)
        add(f"{n} stale launched item(s) — running >2h, may be stuck: {ids}",
            "shux recover  (or kill PID if zombie)")

    # Inbox: dead PID
    if inbox_health["dead_pid"]:
        n = len(inbox_health["dead_pid"])
        ids = ", ".join(d["inbox_id"] for d in inbox_health["dead_pid"])
        add(f"{n} item(s) with dead PID — process died but inbox not updated: {ids}",
            "shux inbox gc")

    # Inbox: missing task
    if inbox_health["missing_task"]:
        n = len(inbox_health["missing_task"])
        ids = ", ".join(m["inbox_id"] for m in inbox_health["missing_task"][:3])
        add(f"{n} inbox item(s) referencing unknown task: {ids}",
            "shux inbox gc  (these items will never dispatch)")

    # Inbox: stale items (dead data — should be cleaned)
    if inbox_health["stale_items"]:
        n = len(inbox_health["stale_items"])
        add(f"{n} stale inbox item(s) — dead data from previous cleanups, should be deleted",
            "shux status --fix")

    # Discussion: orphans
    if inbox_health["discussion_orphans"]:
        n = len(inbox_health["discussion_orphans"])
        ids = ", ".join(d["inbox_id"] for d in inbox_health["discussion_orphans"][:3])
        add(f"{n} discussion inbox item(s) for archived round task(s): {ids}",
            "shux inbox gc")

    # Discussion: consensus not closed
    if disc_health["consensus_unclosed"]:
        for d in disc_health["consensus_unclosed"]:
            add(f"discussion '{d['id']}' reached consensus but not closed — topic: {d['topic'][:60]}",
                f"shux status --fix  (auto-closes consensus discussions + cleans orphans)")

    # Discussion: stale active
    if disc_health["stale_active"]:
        for d in disc_health["stale_active"]:
            add(f"discussion '{d['id']}' active for {d['age_h']}h — may need attention",
                f"shux discuss status --id {d['id']}")

    # Tasks: stuck waiting_input
    if task_health["stuck_waiting"]:
        n = len(task_health["stuck_waiting"])
        sample = task_health["stuck_waiting"][:3]
        ids = ", ".join(f"{t['id']}({t['age_min']}m)" for t in sample)
        add(f"{n} task(s) stuck in waiting_input: {ids}",
            "Respond to agent or close task")

    # Tasks: report_ready with no review
    if task_health["stuck_noreview"]:
        n = len(task_health["stuck_noreview"])
        sample = task_health["stuck_noreview"][:3]
        ids = ", ".join(f"{t['id']}({t['age_min']}m)" for t in sample)
        add(f"{n} task(s) report_ready awaiting review: {ids}",
            "Review and approve/close via dashboard or shux verify --id <id>")

    # Tasks: in_progress with no timestamp
    if task_health["no_timestamp"]:
        n = len(task_health["no_timestamp"])
        ids = ", ".join(t["id"] for t in task_health["no_timestamp"][:3])
        add(f"{n} task(s) in_progress/waiting_input with no timestamp — lifecycle rules cannot fire: {ids}",
            "shux task status --id <id> --status in_progress  (resets updated_at)")

    # Tasks: stuck in_progress
    if task_health["stuck_inprogress"]:
        long_running = [t for t in task_health["stuck_inprogress"] if (t.get("age_min") or 0) >= 180]
        if long_running:
            ids = ", ".join(f"{t['id']}({t['age_min']}m)" for t in long_running[:3])
            add(f"{len(long_running)} task(s) in_progress >3h — should auto-archive next watcher cycle: {ids}")

    # Tasks: stuck plan
    if task_health["stuck_plan"]:
        sample = task_health["stuck_plan"][:3]
        ids = ", ".join(f"{t['id']}({t.get('age_min', '?')}m)" for t in sample)
        add(f"{len(task_health['stuck_plan'])} task(s) plan_proposed/plan_approved with no action: {ids}",
            "Approve plan via dashboard or delegate task")

    return issues, fixes


# ---------------------------------------------------------------------------
# Active task display
# ---------------------------------------------------------------------------

def _print_active_tasks(project_dir: str) -> None:
    """Print per-task details for all non-archived, non-done tasks."""
    from datetime import datetime, timezone
    from superharness.engine.state_reader import get_tasks, get_inbox_items

    tasks = get_tasks(project_dir)
    inbox = get_inbox_items(project_dir)
    now = datetime.now(timezone.utc)

    inbox_by_task: dict[str, list[dict]] = {}
    for item in inbox:
        if isinstance(item, dict):
            tid = item.get("task", item.get("task_id", ""))
            if tid:
                inbox_by_task.setdefault(tid, []).append(item)

    for task in tasks:
        if not isinstance(task, dict):
            continue
        st = task.get("status", "?")
        if st in ("archived", "done"):
            continue
        tid = task.get("id", "?")
        title = task.get("title", "")[:60]
        owner = task.get("owner", "?")

        timer = ""
        for ts_field in ("updated_at", "in_progress_at", "report_ready_at",
                          "launched_at", "created_at"):
            ts = task.get(ts_field, "")
            if ts:
                try:
                    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    mins = int((now - t).total_seconds() / 60)
                    timer = f"({mins}m)"
                except (ValueError, TypeError):
                    pass
                break

        agents = ""
        if tid in inbox_by_task:
            for item in inbox_by_task[tid]:
                a = item.get("to", item.get("target_agent", "?"))
                s = item.get("status", "?")
                agents += f" [{a}:{s}]"

        print(f"  {st:20s} {tid:40s} {owner:12s} {timer:8s}{agents}")
        if title:
            print(f"  {'':20s} {'':40s} {'':12s} {'':8s} {title}")


# ---------------------------------------------------------------------------
# Fix-it: auto-clean
# ---------------------------------------------------------------------------

def _auto_fix(project_dir: str, inbox_health: dict, disc_health: dict) -> int:
    """Automatically fix fixable issues. Returns count of items fixed."""
    fixed = 0

    # Clean orphaned inbox items
    if inbox_health["orphaned"]:
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                for o in inbox_health["orphaned"]:
                    inbox_dao.mark_stale(conn, o["inbox_id"])
                    fixed += 1
                conn.commit()
                print(f"  Cleaned {fixed} orphaned inbox item(s)")
            finally:
                conn.close()
        except Exception as e:
            print(f"  Warning: failed to clean orphans: {e}", file=sys.stderr)

    # Clean discussion orphans
    if inbox_health["discussion_orphans"]:
        n = 0
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                for d in inbox_health["discussion_orphans"]:
                    inbox_dao.mark_stale(conn, d["inbox_id"])
                    n += 1
                conn.commit()
                print(f"  Cleaned {n} discussion orphan inbox item(s)")
                fixed += n
            finally:
                conn.close()
        except Exception as e:
            print(f"  Warning: failed to clean discussion orphans: {e}", file=sys.stderr)

    # Clean duplicates (keep newest, stale rest). Each entry in
    # inbox_health["duplicates"] is already scoped to a single
    # (task_id, agent) pair, so this only ever drops genuine re-enqueues
    # of the same agent — never a sibling participant in a multi-agent
    # discussion.
    if inbox_health["duplicates"]:
        n = 0
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                for _key, dups in inbox_health["duplicates"].items():
                    for dup in dups[:-1]:
                        inbox_dao.mark_stale(conn, dup["inbox_id"])
                        n += 1
                conn.commit()
                if n > 0:
                    print(f"  Cleaned {n} duplicate pending item(s)")
                    fixed += n
            finally:
                conn.close()
        except Exception as e:
            print(f"  Warning: failed to clean duplicates: {e}", file=sys.stderr)

    # Close consensus discussions
    if disc_health["consensus_unclosed"]:
        try:
            from superharness.commands.inbox_watch import _auto_close_consensus_discussions
            n = _auto_close_consensus_discussions(project_dir)
            if n > 0:
                fixed += n
        except Exception as e:
            print(f"  Warning: failed to close consensus discussions: {e}", file=sys.stderr)

    # Repair launchd state: bootout zombies, remove stale-pattern services
    # and orphan plists, bootstrap the operator if its plist is on disk but
    # not loaded. Covers the "watcher: not loaded" + "plist file present"
    # divergence that otherwise needs manual intervention. No-op on Linux.
    try:
        from pathlib import Path
        import hashlib
        from superharness.engine.launchd_health import heal as _launchd_heal

        short = hashlib.md5(project_dir.encode()).hexdigest()[:8]
        operator_label = f"com.superharness.operator.{short}"
        operator_plist = Path.home() / "Library" / "LaunchAgents" / f"{operator_label}.plist"
        report = _launchd_heal(
            operator_plist=operator_plist if operator_plist.is_file() else None,
        )
        if report.fixed_count() > 0:
            print(f"  {report.summary()}")
            fixed += report.fixed_count()
    except Exception as e:
        print(f"  Warning: launchd self-heal failed: {e}", file=sys.stderr)

    # Delete stale inbox items
    if inbox_health["stale_items"]:
        n = 0
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                n = inbox_dao.purge_stale(conn)
                conn.commit()
                print(f"  Deleted {n} stale inbox item(s)")
                fixed += n
            finally:
                conn.close()
        except Exception as e:
            print(f"  Warning: failed to delete stale items: {e}", file=sys.stderr)

    # Cancel stale pending items (pending > 1h, never dispatched)
    if inbox_health["stale_pending"]:
        n = 0
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                for sp in inbox_health["stale_pending"]:
                    inbox_dao.mark_stale(conn, sp["inbox_id"])
                    n += 1
                conn.commit()
                print(f"  Canceled {n} stale pending item(s) (undispatched > 1h)")
                fixed += n
            finally:
                conn.close()
        except Exception as e:
            print(f"  Warning: failed to cancel stale pending: {e}", file=sys.stderr)

    return fixed


# ---------------------------------------------------------------------------
# Worktree surface — tasks with a live dispatch worktree on disk
# ---------------------------------------------------------------------------


def _active_worktrees(project_dir: str) -> list[dict]:
    """Return tasks that currently have a live dispatch worktree on disk.

    "Active" means: worktree_path IS NOT NULL and the directory exists.
    worktree_path is never cleared on cleanup, so the directory existence
    check is the authoritative signal.
    Age is computed from created_at.
    """
    try:
        from superharness.engine.state_reader import get_tasks
        tasks = get_tasks(project_dir)
    except Exception as e:
        logger.warning("status.py unexpected error: %s", e, exc_info=True)
        return []

    now = datetime.now(timezone.utc)
    result = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        wt_path = t.get("worktree_path") or ""
        if not wt_path:
            continue
        if not os.path.isdir(wt_path):
            continue
        age_min = None
        for ts_field in ("created_at", "in_progress_at"):
            ts = t.get(ts_field, "")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    age_min = int((now - dt).total_seconds() / 60)
                except (ValueError, TypeError):
                    pass
                break
        result.append({
            "task_id": str(t.get("id", "?")),
            "path": wt_path,
            "age_min": age_min,
        })
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="status",
        description="Full project health dashboard — one command, complete picture."
    )
    p.add_argument("-p", "--project", default=os.getcwd())
    p.add_argument("--retry-threshold", type=int, default=3, dest="retry_threshold")
    p.add_argument("--check", action="store_true",
                   help="Exit 1 if any issues found (CI mode)")
    p.add_argument("--active", "-a", action="store_true", default=True,
                   help="Show per-task progress details (default)")
    p.add_argument("--summary", "-s", action="store_true",
                   help="Show summary counts only (compact mode)")
    p.add_argument("--fix", action="store_true",
                   help="Auto-clean orphaned inbox items, duplicates, and discussion orphans")
    opts = p.parse_args(argv)

    if opts.retry_threshold <= 0:
        sys.exit("--retry-threshold must be a positive integer")

    project_dir = os.path.realpath(opts.project)
    if not os.path.isdir(project_dir):
        sys.exit(f"Project directory does not exist: {opts.project}")

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        sys.exit(f"Missing .superharness in project: {project_dir}")

    handoff_dir = os.path.join(harness_dir, "handoffs")

    # --- Watcher & heartbeat ---
    sys_platform = platform.system()
    if sys_platform == "Darwin":
        watcher_level, watcher_msg = _watcher_status_darwin(project_dir)
    elif sys_platform == "Linux":
        watcher_level, watcher_msg = _watcher_status_linux(project_dir)
    else:
        watcher_level = "warn"
        watcher_msg = f"no watcher check available on {sys_platform}"

    heartbeat_status, heartbeat_detail = _heartbeat_status(project_dir, harness_dir)

    if watcher_level == "bad" and heartbeat_status == "ok":
        watcher_level = "ok"
        watcher_msg = f"foreground ({heartbeat_detail})"
    elif watcher_level == "bad" and heartbeat_status == "stale":
        watcher_msg = f"not loaded, heartbeat stale ({heartbeat_detail})"
    elif watcher_level == "bad" and heartbeat_status == "missing":
        watcher_msg = "not running (no heartbeat)"

    # --- Deep health scans ---
    inbox_health = _deep_inbox_health(project_dir)
    disc_health = _deep_discussion_health(project_dir)
    task_health = _deep_task_health(project_dir)

    # --- Legacy stats for backward compat ---
    # Approvals pending (from SQLite)
    approvals_pending = 0
    try:
        from superharness.engine import state_reader as _sr_s
        import yaml as _yaml_s
        handoff_rows = _sr_s.get_handoffs(project_dir)
        for row in handoff_rows:
            if not isinstance(row, dict):
                continue
            _status = str(row.get("status") or "")
            gate = None
            content_text = row.get("content") or ""
            if content_text:
                try:
                    parsed = _yaml_s.safe_load(content_text)
                    if isinstance(parsed, dict):
                        gate = parsed.get("approval_gate")
                except Exception:
                    pass
            required = isinstance(gate, dict) and gate.get("required") is True
            approved = isinstance(gate, dict) and gate.get("approved_by_user") is True
            if _status == "pending_user_approval" or (required and not approved):
                approvals_pending += 1
    except Exception as e:
        logger.warning("status.py approvals_pending failed: %s", e, exc_info=True)

    # Retry high — only alert when retries are EXHAUSTED, not when they're working.
    # Discussion shadow rows are excluded (they have their own health signal).
    retry_high = 0
    retry_high_ids: list = []
    active_statuses = {"pending", "launched", "running", "stale", "failed", "paused", "stopped"}
    failed_task_ids: list = []
    for item in inbox_health["items"]:
        if item.get("type") == "discussion":
            continue  # discussion rounds manage their own retry lifecycle
        st = str(item.get("status", ""))
        tid = item.get("task", item.get("task_id", ""))
        if st == "failed" and tid:
            failed_task_ids.append(str(tid))
        if st in active_statuses:
            rc = int(item.get("retry_count") or 0)
            max_rc = int(item.get("max_retries") or 3)
            # Alert only when retries are truly exhausted, not when they're working normally
            if rc >= max_rc and max_rc > 0:
                retry_high += 1
                iid = str(item.get("id", ""))
                if iid:
                    retry_high_ids.append(iid)

    # --- Print ---
    ic = inbox_health["counts"]
    dc = disc_health["counts"]
    tc = task_health["counts"]

    def c(k: str) -> int:
        return ic.get(k, 0)

    print("superharness status")
    print(f"project: {project_dir}")
    print(f"watcher: level={watcher_level} {watcher_msg}")
    print(f"heartbeat: {heartbeat_status} ({heartbeat_detail})")
    print(f"inbox: pending={c('pending')} launched={c('launched')} running={c('running')} "
          f"paused={c('paused')} done={c('done')} failed={c('failed')} "
          f"stale={c('stale')} stopped={c('stopped')}")
    print(f"retry-alert: threshold={opts.retry_threshold} high={retry_high} "
          f"ids={','.join(retry_high_ids[:5]) or 'none'}")

    # Per-agent health scores
    print(f"approvals: pending={approvals_pending}")
    print(f"discussions: active={dc.get('active', 0)} consensus={dc.get('consensus', 0)} "
          f"failed_participant={dc.get('failed_participant', 0)} "
          f"deadlock={dc.get('deadlock', 0)} closed={dc.get('closed', 0)}")
    print(f"tasks: archived={tc.get('archived',0)} done={tc.get('done',0)} "
          f"review={tc.get('review',0)} todo={tc.get('todo',0)} "
          f"in_progress={tc.get('in_progress',0)} plan={tc.get('plan',0)} "
          f"failed={tc.get('failed',0)} blocked={tc.get('blocked',0)} "
          f"waiting_input={tc.get('waiting_input',0)}")

    # Worktrees section — omitted entirely when none are active (zero noise)
    active_worktrees = _active_worktrees(project_dir)
    if active_worktrees:
        print()
        print("Worktrees:")
        for wt in active_worktrees:
            age_str = f"{wt['age_min']}m" if wt["age_min"] is not None else "unknown age"
            print(f"  {wt['task_id']}  {wt['path']}  (age {age_str})")

    # Active tasks detail (default)
    if opts.active and not opts.summary:
        print()
        print("Active Tasks:")
        _print_active_tasks(project_dir)

    # --- Collect and display issues ---
    issues, fixes = _collect_issues(
        project_dir, watcher_level, watcher_msg,
        heartbeat_status, heartbeat_detail,
        inbox_health, disc_health, task_health,
    )

    if issues:
        print()
        print(f"Issues ({len(issues)}):")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        if fixes:
            print()
            print("Fix it:")
            for i, fix in enumerate(fixes, 1):
                print(f"  {i}. {fix}")
        print()
        print(f"  → Run 'shux status --fix' to auto-clean orphans, duplicates, and close consensus discussions")
    else:
        # Quick stuck-discussion check: flag discussions where all inbox items
        # are dispatched/done but zero verdicts submitted and no agents running.
        stuck = _detect_stuck_discussions(project_dir)
        if stuck:
            print()
            print(f"⚠️  Stuck discussions ({len(stuck)}):")
            for s in stuck:
                print(f"  {s['id'][:20]}...  round={s['round']}  age={s['age_min']}m  "
                      f"verdicts={s['verdicts']}/{s['participants']}  "
                      f"agents={', '.join(s['missing_agents'][:3])}")
            print()
            print(f"  No agents are running. Discussions will auto-close as "
                  f"failed_participant after grace period.")
            print(f"  → Submit verdicts manually: shux discuss submit ...")
            print(f"  → Or close them: shux discuss close --id <id> --outcome cancelled")
        else:
            print()
            print("No issues found. All clean.")

    # --- Auto-fix if requested ---
    if opts.fix:
        # Also detect stuck discussions for fix
        stuck = _detect_stuck_discussions(project_dir)
        if stuck:
            # Collect all missing agents across stuck discussions
            all_missing = set()
            for s in stuck:
                all_missing.update(s["missing_agents"])
            
            print()
            print("Auto-fix: investigating agent availability...")
            
            # Try to repair missing agents
            repaired, report = _repair_missing_agents(project_dir, sorted(all_missing))
            if report:
                for line in report:
                    print(f"  {line}")
            
            # If agents were repaired, skip closing — give them time to respond
            if repaired:
                print(f"  {len(repaired)} agent(s) restarted. Skipping discussion close — "
                      f"give them time to respond.")
                print(f"  Run 'shux status' again to verify.")
            else:
                print()
                print("Auto-fix (stuck discussions):")
                from datetime import datetime, timezone
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                try:
                    from superharness.engine.db import get_connection, init_db
                    conn = get_connection(project_dir)
                    try:
                        init_db(conn)
                        closed = 0
                        for s in stuck:
                            conn.execute(
                                "UPDATE discussions SET status='failed_participant', "
                                "closed_at=? WHERE id=? AND status='active'",
                                (now_str, s["id"]),
                            )
                            conn.execute(
                                "UPDATE inbox SET status='done', done_at=?, "
                                "failed_reason='auto-fix: stuck — no agents running' "
                                "WHERE task_id LIKE ? AND status NOT IN ('done','cancelled')",
                                (now_str, f"{s['id']}/round-%"),
                            )
                            closed += 1
                        conn.commit()
                        print(f"  Closed {closed} stuck discussion(s) as failed_participant.")
                        if closed:
                            issues = True
                    finally:
                        conn.close()
                except Exception as e:
                    print(f"  Auto-fix failed: {e}", file=sys.stderr)
        
        if issues:
            print()
            print("Auto-fix:")
            fixed = _auto_fix(project_dir, inbox_health, disc_health)
            if fixed > 0:
                print(f"Fixed {fixed} item(s). Run 'shux status' again to verify.")

    # Exit code for CI
    if opts.check and issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
