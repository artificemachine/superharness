#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import errno as _errno_mod
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil  # noqa: F401 — patched by tests to mock agent CLI detection
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from collections import Counter
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from superharness import __version__
from superharness.engine import db, dashboard_presenter


def _ensure_python_with_yaml() -> None:
    """Re-exec into the repo venv if the current interpreter lacks PyYAML."""
    try:
        import yaml  # noqa: F401
        return
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    if os.environ.get("SUPERHARNESS_MONITOR_REEXEC") == "1":
        return

    repo_root = Path(__file__).resolve().parents[3]
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return

    env = os.environ.copy()
    env["SUPERHARNESS_MONITOR_REEXEC"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

# Registry of known agent names — add new agents here as the ecosystem grows.
KNOWN_AGENTS: list[str] = ["claude-code", "codex-cli", "gemini-cli", "opencode"]

# Inbox item statuses that mean "still in flight or queued" (not terminal).
INBOX_ACTIVE_STATUSES: frozenset[str] = frozenset({"pending", "launched", "running", "paused"})

# Inbox item statuses considered terminal / done.
INBOX_TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "failed", "stale", "stopped"})

from superharness.engine.normalization import normalize_blocked_by as _normalize_blocked_by  # noqa: E402


def git_context(project_dir: Path) -> dict:
    """Get current branch, dirty file count, and last commit."""
    import subprocess as _sp
    result = {"branch": "", "dirty_count": 0, "last_commit": ""}
    try:
        r = _sp.run(["git", "-C", str(project_dir), "branch", "--show-current"],
                    capture_output=True, text=True, check=False)
        if r.returncode == 0:
            result["branch"] = r.stdout.strip()
        r2 = _sp.run(["git", "-C", str(project_dir), "status", "--porcelain", "--untracked-files=normal"],
                     capture_output=True, text=True, check=False)
        if r2.returncode == 0:
            result["dirty_count"] = len([l for l in r2.stdout.strip().splitlines() if l.strip()])
        r3 = _sp.run(["git", "-C", str(project_dir), "log", "-1", "--format=%h %s"],
                     capture_output=True, text=True, check=False)
        if r3.returncode == 0:
            result["last_commit"] = r3.stdout.strip()
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    return result


from datetime import datetime as _datetime

import logging
logger = logging.getLogger(__name__)


def tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return ["No log file yet (created when watcher runs as launchd service). Foreground mode logs to stdout."]
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [ln.rstrip("\n") for ln in lines[-n:]]


def watcher_runtime(label: str) -> dict:
    info = {
        "loaded": False,
        "state": "",
        "last_exit_code": "",
        "run_interval_seconds": 0,
    }
    if sys.platform == "win32":
        return info
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if out.returncode != 0:
            return info
        info["loaded"] = True
        for ln in out.stdout.splitlines():
            if "state =" in ln and not info["state"]:
                info["state"] = ln.split("=", 1)[1].strip()
            elif "last exit code =" in ln:
                info["last_exit_code"] = ln.split("=", 1)[1].strip()
            elif "run interval =" in ln and "seconds" in ln:
                raw = ln.split("=", 1)[1].strip().split(" ", 1)[0]
                try:
                    info["run_interval_seconds"] = int(raw)
                except ValueError:
                    info["run_interval_seconds"] = 0
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return info
    return info


def _read_source_version(project_dir: Path) -> str:
    init_py = project_dir / "src" / "superharness" / "__init__.py"
    if not init_py.exists():
        return "unknown"
    try:
        match = re.search(
            r"""^__version__\s*=\s*['"]([^'"]+)['"]""",
            init_py.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        return match.group(1) if match else "unknown"
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return "unknown"


def version_sanity(project_dir: Path) -> dict:
    wcfg = watcher_config(project_dir)
    watcher_project = Path(str(wcfg.get("watcher_project", str(project_dir))))
    project_version = _read_source_version(project_dir)
    worker_copy_version = _read_source_version(watcher_project)
    dashboard_version = __version__
    installed_version = _get_installed_version()
    issues: list[str] = []

    if project_version != "unknown" and dashboard_version != project_version:
        if installed_version == dashboard_version:
            issues.append(
                f"dashboard process is using installed package {dashboard_version}, "
                f"but project checkout is {project_version}"
            )
        else:
            issues.append(
                f"dashboard process version {dashboard_version} does not match "
                f"project checkout {project_version}"
            )

    if (
        project_version != "unknown"
        and worker_copy_version != "unknown"
        and worker_copy_version != project_version
    ):
        issues.append(
            f"watcher worker copy is {worker_copy_version}, but project checkout is {project_version}"
        )

    return {
        "level": "ok" if not issues else "warn",
        "dashboard_version": dashboard_version,
        "installed_version": installed_version,
        "project_version": project_version,
        "worker_copy_version": worker_copy_version,
        "watcher_project": str(watcher_project),
        "issues": issues,
    }


def inbox_items(inbox_file: Path) -> list[dict]:
    """Read inbox items from state_reader (SQLite-only)."""
    project_dir = str(inbox_file.parent.parent)
    try:
        from superharness.engine import state_reader as _sr
        return _sr.get_inbox_items(project_dir)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return []


def inbox_counts(inbox_file: Path) -> dict[str, int]:
    """Count inbox items by status from state_reader (SQLite-only)."""
    counts = Counter()
    for item in inbox_items(inbox_file):
        status = item.get("status", "")
        if status:
            counts[status] += 1
    return dict(counts)


def inbox_owner_counts(inbox_file: Path) -> dict[str, int]:
    counts = Counter()
    for item in inbox_items(inbox_file):
        owner = item.get("to", "unknown")
        counts[owner] += 1
    return dict(counts)


def _safe_int(value: object, default: int) -> int:
    """Parse an int from a query-string value; fall back on bad input."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def task_instructions(project_dir: Path, task_id: str) -> str:
    """Build personalized TDD instructions for a task by reading plan docs and contract."""
    import re as _re

    # Get task title and criteria from SQLite
    task_title = ""
    criteria = []

    conn = db.get_connection(str(project_dir))
    db.init_db(conn)
    try:
        data = dashboard_presenter.get_task_instructions_data(conn, task_id, str(project_dir))
        if not data:
            return "Task not found."
        task_title = data["title"]
        criteria = data["acceptance_criteria"]
    finally:
        conn.close()



    # Try to find matching iteration section in plan docs
    plan_section = ""
    # Build keywords from task ID and title (e.g. mod.3-obsidian → ["obsidian"], mod.7-ntfy + "ntfy notification module" → ["ntfy", "notification", "module"])
    _stop_words = {"mod", "feat", "auto", "module", "task", "the", "with", "from", "that", "this"}
    raw_words = [w.lower() for w in _re.split(r"[.\-_]+", task_id) if w and not w.isdigit() and w.lower() not in _stop_words]
    title_words = [w.lower() for w in _re.split(r"[\s\-_()]+", task_title) if w and len(w) >= 4 and w.lower() not in _stop_words]
    raw_words.extend(title_words)
    task_keywords = []
    for w in raw_words:
        task_keywords.append(w)
        # "autoschedule" → also match "schedule", "auto-schedule"
        parts = _re.findall(r"[a-z]+", w)
        if len(parts) == 1 and len(w) > 5:
            for prefix in ("auto",):
                if w.startswith(prefix) and len(w) > len(prefix):
                    task_keywords.append(w[len(prefix):])
                    task_keywords.append(prefix + "-" + w[len(prefix):])
    for plan_file in sorted(project_dir.glob("docs/plan*.md")):
        try:
            content = plan_file.read_text(errors="replace")
            # Find all iteration sections
            sections = _re.split(r"\n(?=## Iteration \d)", content)
            for section in sections:
                if not section.strip().startswith("## Iteration"):
                    continue
                # Strip trailing --- separator
                section = _re.split(r"\n---\s*$", section, flags=_re.MULTILINE)[0].strip()
                header = section.split("\n", 1)[0].lower()
                # Match by keywords from task ID against iteration header
                # Require the longest keyword to match (most specific)
                sorted_kw = sorted(task_keywords, key=len, reverse=True)
                if sorted_kw and any(kw in header for kw in sorted_kw if len(kw) >= 4):
                    plan_section = section.strip()
                    break
            if plan_section:
                break
        except Exception as e:
            logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
            continue

    lines = [f"Task: {task_title} ({task_id})", ""]

    if plan_section:
        lines.append("## Plan (from docs/)")
        lines.append(plan_section)
        lines.append("")

    if criteria:
        lines.append("## Acceptance Criteria")
        for c in criteria:
            lines.append(f"- {c}")
        lines.append("")

    # Check for prior failed attempts — inbox items (SQLite) and handoff reports
    prior_failure = ""
    inbox_file = project_dir / ".superharness" / "inbox.yaml"
    items = inbox_items(inbox_file)
    failed = [i for i in items if i.get("task") == task_id and i.get("status") in ("failed", "stale")]
    if failed:
        prior_failure = f"Status: {failed[-1].get('status')}"

    # Check handoff for failure details
    report = task_report(project_dir, task_id, "")
    handoff_status = report.get("handoff_status", "")
    md_report = report.get("markdown_report", "")
    handoff_outcome = report.get("handoff_outcome", "")

    if handoff_status in ("failed", "blocked", "stale") or prior_failure:
        lines.append("## Prior Attempt (FAILED)")
        if prior_failure:
            lines.append(prior_failure)
        if handoff_outcome:
            lines.append(f"Outcome: {handoff_outcome.strip()}")
        if md_report:
            # Truncate to keep it readable
            snippet = md_report.strip()[:2000]
            lines.append(f"\nAgent report:\n{snippet}")
        if not handoff_outcome and not md_report:
            lines.append("No detailed report from previous attempt.")
        lines.append("")
        lines.append("Fix the issues above before proceeding.")
        lines.append("")

    lines.append("## Process")
    lines.append("1. Read the task details and plan section above")
    lines.append("2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation")
    lines.append("3. Implement only after user approves the plan")
    lines.append("4. Run tests after each phase — all tests must pass before marking done")

    return "\n".join(lines)


def task_report(project_dir: Path, task_id: str, agent: str) -> dict:
    """Gather all report data for a given task and optional agent."""
    harness = project_dir / ".superharness"
    result: dict = {"task": task_id, "agent": agent}

    # 1. Contract task — full data from SQLite
    conn = db.get_connection(str(project_dir))
    db.init_db(conn)
    try:
        data = dashboard_presenter.get_task_report_data(conn, task_id, str(project_dir))
        if data:
            result.update(data)
    finally:
        conn.close()

    # 1a. Deadline and lifecycle predictions
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        conn2 = db.get_connection(str(project_dir))
        db.init_db(conn2)
        try:
            row = conn2.execute(
                "SELECT deadline_minutes, created_at, updated_at, in_progress_at, status FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if row:
                deadline = row[0]
                created = row[1]
                updated = row[2]
                in_progress = row[3]
                status = row[4]
                if deadline:
                    result["deadline_minutes"] = deadline
                    if created:
                        try:
                            t = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                            elapsed = int((now - t).total_seconds() / 60)
                            remaining = deadline - elapsed
                            result["deadline_elapsed"] = elapsed
                            result["deadline_remaining"] = remaining
                            result["deadline_exceeded"] = remaining <= 0
                        except (ValueError, TypeError):
                            pass
                # Lifecycle prediction
                ts = updated or in_progress
                if ts and status == "in_progress":
                    try:
                        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        age = int((now - t).total_seconds() / 60)
                        result["lifecycle_age"] = age
                        result["lifecycle_timeout"] = 180
                        result["lifecycle_remaining"] = 180 - age
                        result["lifecycle_action"] = "archive"
                    except (ValueError, TypeError):
                        pass
                elif ts and status == "waiting_input":
                    try:
                        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        age = int((now - t).total_seconds() / 60)
                        result["lifecycle_age"] = age
                        result["lifecycle_timeout"] = 480
                        result["lifecycle_remaining"] = 480 - age
                        result["lifecycle_action"] = "fail"
                    except (ValueError, TypeError):
                        pass
        finally:
            conn2.close()
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    # 1b. Inbox status for this task


    # 1b. Launcher log — extract Model / Effort / Via written at dispatch time
    launcher_log_dir = harness / "launcher-logs"
    if launcher_log_dir.exists():
        try:
            # Most recent log for this task+agent
            logs = sorted(launcher_log_dir.glob(f"{task_id}-{agent}-*.log"), reverse=True)
            if not logs:
                logs = sorted(launcher_log_dir.glob(f"{task_id}-*.log"), reverse=True)
            if logs:
                import re as _re
                # Pick most recent log that has actual content (empty logs are stale)
                log_text = ""
                for _log in logs:
                    _t = _log.read_text(errors="replace")
                    if len(_t.strip()) > 10:
                        log_text = _t
                        break
                for line in log_text.splitlines():
                    # Strip ^D literal, backspace chars, and surrounding whitespace
                    line = _re.sub(r'[\x00-\x08\x0e-\x1f\x7f]', '', line)
                    line = line.replace("^D", "").strip()
                    if line.startswith("Model:"):
                        result["dispatch_model"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Effort:"):
                        result["dispatch_effort"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Via:"):
                        result["dispatch_via"] = line.split(":", 1)[1].strip()
        except Exception as e:
            logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
            pass
    # 2. Handoff — read from SQLite (source of truth)
    handoff_dir = harness / "handoffs"  # kept for discussion markdown fallback below
    try:
        import yaml as _yaml_h
        from superharness.engine import state_reader as _sr_h
        task_handoffs = _sr_h.get_handoffs(str(project_dir), task_id=task_id)
        for row in reversed(task_handoffs):
            if agent and str(row.get("to_agent", "")) != agent and str(row.get("from_agent", "")) != agent:
                continue
            content_text = row.get("content") or ""
            hd: dict = {}
            if content_text:
                try:
                    parsed = _yaml_h.safe_load(content_text)
                    if isinstance(parsed, dict):
                        hd = parsed
                except Exception:
                    pass
            result["handoff_status"] = hd.get("status") or str(row.get("status", ""))
            result["handoff_summary"] = hd.get("summary", "")
            result["handoff_outcome"] = hd.get("outcome", "")
            result["handoff_context"] = hd.get("context", "")
            result["handoff_date"] = str(hd.get("date") or row.get("created_at", ""))
            md_path = hd.get("markdown_report", "")
            if md_path:
                md_file = project_dir / md_path if not Path(md_path).is_absolute() else Path(md_path)
                if md_file.exists():
                    result["markdown_report"] = md_file.read_text(errors="replace")[:8000]
            break
    except Exception as e:
        logger.warning("dashboard-ui handoff SQLite read failed: %s", e, exc_info=True)

    # 3. Discussion submissions (task_id like discuss-XXX/round-N) — SQLite
    if "/" in task_id:
        disc_id, round_part = task_id.rsplit("/", 1)
        try:
            from superharness.engine.db import get_connection as _gc_d, init_db as _idb_d
            from superharness.engine import discussions_dao as _ddao
            _conn_d = _gc_d(str(project_dir))
            try:
                _idb_d(_conn_d)
                disc_row = _ddao.get(_conn_d, disc_id)
                if disc_row:
                    result["discussion_topic"] = disc_row.topic
                    result["discussion_status"] = disc_row.status
                rounds = _ddao.get_rounds(_conn_d, disc_id)
            finally:
                _conn_d.close()

            round_num_str = round_part.replace("round-", "")
            try:
                round_num_int = int(round_num_str)
            except ValueError:
                round_num_int = None

            all_positions = []
            for r in rounds:
                if round_num_int is not None and r.round_number != round_num_int:
                    continue
                a = r.agent
                v = r.verdict or "?"
                p = r.content or ""
                all_positions.append(f"[{a}] verdict={v}\n{p}")
                if agent and r.agent == agent:
                    result["discussion_agent"] = a
                    result["discussion_verdict"] = v or ""
            if all_positions:
                result["discussion_position"] = "\n\n".join(all_positions)
        except Exception as e:
            logger.warning("dashboard-ui discussion SQLite read failed: %s", e, exc_info=True)

    return result


def discussion_agent_status(project_dir: Path, disc_id: str) -> dict:
    """Get full discussion status: submissions, live agents, logs.

    Returns a rich view of a discussion including:
    - submissions: round submissions from each agent (content, verdict, points)
    - agents: live agent activity (PIDs, CPU, elapsed)
    - logs: launcher log files
    - timeline: key events (created, submitted, consensus, closed)
    """
    import subprocess as _sp
    import yaml as _yaml
    harness = project_dir / ".superharness"
    disc_dir = harness / "discussions" / disc_id
    launcher_logs = harness / "launcher-logs"

    result: dict = {
        "discussion_id": disc_id,
        "submissions": [],
        "agents": [],
        "logs": [],
        "timeline": [],
    }

    # --- 1. Read discussion state and round submissions from SQLite ---
    state: dict = {}
    submissions: list[dict] = []
    try:
        from superharness.engine.db import get_connection as _gc_das, init_db as _idb_das
        from superharness.engine import discussions_dao as _ddao_das
        _conn_das = _gc_das(str(project_dir))
        try:
            _idb_das(_conn_das)
            disc_row = _ddao_das.get(_conn_das, disc_id)
            if disc_row:
                state = {
                    "created_at": disc_row.created_at,
                    "closed_at": disc_row.closed_at,
                    "consensus_verdict": disc_row.consensus,
                    "consensus_at": disc_row.closed_at if disc_row.consensus else None,
                }
            round_rows = _ddao_das.get_rounds(_conn_das, disc_id)
        finally:
            _conn_das.close()

        for r in round_rows:
            submissions.append({
                "agent": r.agent,
                "round": r.round_number,
                "verdict": str(r.verdict or ""),
                "position": str(r.content or "")[:500],
                "points": [],
                "submitted_at": r.created_at,
                "content": str(r.content or "")[:5000],
            })
        submissions.sort(key=lambda s: (s["round"], s["agent"]))
        result["submissions"] = submissions
    except Exception as e:
        logger.warning("dashboard-ui discussion SQLite read failed: %s", e, exc_info=True)

    # Build timeline from state + submissions
    created = state.get("created_at", "")
    if created:
        result["timeline"].append({"event": "created", "at": str(created)})
    for s in submissions:
        result["timeline"].append({
            "event": "submitted",
            "agent": s["agent"],
            "round": s["round"],
            "verdict": s["verdict"],
            "at": s["submitted_at"],
        })
    consensus_at = state.get("consensus_at", "")
    if consensus_at:
        result["timeline"].append({"event": "consensus", "at": str(consensus_at),
                                   "verdict": str(state.get("consensus_verdict", ""))})
    closed_at = state.get("closed_at", "")
    if closed_at:
        result["timeline"].append({"event": "closed", "at": str(closed_at)})

    # --- 2. Live agent activity (discussion-specific) ---

    # --- 2. Live agent activity (discussion-specific) ---
    seen_pids: set[int] = set()

    # Collect inbox PIDs for this discussion
    inbox_agents: dict[int, dict] = {}
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(project_dir))
        try:
            init_db(conn)
            rows = conn.execute(
                "SELECT pid, target_agent, task_id FROM inbox "
                "WHERE pid IS NOT NULL AND status IN ('launched','running') "
                "AND (task_id LIKE ? OR task_id LIKE ?)",
                (f"{disc_id}/%", f"{disc_id}%"),
            ).fetchall()
            for r in rows:
                try:
                    inbox_agents[int(r[0])] = {"agent": str(r[1]), "task": str(r[2])}
                except (ValueError, TypeError):
                    pass
        finally:
            conn.close()
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    # Build snapshot of running processes
    running_procs: dict[int, tuple[str, str, str]] = {}
    try:
        ps_out = _sp.run(["ps", "ax", "-o", "pid=,pcpu=,args=,etime="], capture_output=True, text=True).stdout
        for line in ps_out.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid_str, cpu, rest = parts[0], parts[1], parts[2]
            fields = rest.rsplit(None, 1)
            if len(fields) < 2:
                continue
            cmd, elapsed = fields[0], fields[1]
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            running_procs[pid] = (cpu, cmd, elapsed)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    # Inbox-tracked agents for this discussion
    for pid, info in inbox_agents.items():
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        task_short = info["task"].rsplit("/", 1)[-1] if "/" in info["task"] else info["task"]
        if pid in running_procs:
            cpu, cmd, elapsed = running_procs[pid]
            result["agents"].append({"pid": str(pid), "cpu": f"{cpu}%",
                          "cmd": f"{info['agent']} [{task_short}]", "elapsed": elapsed})
        else:
            result["agents"].append({"pid": str(pid), "cpu": "—",
                          "cmd": f"{info['agent']} [{task_short}] (exited)", "elapsed": "—"})

    project_str = str(project_dir.resolve())

    # Running processes not in inbox (user's own agent sessions — filtered strictly)
    for pid, (cpu, cmd, elapsed) in running_procs.items():
        if pid in seen_pids:
            continue
        if not any(a in cmd.lower() for a in ("claude", "codex", "gemini")):
            continue
        if project_str not in cmd:
            if not any(m in cmd for m in (".superharness", "--task", "--project", "delegate-to-")):
                continue
        seen_pids.add(pid)
        result["agents"].append({"pid": str(pid), "cpu": f"{cpu}%", "cmd": cmd[:50], "elapsed": elapsed})

    # --- 3. Launcher logs ---
    if launcher_logs.exists():
        for lf in sorted(launcher_logs.glob(f"*{disc_id}*"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                size = lf.stat().st_size
                name = str(lf.name)
                if name.endswith(".log"):
                    result["logs"].append({"name": name, "size_kb": round(size / 1024, 1)})
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
    result["total_submissions"] = len(result["submissions"])
    result["total_agents"] = len(result["agents"])
    result["total_logs"] = len(result["logs"])
    return result


def task_log_content(project_dir: Path, task_id: str, agent: str, lines: int = 0) -> dict:
    """Retrieve live launcher log content for a task+agent.

    Args:
        project_dir: Project root directory
        task_id: Task ID
        agent: Agent name (optional, if empty will match any agent)
        lines: If > 0, return only last N lines

    Returns:
        dict with keys: task, agent, exists, content, log, log_file, size_bytes
        (includes both 'content' and 'log' for compatibility)
    """
    harness = project_dir / ".superharness"
    log_dir = harness / "launcher-logs"

    result: dict = {
        "task": task_id,
        "agent": agent,
        "exists": False,
        "content": "",
        "log": "",
        "log_file": None,
        "size_bytes": 0,
    }

    if not log_dir.exists():
        result["log"] = "(no log file found)"
        return result

    # Find most recent log file matching task-agent-*.log or task-*-*.log pattern
    if agent:
        pattern = f"{task_id}-{agent}-*.log"
    else:
        pattern = f"{task_id}-*.log"
    matching = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    # Fallback: try glob with underscore separator (discussion round files)
    if not matching and agent:
        safe_task = task_id.replace("/", "_")
        pattern2 = f"*{safe_task}*{agent}*.log"
        matching = sorted(log_dir.glob(pattern2), key=lambda p: p.stat().st_mtime, reverse=True)

    if matching:
        log_file = matching[0]
        result["exists"] = True
        result["log_file"] = str(log_file.relative_to(project_dir))
        try:
            content = log_file.read_text(errors="replace")
            
            import re
            # Strip ANSI escape sequences
            content = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', content)
            # Box-drawing and terminal framing
            content = re.sub(r'[╭╮╰╯─│┌┐└┘├┤┬┴┼▐▌▛▜▀▄▘▝█]', '', content)
            # Nerd Font icons and powerline symbols (U+E000-U+F8FF and U+2500+)
            content = re.sub(r'[\ue000-\uf8ff\u2500-\u259f\u25a0-\u25ff]', '', content)
            # Control characters (except newline and tab)
            content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', content)
            # Strip lines that are only whitespace or consist only of terminal artifacts
            content = '\n'.join(l for l in content.splitlines() if l.strip() and len(l.strip()) > 1)
            # Collapse multiple spaces
            content = re.sub(r' {3,}', '  ', content)
            # Collapse blank lines
            content = re.sub(r'\n{3,}', '\n\n', content)
            # Remove terminal cursor positioning artifacts (lines with only digits+spaces)
            content = re.sub(r'^\s*\d+\s*$', '', content, flags=re.MULTILINE)
            # Remove common terminal noise patterns
            content = content.replace('^D', '')
            content = content.replace('✳', '')
            # Strip all non-ASCII characters (U+0080 and above) for readability
            content = re.sub(r'[^\x00-\x7f]', '', content)
            # Remove lines that are only whitespace/symbols after ASCII strip
            content = '\n'.join(l for l in content.splitlines() if l.strip() and len(l.strip()) > 2)

            # Activity summary
            content_lower = content.lower()
            summary = []
            if "plan mode" in content_lower: summary.append("Phase: PLANNING")
            elif "implement" in content_lower: summary.append("Phase: IMPLEMENTATION")
            errs = re.findall(r'(?:error|failed|exception).*', content_lower)
            if errs: summary.append(f"Errors: {errs[-1][:80]}")
            result["activity"] = "\n".join(summary) if summary else "Working..."

            if lines > 0:
                all_lines = content.splitlines()
                content = "\n".join(all_lines[-lines:])
            result["content"] = content
            result["log"] = content
            result["size_bytes"] = log_file.stat().st_size
        except Exception as exc:
            error_msg = f"(error reading log: {exc})"
            result["content"] = error_msg
            result["log"] = error_msg
    else:
        result["log"] = "(no log file found)"

    # Check SDK session JSONL for sub-agent activity
    sdk_status = _detect_sdk_activity(project_dir)
    if sdk_status:
        result["sdk_status"] = sdk_status
        if result["log"] and not result["log"].startswith("(no log"):
            result["log"] += f"\n\n--- {sdk_status} ---"
            result["content"] = result["log"]

    # Live diff: show what the agent is changing right now
    git_diff = _git_diff_stat(project_dir)
    if git_diff:
        result["git_diff"] = git_diff
        if result["log"] and not result["log"].startswith("(no log"):
            result["log"] += f"\n\n--- files changed ---\n{git_diff}"
            result["content"] = result["log"]

    return result


def _git_diff_stat(project_dir: Path) -> str:
    """Return compact git diff --stat for uncommitted changes."""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "diff", "--stat", "--no-color", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
            cwd=str(project_dir),
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    return ""


def _detect_sdk_activity(project_dir: Path) -> str:
    """Scan the newest SDK session JSONL for current activity."""
    import json as _json
    safe_path = str(project_dir).replace("/", "-")
    session_dir = Path.home() / ".claude" / "projects" / safe_path
    if not session_dir.exists():
        return ""
    candidates = sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return ""
    jsonl = candidates[0]
    try:
        # Read last few lines to detect current activity
        with open(jsonl, "r", encoding="utf-8") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last 8KB
            f.seek(max(0, size - 8192))
            tail = f.read()
        last_tool = ""
        last_text = ""
        for line in tail.strip().splitlines():
            if not line.strip():
                continue
            try:
                d = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if d.get("type") == "assistant":
                msg = d.get("message", {})
                for block in msg.get("content", []):
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            if name == "Agent":
                                desc = inp.get("description", "")
                                return f"sub-agent running: {desc}" if desc else "sub-agent running"
                            last_tool = name
                        elif block.get("type") == "text":
                            last_text = block.get("text", "")[:100]
        if last_tool:
            return f"last tool: {last_tool}"
        return ""
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return ""


def contract_owners(contract_file: Path) -> list[str]:
    """Read distinct task owners from state_reader (SQLite-only)."""
    project_dir = str(contract_file.parent.parent)
    raw_tasks: list[dict] = []
    try:
        from superharness.engine import state_reader as _sr
        raw_tasks = _sr.get_tasks(project_dir)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    owners = []
    seen: set[str] = set()
    for t in raw_tasks:
        if isinstance(t, dict):
            o = t.get("owner")
            if o and o not in seen:
                owners.append(o)
                seen.add(o)
    return owners


from superharness.engine.state_reader import parse_iso_utc as parse_utc_timestamp


def watcher_health(runtime: dict, items: list[dict], now_utc: str, heartbeat: dict | None = None) -> dict:
    now_dt = parse_utc_timestamp(now_utc)
    state = runtime.get("state", "")
    loaded = bool(runtime.get("loaded", False))
    last_exit_code = str(runtime.get("last_exit_code", "")).strip()
    run_interval_seconds = int(runtime.get("run_interval_seconds", 0) or 0)
    pending_items = [x for x in items if x.get("status", "") == "pending"]
    pending_count = len(pending_items)
    stale_count = sum(1 for x in items if x.get("status", "") == "stale")
    failed_count = sum(1 for x in items if x.get("status", "") == "failed")

    if not loaded and heartbeat and heartbeat.get("level") == "ok":
        if stale_count > 0 or failed_count > 0:
            return {
                "level": "warn",
                "message": (
                    "Watcher running in foreground/manual mode "
                    f"(heartbeat active), but backlog issues exist (stale={stale_count}, failed={failed_count})."
                ),
                "pending_count": pending_count,
                "stale_count": stale_count,
                "failed_count": failed_count,
            }
        return {
            "level": "ok",
            "message": "Watcher running in foreground/manual mode (heartbeat active).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }

    if not loaded:
        return {
            "level": "bad",
            "message": "Watcher is not running. Run 'shux dashboard' to start the dashboard and watcher.",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }
    if state == "not running" and run_interval_seconds > 0 and last_exit_code in {"0", "(never exited)"}:
        if stale_count > 0 or failed_count > 0:
            return {
                "level": "warn",
                "message": f"Watcher loaded and idle between runs ({run_interval_seconds}s), but backlog issues exist (stale={stale_count}, failed={failed_count}).",
                "pending_count": pending_count,
                "stale_count": stale_count,
                "failed_count": failed_count,
            }
        return {
            "level": "ok",
            "message": f"Watcher loaded and idle between runs (every {run_interval_seconds}s).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }
    if state in {"running", "active"} and run_interval_seconds > 0 and last_exit_code in {"0", "(never exited)"}:
        if stale_count > 0 or failed_count > 0:
            return {
                "level": "warn",
                "message": f"Watcher loaded and active (every {run_interval_seconds}s), but backlog issues exist (stale={stale_count}, failed={failed_count}).",
                "pending_count": pending_count,
                "stale_count": stale_count,
                "failed_count": failed_count,
            }
        return {
            "level": "ok",
            "message": f"Watcher loaded and active (every {run_interval_seconds}s).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }
    if state != "running" and state != "not running":
        return {
            "level": "warn",
            "message": f"Watcher loaded but in state '{state}' (last exit={last_exit_code or 'unknown'}).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }

    oldest_pending_age = None
    if now_dt:
        ages = []
        for item in pending_items:
            created = parse_utc_timestamp(item.get("created_at", ""))
            if created is not None:
                ages.append(int((now_dt - created).total_seconds()))
        if ages:
            oldest_pending_age = max(ages)

    if oldest_pending_age is not None and oldest_pending_age > 300:
        mins = oldest_pending_age // 60
        return {
            "level": "warn",
            "message": f"Watcher running but pending queue is aging ({mins}m oldest). Consider Restart watcher.",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
            "oldest_pending_age_seconds": oldest_pending_age,
        }

    if stale_count > 0 or failed_count > 0:
        return {
            "level": "warn",
            "message": f"Watcher running with backlog issues (stale={stale_count}, failed={failed_count}).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }

    return {
        "level": "ok",
        "message": f"Watcher running and healthy. pending={pending_count}, stale={stale_count}, failed={failed_count}.",
        "pending_count": pending_count,
        "stale_count": stale_count,
        "failed_count": failed_count,
    }


def _agent_status_health(project_dir: Path, stale_seconds: int = 120) -> dict:
    """Return agent status health for all runtimes — no hardcoded runtime names.

    Uses heartbeat contract v1 (engine.agent_status).  Falls back gracefully
    if the module is unavailable so existing deployments are not broken.
    """
    try:
        from superharness.engine.agent_status import agent_status_health
        return agent_status_health(project_dir, stale_seconds=stale_seconds)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return {"agents": {}}


def heartbeat_health(project_dir: Path, stale_seconds: int = 120) -> dict:
    watcher_project = Path(str(watcher_config(project_dir).get("watcher_project", str(project_dir))))
    hb_root = watcher_project if (watcher_project / ".superharness").exists() else project_dir
    hb_file = hb_root / ".superharness" / "watcher.heartbeat"
    if not hb_file.exists():
        return {
            "level": "warn",
            "message": "No heartbeat file — watcher may not be running.",
            "age_seconds": -1,
        }
    raw = hb_file.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return {
            "level": "warn",
            "message": "Heartbeat file is empty — watcher may not be running.",
            "age_seconds": -1,
        }
    hb_dt = parse_utc_timestamp(raw.splitlines()[0])
    if hb_dt is None:
        return {
            "level": "warn",
            "message": f"Heartbeat timestamp unparseable: {raw[:40]}",
            "age_seconds": -1,
        }
    now_dt = dt.datetime.now(tz=dt.timezone.utc)
    age = int((now_dt - hb_dt).total_seconds())
    via_worker = hb_root != project_dir
    if age >= stale_seconds:
        mins = age // 60
        return {
            "level": "warn",
            "message": f"Heartbeat stale ({mins}m ago){' — worker project' if via_worker else ''} — watcher may have crashed.",
            "age_seconds": age,
        }
    return {
        "level": "ok",
        "message": f"Heartbeat OK ({age}s ago){' — worker project' if via_worker else ''}.",
        "age_seconds": age,
    }


def contract_id(contract_file: Path) -> str:
    """Read the contract id from state_reader (SQLite)."""
    project_dir = str(contract_file.parent.parent)
    try:
        from superharness.engine import state_reader as _sr
        doc = _sr.get_contract_doc(project_dir)
        return str(doc.get("id", "") or "")
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return ""


def contract_tasks(contract_file: Path) -> list[dict]:
    """Return all top-level contract tasks with id, title, status, owner.

    Reads exclusively from state_reader (SQLite). The contract_file path is used
    only to derive project_dir; the YAML file is never read.
    """
    project_dir = str(contract_file.parent.parent)
    raw_tasks: list[dict] = []
    try:
        from superharness.engine import state_reader as _sr
        raw_tasks = _sr.get_top_level_tasks(project_dir)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    tasks = []
    for t in raw_tasks:
        tasks.append({
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": str(t.get("status", "todo")),
            "owner": str(t.get("owner", "")),
            "review_target": _review_target_for_owner(str(t.get("owner", ""))) if str(t.get("status", "todo")) == "review_requested" else "",
            "verified": bool(t.get("verified", False)),
            "workflow": str(t.get("workflow", "")),
            "scheduled_after": str(t.get("scheduled_after", "")),
            "due_by": str(t.get("due_by", "")),
            "depends_on": (t.get("blocked_by") or t.get("depends_on") or []) if isinstance(t.get("blocked_by") or t.get("depends_on"), list) else [x.strip() for x in str(t.get("blocked_by") or t.get("depends_on") or "").strip("[]").split(",") if x.strip()],
            "worktree_path": str(t.get("worktree_path", "")),
        })
    return tasks


def pending_approvals(handoff_dir: Path, project_dir: Path | None = None) -> list[dict]:
    """Return handoffs awaiting user approval, reading from SQLite."""
    rows: list[dict] = []
    _project_dir = project_dir if project_dir is not None else handoff_dir.parent.parent
    try:
        from superharness.engine import state_reader as _sr
        handoffs = _sr.get_handoffs(str(_project_dir))
        for h in handoffs:
            status = str(h.get("status", ""))
            meta = h.get("metadata") or {}
            gate = meta.get("approval_gate") or {}
            required = bool(gate.get("required", False))
            approved = bool(gate.get("approved_by_user", False))
            pending = status == "pending_user_approval" or (required and not approved)
            if pending:
                rows.append({
                    "task": str(h.get("task_id", "")),
                    "status": status,
                    "required": required,
                    "approved_by_user": approved,
                    "markdown_report": str(meta.get("markdown_report", "")),
                })
    except Exception:
        pass
    return rows


def plan_proposals(harness_dir: Path) -> list[dict]:
    """Return contract tasks with status=plan_proposed that await user confirmation.

    Prefers state_reader (SQLite-aware); falls back to YAML.
    """
    rows: list[dict] = []
    contract_file = harness_dir / "contract.yaml"
    handoff_dir = harness_dir / "handoffs"

    all_tasks: list[dict] | None = None
    project_dir = str(harness_dir.parent)
    try:
        from superharness.engine import state_reader as _sr
        all_tasks = _sr.get_tasks(project_dir)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    if all_tasks is None:
        return rows

    tasks = all_tasks or []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") != "plan_proposed":
            continue
        task_id = t.get("id", "")
        owner = t.get("owner", "")
        title = t.get("title", task_id)
        # Find matching handoff for the plan content — from SQLite
        summary = t.get("summary", "")
        handoff_summary = ""
        try:
            import yaml as _yaml_pp
            from superharness.engine import state_reader as _sr_pp
            task_handoffs = _sr_pp.get_handoffs(project_dir, task_id=task_id)
            for row in reversed(task_handoffs):
                if str(row.get("status", "")) == "plan_proposed":
                    content_text = row.get("content") or ""
                    hdata: dict = {}
                    if content_text:
                        try:
                            parsed = _yaml_pp.safe_load(content_text)
                            if isinstance(parsed, dict):
                                hdata = parsed
                        except Exception:
                            pass
                    handoff_summary = hdata.get("summary", "") or hdata.get("scope", "")
                    if isinstance(handoff_summary, list):
                        handoff_summary = "\n".join(str(x) for x in handoff_summary)
                    break
        except Exception as e:
            logger.warning("dashboard-ui plan_proposals handoff read failed: %s", e, exc_info=True)
        rows.append({
            "task": task_id,
            "title": title,
            "from": owner,
            "summary": handoff_summary or summary or title,
        })
    return rows


def _set_task_status(harness_dir: Path, task_id: str, to_status: str, from_status: str | None = None) -> dict:
    """Set a contract task status. Uses unified state_writer (YAML + SQLite)."""
    project_dir = str(harness_dir.parent)
    try:
        from superharness.engine import state_writer
        ok = state_writer.set_task_status(project_dir, task_id, to_status, from_status=from_status)
        if ok:
            return {"ok": True, "task": task_id, "status": to_status}
        
        # Determine specific error
        from superharness.engine import state_reader
        task = state_reader.get_task(project_dir, task_id)
        if not task:
            return {"ok": False, "error": f"task {task_id} not found"}
        if from_status and task.get("status") != from_status:
            return {"ok": False, "error": f"task {task_id} is {task.get('status')!r}, expected {from_status!r}"}
        return {"ok": False, "error": f"transition for {task_id} failed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _contract_task(harness_dir: Path, task_id: str) -> dict | None:
    """Fetch a single task by ID. Uses state_reader (YAML + SQLite)."""
    project_dir = str(harness_dir.parent)
    try:
        from superharness.engine import state_reader
        return state_reader.get_task(project_dir, task_id)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return None


def _review_target_for_owner(owner: str) -> str:
    if owner == "claude-code":
        return "codex-cli"
    return "claude-code"


def board_view(contract_file: Path) -> dict:
    """Return contract tasks grouped into operator board columns.

    Columns: todo | plan | in_progress | review | done
    review_queue: tasks in review_requested / review_passed / review_failed states.
    totals: per-column task count.
    Prefers state_reader (SQLite-aware); falls back to YAML.
    """
    from superharness.engine.next_action import STATUS_TO_COL as _STATUS_TO_COL
    # Add plan_confirmed alias (legacy status)
    _STATUS_TO_COL = dict(_STATUS_TO_COL)
    _STATUS_TO_COL["plan_confirmed"] = "plan"
    _REVIEW_QUEUE_STATUSES = {"review_requested", "review_passed", "review_failed"}
    empty: dict = {col: [] for col in ("todo", "plan", "in_progress", "review", "done")}

    raw_tasks: list[dict] | None = None
    project_dir = str(contract_file.parent.parent)
    _in_harness = contract_file.parent.name == ".superharness" and contract_file.parent.exists()
    if _in_harness:
        try:
            from superharness.engine import state_reader as _sr
            raw_tasks = _sr.get_top_level_tasks(project_dir)
        except Exception as e:
            logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
            pass
    if raw_tasks is None:
        return {"columns": empty, "review_queue": [], "totals": {col: 0 for col in empty}}

    columns: dict = {col: [] for col in ("todo", "plan", "in_progress", "review", "done")}
    review_queue: list = []

    for t in raw_tasks:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", "todo"))
        col = _STATUS_TO_COL.get(st, "todo")
        entry = {
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": st,
            "owner": str(t.get("owner", "")),
            "verified": bool(t.get("verified", False)),
            "blocked_by": _normalize_blocked_by(t.get("blocked_by", "")),
        }
        columns[col].append(entry)
        if st in _REVIEW_QUEUE_STATUSES:
            review_queue.append(entry)

    totals = {col: len(tasks) for col, tasks in columns.items()}
    return {"columns": columns, "review_queue": review_queue, "totals": totals}


def _propose_plan_handoff(
    harness_dir: Path,
    task_id: str,
    *,
    plan_summary: str,
    tdd_red: str,
    tdd_green: str,
    tdd_refactor: str,
    risks: str = "",
    author: str = "owner",
) -> dict:
    """Write a plan handoff for a todo task and transition its status.

    Used by the dashboard "Propose Plan" action so the owner can author a
    plan inline without waiting for an agent. Requires the task to be in
    'todo' status; transitions it to 'plan_proposed'.
    """
    import yaml  # noqa: F811
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    handoff_dir = harness_dir / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    # Transition contract status todo -> plan_proposed
    status_result = _set_task_status(harness_dir, task_id, "plan_proposed", from_status="todo")
    if not status_result.get("ok"):
        return status_result

    safe_ts = now.replace(":", "-")
    handoff_file = handoff_dir / f"{task_id}-plan-{safe_ts}-{author}.yaml"
    doc = {
        "task":   task_id,
        "phase":  "plan",
        "status": "plan_proposed",
        "from":   author,
        "to":     "owner",
        "date":   now,
        "plan":   plan_summary.strip() or "(plan body pending)",
        "tdd": {
            "red":      tdd_red.strip()      or "(red phase pending)",
            "green":    tdd_green.strip()    or "(green phase pending)",
            "refactor": tdd_refactor.strip() or "(refactor phase pending)",
        },
    }
    if risks.strip():
        doc["risks"] = risks.strip()

    try:
        handoff_file.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False))
    except Exception as exc:  # shipguard:ignore PY-007
        # Roll back status transition so task doesn't sit in plan_proposed without a handoff.
        _set_task_status(harness_dir, task_id, "todo", from_status="plan_proposed")
        return {"ok": False, "error": f"failed to write handoff: {exc}"}

    return {"ok": True, "task": task_id, "handoff": str(handoff_file.name), "status": "plan_proposed"}


def _confirm_plan(harness_dir: Path, task_id: str) -> dict:
    """Confirm a plan_proposed task: set contract task to todo, update handoff."""
    import yaml  # noqa: F811
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    handoff_dir = harness_dir / "handoffs"
    errors = []

    # SQLite-primary transition (via state_writer which handles both)
    project_dir = str(harness_dir.parent)
    try:
        from superharness.engine import state_writer
        ok = state_writer.set_task_status(
            project_dir, task_id, "todo",
            from_status="plan_proposed",
            plan_confirmed_at=now
        )
        if not ok:
            # Check if task exists to give better error
            from superharness.engine import state_reader
            task = state_reader.get_task(project_dir, task_id)
            if not task:
                errors.append(f"task {task_id} not found")
            else:
                errors.append(f"task {task_id} transition plan_proposed -> todo failed (current: {task.get('status')})")
    except Exception as e:
        errors.append(f"state_writer error: {e}")

    # Update matching handoff status via SQLite — YAML file update is export-only
    try:
        from superharness.engine import state_reader as _sr_cp
        task_handoffs_cp = _sr_cp.get_handoffs(str(harness_dir.parent), task_id=task_id)
        plan_row = next(
            (r for r in reversed(task_handoffs_cp) if str(r.get("status", "")) == "plan_proposed"),
            None,
        )
        if plan_row:
            import yaml as _yaml_cp
            from superharness.engine import state_writer as _sw_cp
            content_text_cp = plan_row.get("content") or ""
            hdata: dict = {}
            if content_text_cp:
                try:
                    parsed_cp = _yaml_cp.safe_load(content_text_cp)
                    if isinstance(parsed_cp, dict):
                        hdata = parsed_cp
                except Exception:
                    pass
            hdata["status"] = "plan_confirmed"
            gate = hdata.get("plan_gate", {}) or {}
            gate.update({"confirmed_by_user": True, "confirmed_at": now, "confirmed_by": "owner"})
            hdata["plan_gate"] = gate
            _sw_cp.write_handoff_to_db(str(harness_dir.parent), hdata, task_id=task_id, phase="plan")
    except Exception as e:
        errors.append(f"handoff update error: {e}")

    result = {"ok": not errors, "task": task_id, "confirmed_at": now}
    if errors:
        result["errors"] = errors
    return result


def watcher_config(project_dir: Path) -> dict:
    cfg_map = {
        "watcher_project": str(project_dir),
        "interval_seconds": 15,
        "recover_timeout_minutes": 3,
        "recover_action": "retry",
        "launcher_timeout_seconds": 900,
        "target": "both",
        "codex_bypass": False,
        "python_executable": sys.executable,
    }
    cfg = project_dir / ".superharness" / "watcher.yaml"
    if not cfg.exists():
        return cfg_map
    for raw in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("watcher_project:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val:
                candidate = Path(val).expanduser().resolve()
                if (candidate / ".superharness").exists():
                    cfg_map["watcher_project"] = str(candidate)
        elif line.startswith("interval_seconds:"):
            raw_val = line.split(":", 1)[1].strip()
            if raw_val.isdigit() and int(raw_val) > 0:
                cfg_map["interval_seconds"] = int(raw_val)
        elif line.startswith("recover_timeout_minutes:"):
            raw_val = line.split(":", 1)[1].strip()
            if raw_val.isdigit():
                cfg_map["recover_timeout_minutes"] = int(raw_val)
        elif line.startswith("recover_action:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val in {"stale", "retry"}:
                cfg_map["recover_action"] = val
        elif line.startswith("launcher_timeout_seconds:"):
            raw_val = line.split(":", 1)[1].strip()
            if raw_val.isdigit():
                cfg_map["launcher_timeout_seconds"] = int(raw_val)
        elif line.startswith("target:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val in {"both"} | set(KNOWN_AGENTS):
                cfg_map["target"] = val
        elif line.startswith("codex_bypass:"):
            cfg_map["codex_bypass"] = line.split(":", 1)[1].strip().lower() == "true"
        elif line.startswith("python_executable:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val:
                cfg_map["python_executable"] = val
    return cfg_map


def board_tasks(contract_file: Path) -> dict[str, list[dict]]:
    """Group contract tasks by board column (todo/plan/active/review/done/stopped)."""
    from superharness.engine.next_action import STATUS_TO_COL
    # Adapt canonical mapping to board_tasks column names
    _COL_ADAPT = {"in_progress": "active"}
    _STATUS_TO_COL = {k: _COL_ADAPT.get(v, v) for k, v in STATUS_TO_COL.items()}
    # Add stopped as a separate column
    _STATUS_TO_COL["stopped"] = "stopped"
    columns: dict[str, list[dict]] = {
        "todo": [], "plan": [], "active": [], "review": [], "done": [], "stopped": []
    }

    if not contract_file.exists():
        return {}

    raw_tasks: list[dict] | None = None
    project_dir = str(contract_file.parent.parent)
    _in_harness = contract_file.parent.name == ".superharness" and contract_file.parent.exists()
    
    # SQLite is the canonical source of truth (post-YAML migration). The
    # legacy YAML fallback was removed — any test fixture must seed SQLite
    # via tasks_dao.upsert, not write contract.yaml.
    try:
        from superharness.engine import state_reader as _sr
        raw_tasks = _sr.get_top_level_tasks(project_dir)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    if not raw_tasks:
        return columns # Return empty columns instead of {} to avoid KeyError

    for t in (raw_tasks or []):
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", "todo"))
        col = _STATUS_TO_COL.get(st, "todo")
        columns[col].append({
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": st,
            "owner": str(t.get("owner", "")),
            "verified": bool(t.get("verified", False)),
        })

    return columns


def review_queue(contract_file: Path) -> list[dict]:
    """Return tasks in review states ordered by urgency (review_failed first)."""
    _REVIEW_STATUSES = {"report_ready", "review_requested", "review_passed", "review_failed"}
    _URGENCY = {
        "review_failed": 0,
        "report_ready": 1,
        "review_requested": 2,
        "review_passed": 3,
    }

    raw_tasks: list[dict] | None = None
    project_dir = str(contract_file.parent.parent)
    _in_harness = contract_file.parent.name == ".superharness" and contract_file.parent.exists()
    
    # SQLite is the canonical source of truth (post-YAML migration). The
    # legacy YAML fallback was removed — any test fixture must seed SQLite
    # via tasks_dao.upsert, not write contract.yaml.
    try:
        from superharness.engine import state_reader as _sr
        raw_tasks = _sr.get_top_level_tasks(project_dir)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    if not raw_tasks:
        return []

    queue = []
    for t in raw_tasks:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", ""))
        if st not in _REVIEW_STATUSES:
            continue
        queue.append({
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": st,
            "owner": str(t.get("owner", "")),
            "review_target": _review_target_for_owner(str(t.get("owner", ""))),
            "verified": bool(t.get("verified", False)),
            "urgency": _URGENCY.get(st, 9),
        })

    return sorted(queue, key=lambda x: x["urgency"])


def budget_signals(project_dir: Path) -> dict:
    """Extract per-agent budget/usage signals from .superharness/agents/*.status.yaml."""
    try:
        from superharness.engine.agent_status import read_all_agent_statuses
        records = read_all_agent_statuses(project_dir)
        signals: dict = {}
        for runtime, record in records.items():
            if record and record.budget:
                signals[runtime] = record.budget if isinstance(record.budget, dict) else dict(record.budget)
        return {"agents": signals, "available": True}
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        # Fallback: manually scan agents/*.status.yaml for budget fields
        agents_dir = project_dir / ".superharness" / "agents"
        if not agents_dir.exists():
            return {"agents": {}, "available": False}
        signals = {}
        try:
            import yaml  # noqa: F811
            for f in agents_dir.glob("*.status.yaml"):  # noqa: state-read — legacy budget signal scan; budgets in SQLite when migration v25 has populated rows
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}  # noqa: state-read — legacy budget signal scan
                    runtime = data.get("runtime", f.stem.replace(".status", ""))
                    if "budget" in data and data["budget"]:
                        signals[runtime] = data["budget"]
                except Exception as e:
                    logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                    continue
        except Exception as e:
            logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
            pass
        return {"agents": signals, "available": bool(signals)}


def project_label(project_dir: Path) -> str:
    # Match install-launchd-inbox-watcher.sh: basename | tr -cs 'A-Za-z0-9' '-'
    import re
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project_dir.name).strip("-")
    if not slug:
        slug = "project"
    return f"com.superharness.inbox.{slug}"


# ── Behavioral profile data (Iteration 7) ────────────────────────────────────

def _profile_data(project_dir: Path) -> dict:
    """Return behavioral profile + recent trials for the dashboard card."""
    import json as _json
    upath = os.path.join(os.path.expanduser("~"), ".config", "superharness", "behavioral")
    profiles = {}
    if os.path.isdir(upath):
        for fname in os.listdir(upath):
            if fname.endswith(".json") and not fname.startswith("_"):
                try:
                    with open(os.path.join(upath, fname)) as f:
                        profiles[fname.replace(".json", "")] = _json.load(f)
                except Exception:
                    pass

    trials = []
    try:
        conn = db.get_connection(str(project_dir))
        try:
            for row in conn.execute(
                "SELECT * FROM profile_trials ORDER BY trial_started_at DESC LIMIT 10"
            ).fetchall():
                trials.append({
                    "id": row["id"],
                    "profile_key": row["profile_key"],
                    "old_value": row["old_value"],
                    "new_value": row["new_value"],
                    "outcome": row["outcome"],
                    "reverted": bool(row["reverted"]),
                    "reinforced": bool(row["reinforced"]),
                    "started_at": row["trial_started_at"],
                })
        finally:
            conn.close()
    except Exception:
        pass

    return {
        "profiles": {k: {kk: vv for kk, vv in v.items() if kk != "updated_at"}
                     for k, v in profiles.items()},
        "trials": trials,
        "has_data": len(profiles) > 0,
    }


class Handler(BaseHTTPRequestHandler):
    project_dir: Path
    label: str
    refresh_seconds: int
    scripts_dir: Path
    auth_token: str
    idle_timeout: int = 0
    last_ping: float = 0.0

    def _db_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        conn = db.get_connection(str(self.project_dir))
        db.init_db(conn)
        return conn

    def _set_common_headers(self, content_type: str, body_len: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(body_len))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._set_common_headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.replace("__AUTH_TOKEN__", json.dumps(self.auth_token))
        body = body.replace("__TIMEOUT_SECONDS__", str(self.idle_timeout))
        body = body.encode("utf-8")
        self.send_response(200)
        self._set_common_headers("text/html; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _fmt: str, *args) -> None:
        return

    def _run_cmd(self, args: list[str], timeout: int = 30) -> dict:
        run = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
        return {
            "exit_code": run.returncode,
            "stdout": run.stdout.strip(),
            "stderr": run.stderr.strip(),
            "cmd": " ".join(shlex.quote(a) for a in args),
        }

    # Set from the real bind address at server startup. Deriving the expected
    # origin from the request's own Host header (the original implementation)
    # made the comparison circular — it always matched, so it was no defence
    # at all against DNS rebinding.
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787

    _ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

    def _bound_address(self) -> tuple[str, int]:
        """The address actually bound, preferred over the class attributes.

        `main()` sets bind_host/bind_port after binding, but anything else that
        constructs this Handler (the integration suite, or any embedding code)
        would silently inherit the class defaults. Reading the live socket
        removes that coupling — and the defaults still cover a Handler built
        without a server, as the unit tests do.
        """
        srv = getattr(self, "server", None)
        addr = getattr(srv, "server_address", None) if srv is not None else None
        if addr:
            return str(addr[0]), int(addr[1])
        return self.bind_host, self.bind_port

    def _host_is_allowed(self) -> bool:
        """Reject requests whose Host header is not a loopback name.

        This is the anti-DNS-rebinding control. The server is already
        loopback-bind-enforced, but that does not help when the attacker owns
        the browser: they point evil.com at 127.0.0.1 and the browser happily
        connects, sending `Host: evil.com`. Checking Host breaks that, and it
        protects unauthenticated GETs too — which matters because `GET /`
        embeds the auth token in the page it serves.

        Only the hostname is checked, never the port. A browser sets Host from
        the URL, so an attacker cannot forge the hostname; the port carries no
        security signal. Comparing it also broke every non-default port, and
        the dashboard routinely picks one — it scans 8787-8806 for a free slot.
        """
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return False
        # Strip the port without mangling a bracketed IPv6 literal.
        if host.startswith("["):
            hostname = host.split("]")[0] + "]"
        elif ":" in host:
            hostname = host.rpartition(":")[0]
        else:
            hostname = host
        return hostname.lower() in self._ALLOWED_HOSTNAMES

    def _expected_origin(self) -> str:
        host, port = self._bound_address()
        return f"http://{host}:{port}"

    def _token_ok(self, token: str) -> bool:
        return bool(token) and secrets.compare_digest(token, self.auth_token or "")

    def _verify_read_auth(self) -> tuple[dict, int] | None:
        """Gate read-only GET /api/* routes behind the same token as mutations.

        No Origin/Referer check here (unlike `_verify_mutation_auth`): GETs
        don't mutate state, so they carry no CSRF risk, and non-browser
        clients (curl, scripts, this dashboard's own same-origin fetch calls)
        hold the token but may not send Origin/Referer at all.

        The token is normally read from the `X-Superharness-Token` header.
        `EventSource` (used by `/api/logs/stream`) cannot set custom request
        headers, so a `token` query parameter is accepted as a fallback for
        GETs only — never for the mutation path above.

        The Host check is not optional here. `GET /` is unauthenticated and
        injects the auth token into the page it serves, so a DNS-rebound page
        can read the token out of the DOM; without this check it could then
        replay it against the read routes and exfiltrate logs, handoffs, task
        reports and discussion content. Gating mutations alone leaves that
        half of the chain open.
        """
        if not self._host_is_allowed():
            return ({"error": "forbidden"}, 403)

        token = self.headers.get("X-Superharness-Token", "")
        if not token:
            token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        if not self._token_ok(token):
            return ({"error": "forbidden"}, 403)
        return None

    def _verify_mutation_auth(self) -> tuple[dict, int] | None:
        if not self._host_is_allowed():
            return ({"error": "forbidden"}, 403)

        token = self.headers.get("X-Superharness-Token", "")
        if not self._token_ok(token):
            return ({"error": "forbidden"}, 403)

        expected_origin = self._expected_origin()
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")

        # Absent Origin/Referer is deliberately allowed. CSRF is a browser-only
        # attack and browsers always send Origin on a cross-origin POST, so a
        # request with neither header did not come from a page — it came from a
        # client that already holds the token (curl, the test suite, scripts).
        # Rejecting those buys no security and breaks legitimate automation.
        #
        # What actually closes the rebinding chain is _host_is_allowed() plus
        # deriving expected_origin from the real bind address: a rebound request
        # carries Host: evil.com and is refused before reaching here, and a
        # direct cross-origin fetch carries Origin: http://evil.com and fails
        # the comparison below.
        if origin and origin != expected_origin:
            return ({"error": "forbidden"}, 403)
        if referer and not (referer == expected_origin or referer.startswith(expected_origin + "/")):
            return ({"error": "forbidden"}, 403)

        return None

    def _action(self, action: str, payload: dict | None = None) -> tuple[dict, int]:
        wcfg = watcher_config(self.project_dir)
        watcher_project = Path(str(wcfg.get("watcher_project", str(self.project_dir))))
        dispatch = str(self.scripts_dir / "inbox-dispatch.sh")
        recover = str(self.scripts_dir / "inbox-recover-stale.sh")
        normalize = str(self.scripts_dir / "inbox-normalize.sh")
        discuss = str(self.scripts_dir / "discuss.sh")
        install_watcher = str(self.scripts_dir / "install-launchd-inbox-watcher.sh")

        if action in {"watcher_start", "watcher_restart"}:
            watcher_python = str(wcfg.get("python_executable") or sys.executable)
            install_args = [
                watcher_python,
                "-m",
                "superharness.commands.watcher_worker",
                "--project",
                str(self.project_dir),
                "--worker",
                str(watcher_project),
                "--interval",
                str(int(wcfg.get("interval_seconds", 15))),
                "--recover-timeout-minutes",
                str(int(wcfg.get("recover_timeout_minutes", 3))),
                "--recover-action",
                str(wcfg.get("recover_action", "retry")),
                "--launcher-timeout",
                str(int(wcfg.get("launcher_timeout_seconds", 180))),
                "--to",
                str(wcfg.get("target", "both")),
            ]
            project_src = self.project_dir / "src"
            if project_src.is_dir() and os.name != "nt":
                existing_pythonpath = os.environ.get("PYTHONPATH", "").strip()
                pythonpath = str(project_src)
                if existing_pythonpath:
                    pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"
                install_args = ["/usr/bin/env", f"PYTHONPATH={pythonpath}"] + install_args
            if bool(wcfg.get("codex_bypass", False)):
                install_args.append("--codex-bypass")
            install_result = self._run_cmd(install_args, timeout=120)
            if install_result["exit_code"] != 0:
                return install_result, 200
            uid = os.getuid() if hasattr(os, "getuid") else 0
            kickstart_result = self._run_cmd(
                [
                    "launchctl",
                    "kickstart",
                    "-k",
                    f"gui/{uid}/{self.label}",
                ]
            )
            merged = {
                "exit_code": kickstart_result["exit_code"],
                "stdout": "\n".join(
                    x for x in [install_result.get("stdout", ""), kickstart_result.get("stdout", "")] if x
                ),
                "stderr": "\n".join(
                    x for x in [install_result.get("stderr", ""), kickstart_result.get("stderr", "")] if x
                ),
                "cmd": f"{install_result.get('cmd', '')} && {kickstart_result.get('cmd', '')}".strip(),
            }
            return merged, 200

        if action == "dispatch_print_codex":
            return self._run_cmd(["bash", dispatch, "--project", str(self.project_dir), "--to", "codex-cli", "--print-only"]), 200
        if action == "dispatch_print_claude":
            return self._run_cmd(["bash", dispatch, "--project", str(self.project_dir), "--to", "claude-code", "--print-only"]), 200
        if action == "recover_retry":
            return self._run_cmd(["bash", recover, "--project", str(self.project_dir), "--action", "retry", "--timeout-minutes", "20"]), 200
        if action == "recover_failed":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            items = inbox_items(inbox)
            failed_ids = [item["id"] for item in items if item.get("status") == "failed" and item.get("id")]
            recovered = 0
            if failed_ids:
                # SQLite-primary write
                try:
                    from superharness.engine.db import get_connection, init_db
                    from superharness.engine import inbox_dao
                    _now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _conn = get_connection(str(self.project_dir))
                    init_db(_conn)
                    for _id in failed_ids:
                        if inbox_dao.update_status(_conn, _id, from_status="failed", to_status="pending", now=_now):
                            recovered += 1
                    _conn.commit()
                    _conn.close()
                except Exception as e:
                    logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                    pass
                # YAML write (dual mode only)
                if inbox.exists():
                    try:
                        import yaml as _yaml
                        for item in items:
                            if item.get("status") == "failed":
                                item["status"] = "pending"
                                item.pop("failed_at", None)
                                item.pop("failed_reason", None)
                                item["pid"] = ""
                        with open(inbox, "w", encoding="utf-8") as fh:
                            fh.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
                            for item in items:
                                _yaml.dump([item], fh, default_flow_style=False, allow_unicode=True, sort_keys=True)
                    except Exception as e:
                        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                        pass
            return {"ok": True, "recovered": recovered}, 200
        if action == "normalize_stale":
            return self._run_cmd(["bash", normalize, "--project", str(self.project_dir), "--archive", "--drop-status", "stale"]), 200
        if action == "clear_resolved_inbox":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            contract = self.project_dir / ".superharness" / "contract.yaml"
            # contract_tasks() and inbox_items() are both state_reader-aware
            c_tasks = contract_tasks(contract)
            active_task_ids = {
                t["id"] for t in c_tasks
                if t.get("status") not in ("done", "archived")
                and t.get("id")
            }
            items = inbox_items(inbox)
            _KEEP_STATUSES = {"pending", "launched", "running"}
            to_remove = [
                item for item in items
                if item.get("task") not in active_task_ids
                and item.get("status") not in _KEEP_STATUSES
                and item.get("id")
            ]
            removed = len(to_remove)
            if removed > 0:
                remove_ids = {item["id"] for item in to_remove}
                # SQLite-primary: mark removed items as done (tombstone)
                try:
                    from superharness.engine.db import get_connection, init_db
                    from superharness.engine import inbox_dao
                    _now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _conn = get_connection(str(self.project_dir))
                    init_db(_conn)
                    for item in to_remove:
                        for _from in ("failed", "stale", "stopped", "done", "paused"):
                            if inbox_dao.update_status(_conn, item["id"], from_status=_from, to_status="done", now=_now):
                                break
                    _conn.commit()
                    _conn.close()
                except Exception as e:
                    logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                    pass
            return {"ok": True, "removed": removed}, 200
        if action.startswith("confirm_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _confirm_plan(self.project_dir / ".superharness", task_id)
            return result, (200 if result.get("ok") else 500)

        if action.startswith("disable_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "stopped")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("enable_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "todo", from_status="stopped")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("remove_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            try:
                from superharness.engine.db import get_connection, init_db
                _conn = get_connection(str(self.project_dir))
                try:
                    init_db(_conn)
                    _rc = _conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount
                    _conn.commit()
                    if _rc > 0:
                        return {"ok": True, "removed": task_id}, 200
                finally:
                    _conn.close()
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
            return ({"error": f"task '{task_id}' not found"}, 404)

        if action.startswith("set_owner:"):
            parts = action.split(":")
            if len(parts) < 3:
                return ({"error": "invalid action format"}, 400)
            task_id = parts[1]
            new_owner = parts[2]
            try:
                from superharness.engine.db import get_connection, init_db
                from superharness.engine import tasks_dao
                _conn = get_connection(str(self.project_dir))
                try:
                    init_db(_conn)
                    task_row = tasks_dao.get(_conn, task_id)
                    if task_row is None:
                        return ({"error": f"task '{task_id}' not found"}, 404)
                    tasks_dao.update(_conn, task_id, version=task_row.version, changes={"owner": new_owner})
                    _conn.commit()
                finally:
                    _conn.close()
                return {"ok": True, "task": task_id, "new_owner": new_owner}, 200
            except Exception as exc:
                return ({"error": str(exc)}, 500)

        if action.startswith("approve_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "plan_approved", from_status="plan_proposed")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("reject_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "todo", from_status="plan_proposed")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("verify_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [
                    sys.executable,
                    "-m",
                    "superharness.commands.verify",
                    "--project",
                    str(self.project_dir),
                    "--id",
                    task_id,
                    "--method",
                    "Verified from dashboard by operator",
                    "--result",
                    "pass",
                    "--actor",
                    "owner",
                ]
            ), 200

        if action.startswith("propose_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            p = payload or {}
            result = _propose_plan_handoff(
                self.project_dir / ".superharness",
                task_id,
                plan_summary=str(p.get("plan_summary", "")),
                tdd_red=str(p.get("tdd_red", "")),
                tdd_green=str(p.get("tdd_green", "")),
                tdd_refactor=str(p.get("tdd_refactor", "")),
                risks=str(p.get("risks", "")),
                author=str(p.get("author") or "owner"),
            )
            return result, (200 if result.get("ok") else 400)

        if action.startswith("delegate_plan:"):
            # Enqueue the task in plan-only mode so the agent proposes a TDD
            # plan and stops. The watcher picks it up, dispatches with
            # --plan-only, and the agent writes a plan handoff.
            parts = action.split(":", 2)
            task_id = parts[1] if len(parts) > 1 else ""
            target  = parts[2] if len(parts) > 2 else ""
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            task = _contract_task(harness_dir, task_id)
            if not task:
                return ({"error": f"task {task_id} not found"}, 404)
            if not target:
                target = str(task.get("owner", "") or "claude-code") or "claude-code"
            if target not in KNOWN_AGENTS:
                return ({"error": f"invalid target '{target}' — must be one of {KNOWN_AGENTS}"}, 400)
            # Already-enqueued guard.
            items = inbox_items(harness_dir / "inbox.yaml")
            active = INBOX_ACTIVE_STATUSES
            for item in items:
                if item.get("task") == task_id and item.get("status") in active:
                    return (
                        {"error": f"task '{task_id}' already enqueued (item {item.get('id')}, status={item.get('status')})"},
                        409,
                    )
            owner = str(task.get("owner", "") or "").strip()
            force_reassign = bool(owner and owner != target)
            enqueue_args = [
                sys.executable, "-m", "superharness.commands.inbox_enqueue",
                "--project", str(self.project_dir),
                "--to", target,
                "--task", task_id,
                "--plan-only",
            ]
            if force_reassign:
                enqueue_args.append("--force-reassign")
            enqueue_result = self._run_cmd(enqueue_args, timeout=30)
            if enqueue_result.get("exit_code") != 0:
                return (
                    {
                        "error": "enqueue failed",
                        "stdout": enqueue_result.get("stdout", ""),
                        "stderr": enqueue_result.get("stderr", ""),
                        "cmd": enqueue_result.get("cmd", ""),
                    },
                    500,
                )
            return (
                {
                    "ok": True,
                    "task": task_id,
                    "target": target,
                    "mode": "plan-only",
                    "stdout": enqueue_result.get("stdout", "").strip(),
                },
                200,
            )

        if action.startswith("request_review:"):
            parts = action.split(":", 2)
            task_id = parts[1] if len(parts) > 1 else ""
            reviewer = parts[2] if len(parts) > 2 else ""
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            task = _contract_task(harness_dir, task_id)
            if not task:
                return ({"error": f"task {task_id} not found"}, 404)
            if str(task.get("status", "")) != "report_ready":
                return ({"error": f"task {task_id} is {task.get('status')!r}, expected 'report_ready'"}, 400)

            items = inbox_items(harness_dir / "inbox.yaml")
            active_statuses = INBOX_ACTIVE_STATUSES
            for item in items:
                if item.get("task") == task_id and item.get("status") in active_statuses:
                    return ({"error": f"task '{task_id}' already enqueued (item {item.get('id')}, status={item.get('status')})"}, 409)

            target = reviewer if reviewer in ("claude-code", "codex-cli") else _review_target_for_owner(str(task.get("owner", "")))
            enqueue_result = self._run_cmd(
                [
                    sys.executable,
                    "-m",
                    "superharness.commands.inbox_enqueue",
                    "--project",
                    str(self.project_dir),
                    "--to",
                    target,
                    "--task",
                    task_id,
                    "--priority",
                    "1",
                ]
            )
            if enqueue_result.get("exit_code") != 0:
                return enqueue_result, 200

            status_result = _set_task_status(harness_dir, task_id, "review_requested", from_status="report_ready")
            if not status_result.get("ok"):
                return status_result, 500

            return (
                {
                    "exit_code": 0,
                    "stdout": f"Requested review for '{task_id}' via {target}.\n{enqueue_result.get('stdout', '').strip()}".strip(),
                    "stderr": enqueue_result.get("stderr", ""),
                    "cmd": enqueue_result.get("cmd", ""),
                    "status": "review_requested",
                    "review_target": target,
                },
                200,
            )

        if action.startswith("cancel_discussion:"):
            disc_id = action.split(":", 1)[1]
            if not disc_id:
                return ({"error": "missing discussion id"}, 400)
            disc_dir = self.project_dir / ".superharness" / "discussions" / disc_id
            if not disc_dir.exists():
                return ({"error": f"discussion {disc_id} not found"}, 404)
            result = self._run_cmd([
                sys.executable, "-m", "superharness.engine.discussion", "close",
                "--discussion-dir", str(disc_dir),
                "--outcome", "cancelled",
            ])
            # Sync contract task: mark any in_progress task linked to this discussion archived.
            # The contract task ID is either stored in state.yaml task_id or matches the
            # discussion ID pattern (<disc_id>/round-N).
            try:
                # Read task_id from SQLite (source of truth)
                _task_id = ""
                try:
                    from superharness.engine.db import get_connection as _gc_cdisc, init_db as _idb_cdisc
                    from superharness.engine import discussions_dao as _ddao_cdisc
                    _cconn = _gc_cdisc(str(self.project_dir))
                    try:
                        _idb_cdisc(_cconn)
                        _disc_row = _ddao_cdisc.get(_cconn, disc_id)
                        if _disc_row and _disc_row.task_id:
                            _task_id = _disc_row.task_id
                    finally:
                        _cconn.close()
                except Exception:
                    pass

                # Use SQLite to find and update in_progress tasks linked to this discussion
                from superharness.engine.db import get_connection, init_db
                from superharness.engine import tasks_dao
                _conn = get_connection(str(self.project_dir))
                try:
                    init_db(_conn)
                    all_tasks = tasks_dao.get_all(_conn)
                    for _t in all_tasks:
                        _tid = str(_t.id)
                        if _t.status == "in_progress" and (
                            _tid == _task_id
                            or _tid.startswith(disc_id + "/")
                            or (_task_id and _tid.startswith(_task_id + "/"))
                        ):
                            tasks_dao.update(_conn, _tid, version=_t.version, changes={"status": "archived"})
                    _conn.commit()
                finally:
                    _conn.close()
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
            return (result, 200 if result.get("ok") or result.get("exit_code") == 0 else 500)

        if action.startswith("close_discussion:"):
            disc_id = action.split(":", 1)[1]
            if not disc_id:
                return ({"error": "missing discussion id"}, 400)
            disc_dir = self.project_dir / ".superharness" / "discussions" / disc_id
            if not disc_dir.exists():
                return ({"error": f"discussion {disc_id} not found"}, 404)
            result = self._run_cmd([
                sys.executable, "-m", "superharness.engine.discussion", "close",
                "--discussion-dir", str(disc_dir),
                "--outcome", "consensus",
            ])
            # Sync SQLite (source of truth) — YAML export skips read-then-write
            try:
                import sqlite3 as _sq
                from superharness.utils.paths import resolve_active_state_db_path as _rap
                _db = _rap(str(self.project_dir))
                if os.path.isfile(_db):
                    _con = _sq.connect(_db)
                    _con.execute("UPDATE discussions SET status=? WHERE id=?", ("consensus", disc_id))
                    _con.commit()
                    _con.close()
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
            result["ok"] = True
            result["stdout"] = result.get("stdout") or f"Discussion {disc_id} closed with consensus."
            return (result, 200)

        if action.startswith("reopen_discussion:"):
            disc_id = action.split(":", 1)[1]
            if not disc_id:
                return ({"error": "missing discussion id"}, 400)
            disc_dir = self.project_dir / ".superharness" / "discussions" / disc_id
            if not disc_dir.exists():
                return ({"error": f"discussion {disc_id} not found"}, 404)
            # Sync SQLite (source of truth) — YAML export skips read-then-write
            try:
                import sqlite3 as _sq
                from superharness.utils.paths import resolve_active_state_db_path as _rap
                _db = _rap(str(self.project_dir))
                if os.path.isfile(_db):
                    _con = _sq.connect(_db)
                    _con.execute("UPDATE discussions SET status=?, closed_at=NULL WHERE id=?", ("active", disc_id))
                    _con.commit()
                    _con.close()
            except Exception as exc:
                return ({"error": str(exc)}, 500)
            return ({"ok": True, "stdout": f"Discussion {disc_id} reopened."}, 200)

        if action.startswith("submit_discussion_verdict:"):
            disc_id = action.split(":", 1)[1]
            if not disc_id:
                return ({"error": "missing discussion id"}, 400)
            p = payload or {}
            agent    = str(p.get("agent", "")).strip()
            verdict  = str(p.get("verdict", "consensus")).strip()
            position = str(p.get("position", "")).strip()
            round_num = str(p.get("round", "1"))
            if not agent:
                return ({"error": "agent is required"}, 400)
            if not position:
                return ({"error": "position is required"}, 400)
            if verdict not in ("consensus", "disagree", "abstain"):
                return ({"error": f"invalid verdict: {verdict!r}"}, 400)
            disc_dir = self.project_dir / ".superharness" / "discussions" / disc_id
            if not disc_dir.exists():
                return ({"error": f"discussion {disc_id} not found"}, 404)
            result = self._run_cmd([
                sys.executable, "-m", "superharness.commands.discuss",
                "submit",
                "--discussion", disc_id,
                "--agent", agent,
                "--round", str(round_num),
                "--verdict", verdict,
                "--position", position,
                "--project", str(self.project_dir),
            ])
            if result.get("exit_code", 1) != 0:
                return ({"error": result.get("stderr") or result.get("stdout") or "submit failed"}, 500)
            result["ok"] = True

            # Auto-close if all participants submitted with consensus
            try:
                from superharness.engine import discussions_dao as _ddao
                _ac = self._db_conn()
                try:
                    _drow = _ddao.get(_ac, disc_id)
                    _rounds = _ddao.get_rounds(_ac, disc_id)
                finally:
                    _ac.close()
                if _drow and _drow.status == "active":
                    _participants = _drow.owners or []
                    _submitted_agents = {r.agent for r in _rounds}
                    _all_submitted = _participants and all(p in _submitted_agents for p in _participants)
                    _all_consensus = _all_submitted and all(r.verdict == "consensus" for r in _rounds)
                    if _all_consensus:
                        self._run_cmd([
                            sys.executable, "-m", "superharness.commands.discuss",
                            "close", "--id", disc_id,
                            "--outcome", "consensus",
                            "--project", str(self.project_dir),
                        ])
                        result["auto_closed"] = True
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
            return (result, 200)

        if action.startswith("cancel_review:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            # Revert task status from review_requested back to report_ready
            result = _set_task_status(harness_dir, task_id, "report_ready", from_status="review_requested")
            if not result.get("ok"):
                return result, 500
            # Remove any pending/paused inbox items for this review
            items = inbox_items(harness_dir / "inbox.yaml")
            for item in items:
                if item.get("task") == task_id and item.get("status") in ("pending", "paused", "launched"):
                    self._run_cmd(
                        [sys.executable, "-m", "superharness.engine.inbox", "remove",
                         "--file", str(harness_dir / "inbox.yaml"), "--id", item.get("id", "")]
                    )
            return ({"ok": True, "stdout": f"Review cancelled for '{task_id}'. Status reverted to report_ready.", "status": "report_ready"}, 200)

        if action.startswith("approve_without_review:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            # Remove any pending/paused inbox items for this review
            items = inbox_items(harness_dir / "inbox.yaml")
            for item in items:
                if item.get("task") == task_id and item.get("status") in ("pending", "paused", "launched"):
                    self._run_cmd(
                        [sys.executable, "-m", "superharness.engine.inbox", "remove",
                         "--file", str(harness_dir / "inbox.yaml"), "--id", item.get("id", "")]
                    )
            # Revert to report_ready first (close command rejects review_requested)
            revert = _set_task_status(harness_dir, task_id, "report_ready", from_status="review_requested")
            if not revert.get("ok"):
                return revert, 500
            # Now close the task (skip-verify: operator is explicitly approving)
            return self._run_cmd(
                [
                    sys.executable, "-m", "superharness.commands.close",
                    "--project", str(self.project_dir),
                    "--id", task_id,
                    "--actor", "owner",
                    "--summary", "Approved by operator without agent review",
                    "--skip-verify",
                ]
            ), 200

        if action.startswith("approve_report:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [
                    sys.executable,
                    "-m",
                    "superharness.commands.close",
                    "--project",
                    str(self.project_dir),
                    "--id",
                    task_id,
                    "--actor",
                    "owner",
                    "--summary",
                    "Closed from dashboard without review request",
                    "--skip-verify",
                ]
            ), 200

        if action.startswith("mark_done:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "done", from_status="todo")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("enqueue_task:"):
            parts = action.split(":", 2)
            if len(parts) < 3 or not parts[1] or not parts[2]:
                return ({"error": "Missing task ID or target agent."}, 400)
            task_id, target = parts[1], parts[2]
            if target not in KNOWN_AGENTS:
                return ({"error": f"invalid target: {target} — must be one of {KNOWN_AGENTS}"}, 400)
            # Block duplicate: reject if task already has an active/paused inbox item
            active_statuses = INBOX_ACTIVE_STATUSES
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            for item in items:
                if item.get("task") == task_id and item.get("status") in active_statuses:
                    return ({"error": f"task '{task_id}' already enqueued (item {item.get('id')}, status={item.get('status')})"}, 409)
            # Save instructions file if provided
            instructions = (payload or {}).get("instructions", "").strip()
            if instructions:
                instructions_file = self.project_dir / ".superharness" / "handoffs" / f"{task_id}-instructions.md"
                instructions_file.parent.mkdir(parents=True, exist_ok=True)
                instructions_file.write_text(instructions, encoding="utf-8")
            # Detect implementation+todo: agent must propose a plan first.
            tasks = contract_tasks(self.project_dir / ".superharness" / "contract.yaml")
            task_meta = next((t for t in tasks if t.get("id") == task_id), {})
            from superharness.engine.next_action import infer_workflow as _infer_wf
            _workflow = _infer_wf(task_id, task_meta)
            _plan_only = _workflow == "implementation" and task_meta.get("status") == "todo"
            cmd = [sys.executable, "-m", "superharness.commands.inbox_enqueue",
                   "--project", str(self.project_dir),
                   "--to", target, "--task", task_id, "--priority", "2"]
            if _plan_only:
                cmd.append("--plan-only")
            return self._run_cmd(cmd), 200

        if action.startswith("close_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [sys.executable, "-m", "superharness.commands.close",
                 "--project", str(self.project_dir), "--id", task_id,
                 "--actor", "owner"]
            ), 200

        if action.startswith("approve_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [
                    "bash",
                    discuss,
                    "approve",
                    "--project",
                    str(self.project_dir),
                    "--task",
                    task_id,
                    "--by",
                    "owner",
                    "--note",
                    "Approved from dashboard",
                ]
            ), 200

        inbox_py = [sys.executable, "-m", "superharness.engine.inbox"]
        inbox_file = str(self.project_dir / ".superharness" / "inbox.yaml")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if action.startswith("pause_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", "pending", "--to", "paused", "--now", now, "--stamp-key", "paused_at"]), 200
        if action.startswith("resume_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", "paused", "--to", "pending", "--now", now, "--stamp-key", "resumed_at"]), 200
        if action.startswith("resume_task:"):
            task_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("task") == task_id and i.get("status") == "paused"), None)
            if not target:
                return ({"error": f"no paused inbox item found for task: {task_id}"}, 404)
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", target["id"], "--from", "paused", "--to", "pending", "--now", now, "--stamp-key", "resumed_at"]), 200
        if action.startswith("retry_task:"):
            task_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("task") == task_id and i.get("status") in ("stale", "failed", "stopped")), None)
            if not target:
                return ({"error": f"no failed/stale inbox item found for task: {task_id}"}, 404)
            from_status = target.get("status", "failed")
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", target["id"], "--from", from_status, "--to", "pending", "--now", now, "--stamp-key", "retried_at"]), 200
        if action.startswith("retry_item:"):
            item_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("id") == item_id), None)
            if not target:
                return ({"error": f"item not found: {item_id}"}, 404)
            from_status = target.get("status", "")
            if from_status not in ("stale", "failed", "stopped"):
                return ({"error": f"cannot retry from status: {from_status}"}, 400)
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", from_status, "--to", "pending", "--now", now, "--stamp-key", "retried_at"]), 200
        if action.startswith("stop_item:"):
            item_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("id") == item_id), None)
            if not target:
                return ({"error": f"item not found: {item_id}"}, 404)
            pid_str = target.get("pid", "")
            if pid_str:
                try:
                    os.kill(int(pid_str), 15)
                except (ProcessLookupError, ValueError, PermissionError):
                    pass
            from_status = target.get("status", "launched")
            result = self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", from_status, "--to", "stopped", "--now", now, "--stamp-key", "stopped_at"])
            return result, 200
        if action.startswith("remove_item:"):
            item_id = action.split(":", 1)[1]
            result = self._run_cmd(inbox_py + ["remove", "--file", inbox_file, "--id", item_id])
            # Also purge from SQLite — items written by dual-mode may exist only in DB
            try:
                from superharness.engine.db import get_connection, init_db
                from superharness.engine import inbox_dao
                _conn = get_connection(str(self.project_dir))
                init_db(_conn)
                inbox_dao.remove(_conn, item_id)
                _conn.commit()
                _conn.close()
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
            return result, 200

        return ({"error": f"unsupported action: {action}"}, 400)

    def do_GET(self) -> None:  # noqa: N802
        Handler.last_ping = time.time()

        # Refuse a rebound Host before serving anything at all — including the
        # unauthenticated `/`, which injects the auth token into the page. A
        # DNS-rebound page that can fetch `/` can read that token and replay it
        # against every other route, so the cheapest place to break the chain
        # is the front door rather than each route behind it.
        if not self._host_is_allowed():
            self._json({"error": "forbidden"}, 403)
            return

        parsed = urlparse(self.path)
        p = parsed.path
        if p in {"/", "/index.html"}:
            self._html(HTML)
            return

        # Every /api/* GET is read-only but still discloses task reports,
        # logs, handoffs, and discussion content — gate all of them here,
        # once, so a future route can't be added ungated by accident.
        if p.startswith("/api/"):
            auth_error = self._verify_read_auth()
            if auth_error:
                self._json(*auth_error)
                return

        if p == "/api/ping":
            self._json({"status": "ok", "idle_seconds": int(time.time() - Handler.last_ping)})
            return

        if p.startswith("/.superharness/handoffs/") and p.endswith(".md"):
            report_path = (self.project_dir / p.lstrip("/")).resolve()
            handoff_root = (self.project_dir / ".superharness" / "handoffs").resolve()
            if not report_path.is_relative_to(handoff_root):
                self._json({"error": "forbidden"}, 403)
                return
            if not report_path.exists():
                self._json({"error": "not found"}, 404)
                return
            body = report_path.read_bytes()
            self.send_response(200)
            self._set_common_headers("text/markdown; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        if p.startswith("/api/observation/"):
            raw_id = p[len("/api/observation/"):]
            from superharness.commands.observation import route_observation
            conn = self._db_conn()
            try:
                payload, status = route_observation(conn, raw_id)
            finally:
                conn.close()
            self._json(payload, status)
            return

        # Citation sibling routes for handoff, decision, failure.
        # Each takes an integer id and returns the row as JSON.
        for _prefix, _kind in (
            ("/api/handoff/", "handoff"),
            ("/api/decision/", "decision"),
            ("/api/failure/", "failure"),
        ):
            if p.startswith(_prefix):
                raw_id = p[len(_prefix):]
                from superharness.commands.citation import route_citation
                conn = self._db_conn()
                try:
                    payload, status = route_citation(conn, _kind, raw_id)
                finally:
                    conn.close()
                self._json(payload, status)
                return

        # Per-task observation list: /api/task/<task_id>/observations
        if p.startswith("/api/task/") and p.endswith("/observations"):
            task_id = p[len("/api/task/"):-len("/observations")]
            from superharness.commands.citation import route_task_observations
            conn = self._db_conn()
            try:
                payload, status = route_task_observations(conn, task_id)
            finally:
                conn.close()
            self._json(payload, status)
            return

        # ── Per-agent heartbeat status endpoint ───────────────────────
        if p == "/api/heartbeats":
            now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            now_ts = time.time()
            _KNOWN_AGENTS = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
            agents: dict = {a: {"level": "gray", "age_seconds": -1, "status": None,
                                "task_id": None, "updated_at": None}
                            for a in _KNOWN_AGENTS}
            try:
                from superharness.engine import heartbeat_dao as _hb_dao
                conn = self._db_conn()
                try:
                    rows = _hb_dao.get_all(conn)
                finally:
                    conn.close()
                for row in rows:
                    try:
                        import calendar as _cal
                        import time as _time
                        updated = _cal.timegm(_time.strptime(row.updated_at, "%Y-%m-%dT%H:%M:%SZ"))
                        age = int(now_ts - updated)
                    except Exception:
                        age = -1
                    if row.status == "zombie":
                        level = "red"
                    elif age < 0:
                        level = "gray"
                    elif age < 60:
                        level = "green"
                    elif age < 300:
                        level = "yellow"
                    else:
                        level = "red"
                    agents[row.agent] = {
                        "level": level,
                        "age_seconds": age,
                        "status": row.status,
                        "task_id": row.task_id,
                        "updated_at": row.updated_at,
                    }
            except Exception:
                pass
            self._json({"agents": agents, "now_utc": now_utc})
            return

        # ── Behavioral profile endpoint (Iteration 7) ──────────────────
        if p == "/api/profile":
            self._json(_profile_data(self.project_dir))
            return

        if p == "/api/status":
            now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            runtime = watcher_runtime(self.label)
            heartbeat = heartbeat_health(self.project_dir)
            wcfg = watcher_config(self.project_dir)
            sanity = version_sanity(self.project_dir)
            
            # Get optimized snapshot from SQLite
            conn = self._db_conn()
            try:
                snapshot = dashboard_presenter.get_dashboard_status_snapshot(conn, str(self.project_dir))
            finally:
                conn.close()

            # Merge SQLite snapshot with runtime/file-based signals
            result = {
                "version": __version__,
                "project": str(self.project_dir),
                "label": self.label,
                "launchctl_state": str(runtime.get("state", "")) or ("loaded" if runtime.get("loaded") else ("foreground" if heartbeat.get("level") == "ok" else "")),
                "watcher_health": watcher_health(runtime, snapshot["inbox_items"], now_utc, heartbeat=heartbeat),
                "heartbeat": heartbeat,
                "agent_status": _agent_status_health(self.project_dir),
                "watcher_runtime": runtime,
                "watcher_project": str(wcfg.get("watcher_project", str(self.project_dir))),
                "watcher_config": wcfg,
                "version_sanity": sanity,
                "budget": budget_signals(self.project_dir),
                "git_context": git_context(self.project_dir),
                "now_utc": now_utc,
                "refresh_seconds": self.refresh_seconds,
            }
            # Add all snapshot fields (contract_tasks, board_columns, activity_feed, etc.)
            result.update(snapshot)



            # Parity panel removed — YAML/SQLite parity is no longer tracked.
            result["parity"] = {"healthy": True, "yaml_sync_lag": 0, "drift": []}

            import os as _os
            result["state_backend"] = _os.environ.get("STATE_BACKEND", "dual")

            self._json(result)
            return

        if p == "/api/inbox":
            qs = parse_qs(parsed.query)
            status_filter = qs.get("status", [""])[0]
            owner_filter = qs.get("owner", [])
            conn = self._db_conn()
            try:
                from superharness.engine import inbox_dao
                items = [asdict(i) for i in inbox_dao.get_all(conn, status=status_filter or None if status_filter != "active" else None)]
                if status_filter == "active":
                    _ACTIVE = {"pending", "launched", "running"}
                    items = [i for i in items if i.get("status") in _ACTIVE]
                if owner_filter:
                    items = [i for i in items if i.get("target_agent") in owner_filter]
            finally:
                conn.close()
            self._json({"items": items, "status": status_filter, "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return

        if p == "/api/adapter-preview":
            # Adapter-payload preview: render todo nodes from the live project
            project_name = self.project_dir.name
            todo_tasks = []

            conn = self._db_conn()
            try:
                from superharness.engine import tasks_dao
                tasks = tasks_dao.get_all(conn, status="todo")
                for task in tasks:
                    todo_tasks.append({
                        "id": task.id,
                        "title": task.title,
                        "owner": task.owner or "",
                        "effort": task.effort or "medium",
                        "blocked_by": task.blocked_by,
                    })
            except Exception as e:
                self._json({"error": str(e), "project": project_name, "tasks": []}, 500)
                return
            finally:
                conn.close()

            self._json({
                "project": project_name,
                "project_path": str(self.project_dir),
                "tasks": todo_tasks,
                "count": len(todo_tasks),
            })
            return

        if p == "/api/task-log":
            qs = parse_qs(parsed.query)
            task_id = qs.get("task", [""])[0]
            agent = qs.get("agent", [""])[0]
            lines = _safe_int(qs.get("lines", ["200"])[0], 200)
            if not task_id:
                self._json({"error": "task parameter required"}, 400)
                return
            try:
                result = task_log_content(self.project_dir, task_id, agent, lines)
                # Add lines field for compatibility
                result["lines"] = lines
                self._json(result)
            except Exception as exc:
                self._json({"error": f"task_log_content failed: {exc}", "task": task_id, "agent": agent}, 500)
            return

        if p == "/api/task-instructions":
            qs = parse_qs(parsed.query)
            task_id = qs.get("task", [""])[0]
            if not task_id:
                self._json({"error": "task parameter required"}, 400)
                return
            try:
                text = task_instructions(self.project_dir, task_id)
                # Include task metadata for dispatch preview (SQLite, then contract.yaml fallback)
                task_meta = {}
                conn = self._db_conn()
                try:
                    data = dashboard_presenter.get_task_instructions_data(conn, task_id, str(self.project_dir))
                    if data:
                        task_meta = data
                finally:
                    conn.close()
                if not task_meta:
                    for t in contract_tasks(self.project_dir / ".superharness" / "contract.yaml"):
                        if t.get("id") == task_id:
                            task_meta = t
                            break
                self._json({"task": task_id, "instructions": text, "task_meta": task_meta})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        if p == "/api/watcher-errors":
            lines = _safe_int(parse_qs(parsed.query).get("lines", ["30"])[0], 30)
            errors_path = self.project_dir / ".superharness" / "watcher-errors.log"
            content = ""
            if errors_path.exists():
                try:
                    all_lines = errors_path.read_text(errors="replace").splitlines()
                    content = "\n".join(all_lines[-lines:])
                except Exception as e:
                    logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                    pass
            self._json({"errors": content, "lines": lines, "path": str(errors_path)})
            return

        if p == "/api/logs":
            # One-shot read of central superharness log (tail -n).
            from superharness.logging_utils import _resolve_log_file
            qs = parse_qs(parsed.query)
            audit = qs.get("audit", ["0"])[0] in ("1", "true")
            n = _safe_int(qs.get("n", ["200"])[0], 200)
            level = qs.get("level", [""])[0].upper()
            log_path = _resolve_log_file(
                "SUPERHARNESS_AUDIT_LOG_FILE" if audit else "SUPERHARNESS_LOG_FILE",
                "superharness-audit.log" if audit else "superharness.log",
            )
            content = ""
            if log_path.is_file():
                try:
                    all_lines = log_path.read_text(errors="replace").splitlines()
                    if level:
                        rank = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
                        min_rank = rank.get(level, -1)
                        all_lines = [
                            ln for ln in all_lines
                            if any(f" {lv} " in ln and rank[lv] >= min_rank for lv in rank)
                        ] if min_rank >= 0 else all_lines
                    content = "\n".join(all_lines[-n:])
                except Exception as e:
                    content = f"(error reading log: {e})"
            self._json({"lines": content, "path": str(log_path), "audit": audit, "level": level})
            return

        if p == "/api/discussions":
            qs = parse_qs(parsed.query)
            status_filter = qs.get("status", [""])[0] or None
            conn = self._db_conn()
            try:
                from superharness.engine import discussions_dao as _ddao_list
                from dataclasses import asdict as _asdict
                rows = _ddao_list.get_all(conn, status=status_filter)
                discs = []
                for r in rows:
                    d = _asdict(r)
                    # current_round = highest round number submitted
                    rounds = conn.execute(
                        "SELECT MAX(round_number) as mx FROM discussion_rounds WHERE discussion_id=?",
                        (r.id,),
                    ).fetchone()
                    d["current_round"] = int(rounds["mx"]) if rounds and rounds["mx"] else 0
                    discs.append(d)
            finally:
                conn.close()
            self._json({"discussions": discs, "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return

        if p.startswith("/api/discussion/") and p.endswith("/rounds"):
            disc_id = p[len("/api/discussion/"):-len("/rounds")]
            conn = self._db_conn()
            try:
                from superharness.engine import discussions_dao as _ddao_rounds
                from dataclasses import asdict as _asdict2
                rounds = _ddao_rounds.get_rounds(conn, disc_id)
                disc = _ddao_rounds.get(conn, disc_id)
            finally:
                conn.close()
            self._json({
                "discussion_id": disc_id,
                "topic": disc.topic if disc else "",
                "status": disc.status if disc else "",
                "max_rounds": disc.max_rounds if disc else 3,
                "consensus": disc.consensus if disc else None,
                "rounds": [_asdict2(r) for r in rounds],
            })
            return

        if p == "/api/logs/stream":
            # Server-Sent Events: stream new log lines as they arrive.
            from superharness.logging_utils import _resolve_log_file
            qs = parse_qs(parsed.query)
            audit = qs.get("audit", ["0"])[0] in ("1", "true")
            log_path = _resolve_log_file(
                "SUPERHARNESS_AUDIT_LOG_FILE" if audit else "SUPERHARNESS_LOG_FILE",
                "superharness-audit.log" if audit else "superharness.log",
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                if not log_path.is_file():
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.touch()
                with log_path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        if not line:
                            try:
                                self.wfile.write(b": ping\n\n")
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                return
                            time.sleep(1.0)
                            continue
                        # Escape newlines in payload per SSE spec
                        payload = line.rstrip("\n").replace("\r", "")
                        try:
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            return
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                return
            return

        if p == "/api/discussion-status":
            from urllib.parse import parse_qs as _pqs
            qs = _pqs(parsed.query)
            disc_id = qs.get("id", [""])[0]
            if not disc_id:
                self._json({"error": "id required"}, 400)
                return
            result = discussion_agent_status(self.project_dir, disc_id)
            self._json(result)
            return

        if p == "/api/task-report":
            qs = parse_qs(parsed.query)
            task_id = qs.get("task", [""])[0]
            agent = qs.get("agent", [""])[0]
            if not task_id:
                self._json({"error": "task parameter required"}, 400)
                return
            try:
                self._json(task_report(self.project_dir, task_id, agent))
            except Exception as exc:
                self._json({"error": f"task_report failed: {exc}", "task": task_id, "agent": agent}, 500)
            return

        if p == "/api/discussion":
            qs = parse_qs(parsed.query)
            disc_id = qs.get("id", [""])[0]
            if not disc_id:
                self._json({"error": "id parameter required"}, 400)
                return
            try:
                from superharness.engine import discussions_dao as _disc_dao
                _dconn = self._db_conn()
                try:
                    _drow = _disc_dao.get(_dconn, disc_id)
                    _drounds = _disc_dao.get_rounds(_dconn, disc_id) if _drow else []
                finally:
                    _dconn.close()
                if not _drow:
                    self._json({"error": f"discussion {disc_id} not found"}, 404)
                    return
                _submitted = len(_drounds)
                result: dict = {
                    "id": disc_id,
                    "topic": _drow.topic or "",
                    "status": _drow.status or "",
                    "current_round": _submitted + 1,
                    "max_rounds": 3,
                    "participants": _drow.owners or [],
                    "created_at": _drow.created_at or "",
                    "rounds": [
                        {
                            "round": r.round_number,
                            "agent": r.agent,
                            "verdict": r.verdict or "",
                            "position": r.content or "",
                            "submitted_at": r.created_at or "",
                            "points": [],
                        }
                        for r in _drounds
                    ],
                }
                # SQLite is source of truth — no YAML fallback needed
                self._json(result)
            except Exception as exc:
                self._json({"error": f"discussion fetch failed: {exc}"}, 500)
            return

        if p == "/api/skill-insights":
            try:
                from superharness.engine.skill_metrics import get_skill_insights
                insights = get_skill_insights(str(self.project_dir))
                self._json({"skills": insights})
            except Exception as e:
                self._json({"skills": [], "error": str(e)})
            return

        if p == "/api/board":
            _contract_file = self.project_dir / ".superharness" / "contract.yaml"
            _board = board_tasks(_contract_file)
            _rq = review_queue(_contract_file)
            agent_health = _agent_status_health(self.project_dir)
            self._json({
                # New fields
                "board": _board,
                "review_queue": _rq,
                "agent_health": agent_health,
                "budget": budget_signals(self.project_dir),
                # Legacy fields
                "columns": _board,
                "totals": {k: len(v) for k, v in _board.items()},
                "agent_status": agent_health,
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        if p == "/api/review-queue":
            _contract_file = self.project_dir / ".superharness" / "contract.yaml"
            self._json({
                "queue": review_queue(_contract_file),
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        if p == "/api/recent-failures":
            # iter 8: dashboard error surface. Returns latest failed inbox items
            # with structured failure_class, failure_explain, and last 20 lines
            # of launcher log inline so operators don't need to tail logs.
            from urllib.parse import parse_qs as _pq
            qs = _pq(parsed.query)
            limit = int((qs.get("limit", ["10"])[0] or "10"))
            harness = self.project_dir / ".superharness"
            launcher_logs = harness / "launcher-logs"
            failures = []
            try:
                # Read failed items from SQLite inbox table
                from superharness.engine.db import get_connection, init_db
                from superharness.engine import inbox_dao
                conn = get_connection(str(self.project_dir))
                try:
                    init_db(conn)
                    failed_rows = inbox_dao.get_all(conn, status="failed")
                    failed = [{
                        "id": r.id,
                        "task": r.task_id,
                        "to": r.target_agent,
                        "status": r.status,
                        "retry_count": r.retry_count,
                        "failed_reason": r.failed_reason or "",
                        "failed_at": r.failed_at or "",
                        "pid": r.pid,
                    } for r in failed_rows]
                    failed.sort(key=lambda i: i.get("failed_at", ""), reverse=True)
                finally:
                    conn.close()
                for item in failed[:limit]:
                    log_tail = ""
                    task_id = str(item.get("task") or item.get("task_id") or "")
                    target = str(item.get("to") or item.get("target_agent") or "")
                    if task_id and launcher_logs.is_dir():
                        # Find the most recent log for this task+target
                        safe_task = task_id.replace("/", "-")
                        candidates = sorted(
                            launcher_logs.glob(f"{safe_task}-{target}-*.log"),
                            key=lambda p: p.stat().st_mtime, reverse=True,
                        )
                        if candidates:
                            try:
                                lines = candidates[0].read_text(encoding="utf-8", errors="replace").splitlines()
                                log_tail = "\n".join(lines[-20:])
                            except Exception as e:
                                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                                pass
                    failures.append({
                        "id": str(item.get("id", "")),
                        "task": task_id,
                        "to": target,
                        "failed_at": str(item.get("failed_at") or ""),
                        "failure_class": str(item.get("failure_class") or "unknown"),
                        "failure_explain": str(item.get("failure_explain") or item.get("failed_reason") or ""),
                        "retry_count": int(item.get("retry_count", 0) or 0),
                        "max_retries": int(item.get("max_retries", 3) or 3),
                        "log_tail": log_tail,
                    })
            except Exception as e:
                self._json({"error": str(e), "failures": []}, 500)
                return
            self._json({"failures": failures, "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return

        if p == "/api/costs":
            try:
                from superharness.engine.benchmark import load_records, aggregate
            except ImportError:
                self._json({"error": "benchmark module not available"}, 500)
                return
            qs = parse_qs(parsed.query)
            top_n = _safe_int(qs.get("top", ["20"])[0], 20)
            records = load_records(self.project_dir)
            stats = aggregate(records)[:top_n]
            total_cost = sum(r.get("cost_usd", 0.0) for r in records)
            total_tokens = sum(r.get("tokens", 0) for r in records)
            self._json({
                "leaderboard": [
                    {
                        "task_id": s.task_id,
                        "total_cost_usd": round(s.total_cost_usd, 4),
                        "total_tokens": 0,
                        "dispatch_count": s.total_runs,
                        "success_count": s.successes,
                        "avg_duration_seconds": round(s.avg_duration_seconds, 1),
                    }
                    for s in stats
                ],
                "summary": {
                    "total_records": len(records),
                    "total_cost_usd": round(total_cost, 4),
                    "total_tokens": total_tokens,
                },
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        p = parsed.path

        if p == "/api/action":
            auth_error = self._verify_mutation_auth()
            if auth_error is not None:
                data, status = auth_error
                self._json(data, status)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(body.decode("utf-8"))
                action = str(payload.get("action", ""))
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                self._json({"error": "invalid request body"}, 400)
                return

            data, status = self._action(action, payload=payload)
            self._json(data, status)
            return

        if p == "/api/owners":
            auth_error = self._verify_mutation_auth()
            if auth_error is not None:
                data, status = auth_error
                self._json(data, status)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(body.decode("utf-8"))
                action = str(payload.get("action", ""))
                owner = str(payload.get("owner", "")).strip()
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                self._json({"error": "invalid request body"}, 400)
                return

            if not owner or not all(c.isalnum() or c in "-_" for c in owner):
                self._json({"error": "invalid owner name"}, 400)
                return

            task_sh = self.scripts_dir / "task.sh"
            contract = self.project_dir / ".superharness" / "contract.yaml"

            if action == "add":
                existing = contract_owners(contract)
                if owner in existing:
                    self._json({"ok": True, "owners": existing, "note": "already exists"})
                    return
                task_id = f"agent-{owner}"
                run = subprocess.run(
                    ["bash", str(task_sh), "create",
                     "--project", str(self.project_dir),
                     "--id", task_id,
                     "--title", f"Tasks for {owner}",
                     "--owner", owner,
                     "--status", "todo"],
                    capture_output=True, text=True, check=False, timeout=10,
                )
                if run.returncode != 0:
                    self._json({"error": run.stderr.strip()}, 500)
                    return
                self._json({"ok": True, "owners": contract_owners(contract)})
                return

            if action == "remove":
                existing = contract_owners(contract)
                if owner not in existing:
                    self._json({"ok": True, "owners": existing, "note": "not found"})
                    return
                if len(existing) <= 2:
                    self._json({"error": "Cannot remove owner: at least 2 owners required"}, 400)
                    return
                # Remove all tasks owned by this owner via SQLite
                try:
                    from superharness.engine.db import get_connection, init_db
                    _conn = get_connection(str(self.project_dir))
                    try:
                        init_db(_conn)
                        _conn.execute("DELETE FROM tasks WHERE owner = ?", (owner,))
                        _conn.commit()
                    finally:
                        _conn.close()
                except Exception as e:
                    self._json({"error": str(e)}, 500)
                    return
                self._json({"ok": True, "owners": contract_owners(contract)})
                return

            self._json({"error": f"unknown owner action: {action}"}, 400)
            return


        # Health API — per-agent uptime, failure rate, latency
        if p == "/api/health":
            health = _get_health(str(self.project_dir))
            self._json(health)
            return

        # Discussion operator actions
        if p.startswith("/api/discussion/") and p.endswith("/close"):
            auth_error = self._verify_mutation_auth()
            if auth_error:
                self._json(*auth_error)
                return
            from urllib.parse import unquote as _unquote_close
            disc_id = _unquote_close(p[len("/api/discussion/"):-len("/close")])
            if not disc_id:
                self._json({"error": "missing discussion id"}, 400)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = {}
            result = subprocess.run(
                ["shux", "discuss", "close", "--project", str(self.project_dir), "--id", disc_id],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self._json({"ok": True, "discussion_id": disc_id})
            else:
                self._json({"error": result.stderr.strip() or result.stdout.strip()}, 500)
            return

        if p.startswith("/api/discussion/") and p.endswith("/create-task"):
            auth_error = self._verify_mutation_auth()
            if auth_error:
                self._json(*auth_error)
                return
            from urllib.parse import unquote as _unquote_ct
            disc_id = _unquote_ct(p[len("/api/discussion/"):-len("/create-task")])
            if not disc_id:
                self._json({"error": "missing discussion id"}, 400)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = {}
            title = str(payload.get("title", "")).strip() or f"Implement consensus from {disc_id}"
            owner = str(payload.get("owner", "claude-code")).strip()
            result = subprocess.run(
                ["shux", "task", "create",
                 "--project", str(self.project_dir),
                 "--title", title,
                 "--owner", owner,
                 "--context", f"Consensus reached in discussion {disc_id}. Implement the agreed design."],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self._json({"ok": True, "discussion_id": disc_id, "output": result.stdout.strip()})
            else:
                self._json({"error": result.stderr.strip() or result.stdout.strip()}, 500)
            return

        self._json({"error": "not found"}, 404)


def _get_installed_version() -> str:
    """Return the installed package version, or 'unknown' if unavailable."""
    try:
        import importlib.metadata
        return importlib.metadata.version("superharness")
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return "unknown"


def _append_ledger(project_dir: str, line: str) -> None:
    """Append *line* to .superharness/ledger.md, creating the file if absent."""
    ledger_path = os.path.join(project_dir, ".superharness", "ledger.md")
    try:
        with open(ledger_path, "a") as fh:
            fh.write(line)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass  # Ledger writes must never crash the watchdog


def autohealth_check(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """Ping the dashboard server. Returns True if healthy, False otherwise."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/status")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        return False


def autohealth_loop(
    project_dir: str,
    port: int = 8787,
    host: str = "127.0.0.1",
    interval: int = 5,
    max_restarts: int = 100,
) -> None:
    """Watchdog loop: check server health every `interval` seconds, restart if dead."""
    import signal
    restarts = 0
    proc: subprocess.Popen | None = None
    log_handle: object = None

    def _start() -> subprocess.Popen:
        nonlocal log_handle
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
        log_handle = open(os.path.join(project_dir, ".superharness", "dashboard-health.log"), "a")
        return subprocess.Popen(
            [sys.executable, "-u", __file__, "--project", str(project_dir),
             "--port", str(port), "--host", host, "--no-open"],
            start_new_session=True,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

    def _restart_proc(current_proc: subprocess.Popen) -> subprocess.Popen:
        """Terminate *current_proc* (if alive) and start a fresh dashboard."""
        if current_proc.poll() is None:
            current_proc.terminate()
            try:
                current_proc.wait(timeout=5)
            except Exception as e:
                logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                pass
        return _start()

    def _shutdown(signum: int, frame: object) -> None:
        if proc and proc.poll() is None:
            proc.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    proc = _start()
    running_version = _get_installed_version()
    print(f"autohealth: started dashboard pid={proc.pid} port={port} version={running_version}")

    while restarts < max_restarts:
        time.sleep(interval)

        # Version-mismatch check: restart when installed package was upgraded.
        installed_version = _get_installed_version()
        if installed_version != running_version:
            restarts += 1
            now_ts = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _append_ledger(
                project_dir,
                f"- {now_ts} — autohealth — auto-restart — version mismatch: "
                f"{running_version} -> {installed_version}\n",
            )
            proc = _restart_proc(proc)
            running_version = installed_version
            print(
                f"autohealth: restarted dashboard pid={proc.pid} "
                f"(version upgrade: {running_version}, restart #{restarts})"
            )
            continue

        if proc.poll() is not None or not autohealth_check(port, host):
            restarts += 1
            proc = _restart_proc(proc)
            print(f"autohealth: restarted dashboard pid={proc.pid} (restart #{restarts})")
    print(f"autohealth: max restarts ({max_restarts}) reached, exiting")


def main() -> int:
    _ensure_python_with_yaml()
    ap = argparse.ArgumentParser(description="superharness browser dashboard")
    ap.add_argument("--project", default=None, help="project directory containing .superharness (default: cwd)")
    ap.add_argument("--port", type=int, default=8787, help="HTTP port (default: 8787)")
    ap.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    ap.add_argument("--refresh-seconds", type=int, default=3, help="ui refresh seconds (default: 3)")
    ap.add_argument("--no-open", action="store_true", help="do not open browser automatically")
    ap.add_argument("--autohealth", action="store_true", help="run watchdog that auto-restarts dashboard if it dies")
    ap.add_argument("--health-interval", type=int, default=5, help="health check interval in seconds (default: 5)")
    ap.add_argument("--timeout", type=int, default=0, help="idle timeout in seconds (default: 0, disabled)")
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve() if args.project else Path.cwd()
    if not (project_dir / ".superharness").is_dir():
        raise SystemExit(f"Missing .superharness in project: {project_dir}")
    try:
        if not ipaddress.ip_address(args.host).is_loopback:
            raise SystemExit(f"dashboard host must be loopback-only, got: {args.host}")
    except ValueError:
        if args.host not in {"localhost"}:
            raise SystemExit(f"dashboard host must be loopback-only, got: {args.host}")

    if args.autohealth:
        autohealth_loop(
            project_dir=str(project_dir),
            port=args.port,
            host=args.host,
            interval=args.health_interval,
        )
        return 0

    scripts_dir = Path(__file__).resolve().parent

    Handler.idle_timeout = args.timeout
    Handler.last_ping = time.time()

    if Handler.idle_timeout > 0:
        def _idle_monitor():
            while True:
                idle = time.time() - Handler.last_ping
                if idle > Handler.idle_timeout:
                    print(f"dashboard-ui: idle timeout ({Handler.idle_timeout}s) exceeded — shutting down")
                    os._exit(0)
                time.sleep(5)
        threading.Thread(target=_idle_monitor, daemon=True).start()

    # Guard: prevent a second dashboard for the same project directory.
    _my_pid = os.getpid()
    try:
        import subprocess as _sp
        # Use Popen+communicate instead of run(timeout=) — on macOS CI runners ps
        # can enter an uninterruptible kernel wait that ignores SIGKILL.  subprocess.run
        # calls process.wait() after kill(), which hangs forever in that case.
        # Popen.communicate() does NOT call wait() after kill on POSIX, so we can
        # safely abandon the process and skip the guard.
        _ps_proc = _sp.Popen(
            ["ps", "ax", "-o", "pid=,args="],
            stdout=_sp.PIPE, stderr=_sp.DEVNULL, text=True,
        )
        try:
            _ps, _ = _ps_proc.communicate(timeout=10)
        except _sp.TimeoutExpired:
            _ps_proc.kill()
            _ps = ""  # guard skipped — ps timed out
        for _line in _ps.splitlines():
            _line = _line.strip()
            _is_dash = (
                "dashboard-ui.py" in _line
                or "monitor-ui.py" in _line
                or "superharness.scripts.dashboard-ui" in _line
                or "superharness.scripts.monitor-ui" in _line
            )
            if not _is_dash:
                continue
            _parts = _line.split()
            try:
                _other_pid = int(_parts[0])
            except (ValueError, IndexError):
                continue
            if _other_pid == _my_pid:
                continue
            # Extract --project from that process's cmdline
            _other_proj = None
            for _i, _p in enumerate(_parts):
                if _p == "--project" and _i + 1 < len(_parts):
                    _other_proj = str(Path(_parts[_i + 1]).expanduser().resolve())
                    break
            if _other_proj and Path(_other_proj).resolve() == project_dir.resolve():
                # Find its port via lsof
                _lsof = _sp.run(
                    ["lsof", "-a", "-i", "TCP", "-sTCP:LISTEN", "-n", "-P", "-p", str(_other_pid)],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                _existing_port = None
                for _ll in _lsof.splitlines():
                    _lp = _ll.split()
                    if len(_lp) >= 9:
                        try:
                            _existing_port = int(_lp[8].split(":")[-1])
                        except ValueError:
                            pass
                _url = f"http://127.0.0.1:{_existing_port}" if _existing_port else "(port unknown)"

                # Version check: query running dashboard and compare to installed version
                _current_version = _get_installed_version()
                _running_version = "unknown"
                if _existing_port:
                    try:
                        import urllib.request as _ur
                        with _ur.urlopen(f"http://127.0.0.1:{_existing_port}/api/status", timeout=2) as _r:
                            import json as _json
                            _running_version = _json.loads(_r.read()).get("version", "unknown")
                    except Exception as e:
                        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                        pass
                if _running_version != "unknown" and _running_version != _current_version:
                    # Log the mismatch but DON'T restart — let the user decide
                    print(f"dashboard version: running {_running_version} vs installed {_current_version} — run 'pipx upgrade superharness' to update")
                    # Don't kill the process — just continue as a warning

                # If the port is unknown, the PID is dead — kill stale entry and start fresh
                if _existing_port is None:
                    print(f"dashboard: found stale pid={_other_pid} for project '{project_dir.name}' — clearing and starting fresh")
                    try:
                        os.kill(_other_pid, 0)  # test if alive
                    except OSError:
                        # PID is dead — remove stale operator-state.json
                        _state_file = project_dir / ".superharness" / "operator-state.json"
                        try:
                            _state_file.unlink(missing_ok=True)
                        except Exception as e:
                            logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
                            pass
                    continue

                print(f"dashboard already running for project '{project_dir.name}' (pid={_other_pid}, {_url}) — version {_running_version}")
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass  # Guard failure must never block startup

    Handler.project_dir = project_dir
    Handler.label = project_label(project_dir)
    Handler.refresh_seconds = args.refresh_seconds
    Handler.scripts_dir = scripts_dir
    # Persist the auth token so browser tabs survive daemon restarts.
    # Token is regenerated only when the file is absent or unreadable.
    _token_file = project_dir / ".superharness" / ".dashboard_auth_token"
    try:
        _stored = _token_file.read_text().strip()
        Handler.auth_token = _stored if len(_stored) >= 16 else secrets.token_urlsafe(24)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        Handler.auth_token = secrets.token_urlsafe(24)
    try:
        _token_file.write_text(Handler.auth_token)
        _token_file.chmod(0o600)
    except Exception as e:
        logger.warning("dashboard-ui unexpected error: %s", e, exc_info=True)
        pass
    port = args.port
    user_specified_port = "--port" in sys.argv
    if not user_specified_port:
        for candidate in range(port, port + 20):
            try:
                server = ThreadingHTTPServer((args.host, candidate), Handler)
                if candidate != port:
                    print(f"port {port} in use, using {candidate}")
                port = candidate
                break
            except OSError as exc:
                if exc.errno in (48, 98, 10048, _errno_mod.EADDRINUSE) or "address already in use" in str(exc).lower():
                    continue
                raise
        else:
            raise SystemExit(f"No free port found in range {args.port}–{args.port + 19}")
    else:
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
        except OSError as exc:
            if exc.errno in (48, 98, 10048, _errno_mod.EADDRINUSE) or "address already in use" in str(exc).lower():
                raise SystemExit(f"Port {port} is already in use") from None
            raise
    # Pin the guards to the address actually bound, so _expected_origin and
    # _host_is_allowed compare against reality rather than the request.
    Handler.bind_host = args.host
    Handler.bind_port = port
    url = f"http://{args.host}:{port}"
    print(f"dashboard: {url}")
    print(f"project: {project_dir}")
    _installed_ver = _get_installed_version()
    print(f"version: {_installed_ver}")
    _wrt = watcher_runtime(Handler.label)
    _watcher_ok = _wrt.get("loaded") and _wrt.get("state") in ("waiting", "running")
    print(f"watcher: {'ok — auto-dispatch active' if _watcher_ok else 'NOT RUNNING — auto-dispatch inactive (run: shux watcher-install)'}")
    print(f"watcher label: {Handler.label}")
    url_file = os.environ.get("SUPERHARNESS_DASHBOARD_URL_FILE") or os.environ.get("SUPERHARNESS_MONITOR_URL_FILE")
    if url_file:
        with open(url_file, "w") as _f:
            _f.write(f"dashboard: {url}\n")
            _f.write(f"project: {project_dir}\n")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _get_health(project_dir: str) -> dict:
    """Return per-agent health stats for the dashboard."""
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            agents = []
            hb_rows = conn.execute(
                "SELECT agent, status, updated_at FROM agent_heartbeats ORDER BY agent"
            ).fetchall()
            for hb in hb_rows:
                agent = hb["agent"]
                done = conn.execute(
                    "SELECT COUNT(*) FROM inbox WHERE target_agent=? AND status='done'",
                    (agent,),
                ).fetchone()[0]
                failed = conn.execute(
                    "SELECT COUNT(*) FROM inbox WHERE target_agent=? AND status='failed'",
                    (agent,),
                ).fetchone()[0]
                total = done + failed
                accuracy = round(done / total * 100, 1) if total > 0 else 100.0
                agents.append({
                    "agent": agent, "status": hb["status"],
                    "last_seen": hb["updated_at"],
                    "tasks_done": done, "tasks_failed": failed,
                    "accuracy_pct": accuracy,
                })
            return {"agents": agents, "total_agents": len(agents)}
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    raise SystemExit(main())
