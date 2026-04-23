#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import errno as _errno_mod
import ipaddress
import json
import os
import secrets
import shlex
import shutil  # noqa: F401 — patched by tests to mock agent CLI detection
import subprocess
import sys
import time
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from superharness import __version__


def _ensure_python_with_yaml() -> None:
    """Re-exec into the repo venv if the current interpreter lacks PyYAML."""
    try:
        import yaml  # noqa: F401
        return
    except Exception:
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


HTML = (Path(__file__).parent / "dashboard.html").read_text()

# Registry of known agent names — add new agents here as the ecosystem grows.
KNOWN_AGENTS: list[str] = ["claude-code", "codex-cli", "gemini-cli"]

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
    except Exception:
        pass
    return result


def activity_feed(project_dir: Path, inbox_file: Path, ledger_file: Path, limit: int = 30) -> list[dict]:
    """Build a combined activity feed from inbox events + ledger entries, sorted by time."""
    import re as _re
    events: list[dict] = []
    cutoff_hours = 4

    now = time.time()
    cutoff = now - (cutoff_hours * 3600)

    # Inbox events
    for item in inbox_items(inbox_file):
        ts_map = {
            "created_at": "enqueued",
            "launched_at": "launched",
            "done_at": "done",
            "failed_at": "failed",
            "paused_at": "paused",
            "stale_at": "stale",
            "stopped_at": "stopped",
        }
        for ts_key, event_type in ts_map.items():
            ts = str(item.get(ts_key, "")).strip().strip("'")
            if not ts:
                continue
            try:
                dt = _datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.timestamp() < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            task = item.get("task", "?")
            to = item.get("to", "?")
            reason = item.get("pause_reason") or item.get("failed_reason") or ""
            reason_str = f" — {reason.replace('_', ' ')}" if reason else ""
            events.append({
                "time": ts,
                "type": event_type,
                "message": f"{task} → {to}{reason_str}",
            })

    # Ledger entries
    if ledger_file.exists():
        try:
            for line in ledger_file.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)", line)
                if not m:
                    continue
                ts = m.group(1)
                try:
                    dt = _datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.timestamp() < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
                # Determine type from content
                line_lower = line.lower()
                if "[gc]" in line_lower:
                    etype = "gc"
                elif "dispatch" in line_lower:
                    etype = "dispatch"
                elif "review" in line_lower:
                    etype = "review"
                else:
                    etype = "ledger"
                # Clean up the message
                msg = _re.sub(r"^-\s*\d{4}-\d{2}-\d{2}T\S+\s*—?\s*", "", line).strip()
                events.append({"time": ts, "type": etype, "message": msg})
        except OSError:
            pass

    events.sort(key=lambda e: e.get("time", ""), reverse=True)
    return events[:limit]


from datetime import datetime as _datetime


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
    except Exception:
        return info
    return info


def inbox_items(inbox_file: Path) -> list[dict]:
    if not inbox_file.exists():
        return []
    items: list[dict] = []
    current: dict = {}
    for raw in inbox_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if raw.startswith("- "):
            if current:
                items.append(current)
            current = {}
            kv = line[2:]
            if ":" in kv:
                k, _, v = kv.partition(":")
                current[k.strip()] = v.strip()
        elif ":" in line and current:
            k, _, v = line.partition(":")
            k = k.strip()
            if k and k not in current:
                current[k] = v.strip()
    if current:
        items.append(current)
    return items


def inbox_counts(inbox_file: Path) -> dict[str, int]:
    counts = Counter()
    if not inbox_file.exists():
        return {}
    for ln in inbox_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = ln.strip()
        if line.startswith("status:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                counts[parts[1].strip()] += 1
    return dict(counts)


def inbox_owner_counts(inbox_file: Path) -> dict[str, int]:
    counts = Counter()
    for item in inbox_items(inbox_file):
        owner = item.get("to", "unknown")
        counts[owner] += 1
    return dict(counts)


def task_instructions(project_dir: Path, task_id: str) -> str:
    """Build personalized TDD instructions for a task by reading plan docs and contract."""
    import re as _re

    # Get task title and criteria from contract
    contract_file = project_dir / ".superharness" / "contract.yaml"
    task_title = task_id
    criteria = []
    if contract_file.exists():
        try:
            import yaml
            doc = yaml.safe_load(contract_file.read_text()) or {}
            for t in doc.get("tasks") or []:
                if isinstance(t, dict) and t.get("id") == task_id:
                    task_title = t.get("title", task_id)
                    criteria = t.get("acceptance_criteria") or t.get("criteria") or []
                    if isinstance(criteria, str):
                        criteria = [criteria]
                    break
        except Exception:
            pass

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
        except Exception:
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

    # Check for prior failed attempts — inbox items and handoff reports
    prior_failure = ""
    inbox_file = project_dir / ".superharness" / "inbox.yaml"
    if inbox_file.exists():
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

    # 1. Contract task — full data
    contract_file = harness / "contract.yaml"
    if contract_file.exists():
        try:
            import yaml
            doc = yaml.safe_load(contract_file.read_text()) or {}
            for t in doc.get("tasks") or []:
                if isinstance(t, dict) and t.get("id") == task_id:
                    result["contract_status"]   = t.get("status", "")
                    result["contract_title"]    = t.get("title", "")
                    result["contract_owner"]    = t.get("owner", "")
                    result["contract_summary"]  = t.get("summary", "")
                    result["blocked_by"]        = _normalize_blocked_by(t.get("blocked_by", ""))
                    result["acceptance_criteria"] = t.get("acceptance_criteria") or []
                    result["test_types"]        = t.get("test_types") or []
                    result["tdd"]               = t.get("tdd") or {}
                    result["outcomes"]          = t.get("outcomes") or []
                    result["tests_passed"]      = t.get("tests_passed", None)
                    result["verified"]          = t.get("verified", None)
                    result["verified_at"]       = str(t.get("verified_at", ""))
                    result["verified_by"]       = t.get("verified_by", "")
                    # timestamps
                    for ts_key in ("todo_at", "plan_proposed_at", "plan_approved_at",
                                   "in_progress_at", "report_ready_at", "done_at", "stopped_at"):
                        if t.get(ts_key):
                            result[ts_key] = str(t[ts_key])
                    break
        except Exception:
            pass

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
        except Exception:
            pass

    # 2. Handoff YAML + markdown report
    handoff_dir = harness / "handoffs"
    if handoff_dir.exists():
        # Search both .yaml and .md files (md files use YAML frontmatter)
        handoff_files = sorted(handoff_dir.glob("*.yaml"), reverse=True) + sorted(handoff_dir.glob("*.md"), reverse=True)
        for f in handoff_files:
            try:
                content = f.read_text(errors="replace")
                # Match by task/task_id fields in content, or by filename (skip instructions files)
                is_instructions = f.name.endswith("-instructions.md")
                has_task = (f"task: {task_id}" in content or f"task: '{task_id}'" in content
                            or f"task_id: {task_id}" in content or f"task_id: '{task_id}'" in content
                            or (not is_instructions and (f.name.startswith(f"{task_id}-") or f.name.startswith(f"{task_id}."))))
                if not has_task:
                    continue
                import yaml
                # For .md files, extract YAML frontmatter between --- delimiters
                if f.suffix == ".md":
                    stripped = content.strip()
                    if stripped.startswith("---"):
                        parts = stripped.split("---", 2)
                        if len(parts) >= 3:
                            hd = yaml.safe_load(parts[1]) or {}
                            md_body = parts[2].strip()
                        else:
                            hd = {}
                            md_body = stripped
                    else:
                        # No frontmatter — use entire content as report body
                        hd = {}
                        md_body = stripped
                else:
                    hd = yaml.safe_load(content) or {}
                    md_body = ""
                if agent and hd.get("to") and hd["to"] != agent and hd.get("from") != agent:
                    continue
                result["handoff_status"] = hd.get("status", "")
                result["handoff_summary"] = hd.get("summary", "")
                result["handoff_outcome"] = hd.get("outcome", "")
                result["handoff_context"] = hd.get("context", "")
                result["handoff_date"] = str(hd.get("date", hd.get("timestamp", "")))
                md_path = hd.get("markdown_report", "")
                if md_path:
                    md_file = project_dir / md_path if not Path(md_path).is_absolute() else Path(md_path)
                    if md_file.exists():
                        result["markdown_report"] = md_file.read_text(errors="replace")[:8000]
                elif md_body:
                    result["markdown_report"] = md_body[:8000]
                break
            except Exception:
                continue

    # 3. Discussion submissions (task_id like discuss-XXX/round-N)
    if "/" in task_id:
        disc_id, round_part = task_id.rsplit("/", 1)
        disc_dir = harness / "discussions" / disc_id
        if disc_dir.exists():
            # Discussion state
            state_file = disc_dir / "state.yaml"
            if state_file.exists():
                try:
                    import yaml
                    st = yaml.safe_load(state_file.read_text()) or {}
                    result["discussion_topic"] = st.get("topic", "")
                    result["discussion_status"] = st.get("status", "")
                    result["discussion_round"] = st.get("current_round", "")
                    result["discussion_max_rounds"] = st.get("max_rounds", "")
                except Exception:
                    pass

            # Agent submission for this round
            round_num = round_part.replace("round-", "")
            sub_file = disc_dir / f"round-{round_num}-{agent}.yaml"
            if sub_file.exists():
                try:
                    import yaml
                    sub = yaml.safe_load(sub_file.read_text()) or {}
                    result["discussion_verdict"] = sub.get("verdict", "")
                    result["discussion_position"] = sub.get("position", "")
                    result["discussion_agent"] = sub.get("agent", agent)
                except Exception:
                    pass

            # If no specific agent submission, try all agents
            if "discussion_position" not in result:
                all_positions = []
                for sf in sorted(disc_dir.glob(f"round-{round_num}-*.yaml")):
                    try:
                        import yaml
                        sub = yaml.safe_load(sf.read_text()) or {}
                        a = sub.get("agent", sf.stem.split("-")[-1])
                        v = sub.get("verdict", "?")
                        p = sub.get("position", "")
                        all_positions.append(f"[{a}] verdict={v}\n{p}")
                    except Exception:
                        continue
                if all_positions:
                    result["discussion_position"] = "\n\n".join(all_positions)

            # Outcome handoff markdown
            if "markdown_report" not in result:
                for mf in sorted(handoff_dir.glob(f"*{disc_id}*outcome*.md"), reverse=True) if handoff_dir.exists() else []:
                    try:
                        result["markdown_report"] = mf.read_text(errors="replace")[:8000]
                        break
                    except Exception:
                        continue
                # Also check per-agent markdown
                if "markdown_report" not in result and agent:
                    for mf in sorted(handoff_dir.glob(f"*{disc_id}*{agent}*.md"), reverse=True) if handoff_dir.exists() else []:
                        try:
                            result["markdown_report"] = mf.read_text(errors="replace")[:8000]
                            break
                        except Exception:
                            continue

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

    if matching:
        log_file = matching[0]
        result["exists"] = True
        result["log_file"] = str(log_file.relative_to(project_dir))
        try:
            content = log_file.read_text(errors="replace")
            
            # Strip ANSI escape sequences (e.g., [1C, [m)
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            content = ansi_escape.sub('', content)

            if lines > 0:
                # Return only last N lines
                all_lines = content.splitlines()
                content = "\n".join(all_lines[-lines:])
            result["content"] = content
            result["log"] = content  # Compatibility with existing JS code
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
    except Exception:
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
    except Exception:
        return ""


def contract_owners(contract_file: Path) -> list[str]:
    """Read distinct task owners from contract.yaml."""
    if not contract_file.exists():
        return []
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text()) or {}
    except Exception:
        return []
    tasks = doc.get("tasks") or []
    owners = []
    seen = set()
    for t in tasks:
        if isinstance(t, dict):
            o = t.get("owner")
            if o and o not in seen:
                owners.append(o)
                seen.add(o)
    return owners


def parse_utc_timestamp(raw: str) -> dt.datetime | None:
    value = raw.strip().strip("'\"")
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def watcher_health(runtime: dict, items: list[dict], now_utc: str) -> dict:
    now_dt = parse_utc_timestamp(now_utc)
    state = runtime.get("state", "")
    loaded = bool(runtime.get("loaded", False))
    last_exit_code = str(runtime.get("last_exit_code", "")).strip()
    run_interval_seconds = int(runtime.get("run_interval_seconds", 0) or 0)
    pending_items = [x for x in items if x.get("status", "") == "pending"]
    pending_count = len(pending_items)
    stale_count = sum(1 for x in items if x.get("status", "") == "stale")
    failed_count = sum(1 for x in items if x.get("status", "") == "failed")

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
    except Exception:
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
    if not contract_file.exists():
        return ""
    try:
        import yaml
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
        return str(doc.get("id", "") or "")
    except Exception:
        return ""


def contract_tasks(contract_file: Path) -> list[dict]:
    """Return all contract tasks with id, title, status, owner."""
    if not contract_file.exists():
        return []
    try:
        import yaml
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
        tasks = []
        for t in doc.get("tasks") or []:
            if not isinstance(t, dict):
                continue
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
            })
        return tasks
    except Exception:
        return []


def pending_approvals(handoff_dir: Path) -> list[dict]:
    rows: list[dict] = []
    if not handoff_dir.exists():
        return rows
    for file in sorted(handoff_dir.glob("*.yaml")):
        task = ""
        status = ""
        markdown_report = ""
        required = False
        approved = False
        in_gate = False
        for raw in file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if stripped.startswith("task:"):
                task = stripped.split(":", 1)[1].strip().strip("'\"")
            elif stripped.startswith("status:"):
                status = stripped.split(":", 1)[1].strip().strip("'\"")
            elif stripped.startswith("markdown_report:"):
                markdown_report = stripped.split(":", 1)[1].strip().strip("'\"")
            elif stripped == "approval_gate:":
                in_gate = True
            elif in_gate and not line.startswith("  "):
                in_gate = False
            elif in_gate and stripped.startswith("required:"):
                required = stripped.split(":", 1)[1].strip().lower() == "true"
            elif in_gate and stripped.startswith("approved_by_user:"):
                approved = stripped.split(":", 1)[1].strip().lower() == "true"
        pending = status == "pending_user_approval" or (required and not approved)
        if pending:
            rows.append(
                {
                    "task": task,
                    "status": status,
                    "required": required,
                    "approved_by_user": approved,
                    "markdown_report": markdown_report,
                }
            )
    return rows


def plan_proposals(harness_dir: Path) -> list[dict]:
    """Return contract tasks with status=plan_proposed that await user confirmation."""
    rows: list[dict] = []
    contract_file = harness_dir / "contract.yaml"
    handoff_dir = harness_dir / "handoffs"
    if not contract_file.exists():
        return rows
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text()) or {}
    except Exception:
        return rows
    tasks = doc.get("tasks", []) or []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") != "plan_proposed":
            continue
        task_id = t.get("id", "")
        owner = t.get("owner", "")
        title = t.get("title", task_id)
        # Find matching handoff for the plan content
        summary = t.get("summary", "")
        handoff_summary = ""
        if handoff_dir.exists():
            for hf in sorted(handoff_dir.glob("*.yaml"), reverse=True):
                try:
                    raw = hf.read_text(encoding="utf-8", errors="replace")
                    hdata = yaml.safe_load(raw) or {}
                    if hdata.get("task") == task_id and hdata.get("status") == "plan_proposed":
                        handoff_summary = hdata.get("summary", "") or hdata.get("scope", "")
                        if isinstance(handoff_summary, list):
                            handoff_summary = "\n".join(str(x) for x in handoff_summary)
                        break
                except Exception:
                    continue
        rows.append({
            "task": task_id,
            "title": title,
            "from": owner,
            "summary": handoff_summary or summary or title,
        })
    return rows


def _set_task_status(harness_dir: Path, task_id: str, to_status: str, from_status: str | None = None) -> dict:
    """Set a contract task status, optionally requiring it to be in from_status first."""
    import yaml  # noqa: F811
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    contract_file = harness_dir / "contract.yaml"
    try:
        doc = yaml.safe_load(contract_file.read_text()) or {}
        found = False
        for t in doc.get("tasks") or []:
            if isinstance(t, dict) and t.get("id") == task_id:
                if from_status and t.get("status") != from_status:
                    return {"ok": False, "error": f"task {task_id} is {t.get('status')!r}, expected {from_status!r}"}
                t["status"] = to_status
                t[f"{to_status}_at"] = now
                found = True
                break
        if not found:
            return {"ok": False, "error": f"task {task_id} not found"}
        contract_file.write_text(yaml.dump(doc, default_flow_style=False, sort_keys=False))
        return {"ok": True, "task": task_id, "status": to_status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _contract_task(harness_dir: Path, task_id: str) -> dict | None:
    contract_file = harness_dir / "contract.yaml"
    if not contract_file.exists():
        return None
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text()) or {}
    except Exception:
        return None
    for task in doc.get("tasks") or []:
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
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
    """
    _STATUS_TO_COL = {
        "todo": "todo",
        "plan_proposed": "plan",
        "plan_approved": "plan",
        "plan_confirmed": "plan",
        "in_progress": "in_progress",
        "launched": "in_progress",
        "running": "in_progress",
        "report_ready": "review",
        "review_requested": "review",
        "review_passed": "review",
        "review_failed": "review",
        "done": "done",
        "stopped": "done",
        "failed": "done",
    }
    _REVIEW_QUEUE_STATUSES = {"review_requested", "review_passed", "review_failed"}
    empty: dict = {col: [] for col in ("todo", "plan", "in_progress", "review", "done")}

    if not contract_file.exists():
        return {"columns": empty, "review_queue": [], "totals": {col: 0 for col in empty}}

    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {"columns": empty, "review_queue": [], "totals": {col: 0 for col in empty}}

    columns: dict = {col: [] for col in ("todo", "plan", "in_progress", "review", "done")}
    review_queue: list = []

    for t in doc.get("tasks") or []:
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
    contract_file = harness_dir / "contract.yaml"
    handoff_dir = harness_dir / "handoffs"
    errors = []

    # Update contract task status plan_proposed -> todo
    if contract_file.exists():
        try:
            doc = yaml.safe_load(contract_file.read_text()) or {}
            tasks = doc.get("tasks", []) or []
            found = False
            for t in tasks:
                if isinstance(t, dict) and t.get("id") == task_id and t.get("status") == "plan_proposed":
                    t["status"] = "todo"
                    t["plan_confirmed_at"] = now
                    t["plan_confirmed_by"] = "owner"
                    found = True
                    break
            if found:
                contract_file.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            else:
                errors.append(f"task {task_id} not found in plan_proposed status")
        except Exception as e:
            errors.append(f"contract update error: {e}")  # shipguard:ignore PY-007

    # Update matching handoff: add plan_gate confirmation
    if handoff_dir.exists():
        for hf in sorted(handoff_dir.glob("*.yaml"), reverse=True):
            try:
                raw = hf.read_text(encoding="utf-8", errors="replace")
                hdata = yaml.safe_load(raw) or {}
                if hdata.get("task") == task_id and hdata.get("status") == "plan_proposed":
                    hdata["status"] = "plan_confirmed"
                    gate = hdata.get("plan_gate", {}) or {}
                    gate["confirmed_by_user"] = True
                    gate["confirmed_at"] = now
                    gate["confirmed_by"] = "owner"
                    hdata["plan_gate"] = gate
                    hf.write_text(yaml.dump(hdata, default_flow_style=False, allow_unicode=True))
                    break
            except Exception as e:
                errors.append(f"handoff update error: {e}")  # shipguard:ignore PY-007

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
    return cfg_map


def board_tasks(contract_file: Path) -> dict[str, list[dict]]:
    """Group contract tasks by board column (todo/plan/active/review/done/stopped)."""
    if not contract_file.exists():
        return {}
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {}

    _STATUS_TO_COL: dict[str, str] = {
        "todo": "todo",
        "plan_proposed": "plan",
        "plan_approved": "plan",
        "in_progress": "active",
        "launched": "active",
        "running": "active",
        "report_ready": "review",
        "review_requested": "review",
        "review_passed": "review",
        "review_failed": "review",
        "done": "done",
        "failed": "done",
        "stopped": "stopped",
    }

    columns: dict[str, list[dict]] = {
        "todo": [], "plan": [], "active": [], "review": [], "done": [], "stopped": []
    }

    for t in doc.get("tasks") or []:
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
    if not contract_file.exists():
        return []
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return []

    _REVIEW_STATUSES = {"report_ready", "review_requested", "review_passed", "review_failed"}
    _URGENCY = {
        "review_failed": 0,
        "report_ready": 1,
        "review_requested": 2,
        "review_passed": 3,
    }

    queue = []
    for t in doc.get("tasks") or []:
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
    except Exception:
        # Fallback: manually scan agents/*.status.yaml for budget fields
        agents_dir = project_dir / ".superharness" / "agents"
        if not agents_dir.exists():
            return {"agents": {}, "available": False}
        signals = {}
        try:
            import yaml  # noqa: F811
            for f in agents_dir.glob("*.status.yaml"):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}
                    runtime = data.get("runtime", f.stem.replace(".status", ""))
                    if "budget" in data and data["budget"]:
                        signals[runtime] = data["budget"]
                except Exception:
                    continue
        except Exception:
            pass
        return {"agents": signals, "available": bool(signals)}


def project_label(project_dir: Path) -> str:
    # Match install-launchd-inbox-watcher.sh: basename | tr -cs 'A-Za-z0-9' '-'
    import re
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project_dir.name).strip("-")
    if not slug:
        slug = "project"
    return f"com.superharness.inbox.{slug}"


class Handler(BaseHTTPRequestHandler):
    project_dir: Path
    label: str
    refresh_seconds: int
    scripts_dir: Path
    auth_token: str

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
        body = html.replace("__AUTH_TOKEN__", json.dumps(self.auth_token)).encode("utf-8")
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

    def _expected_origin(self) -> str:
        return f"http://{self.headers.get('Host', '')}"

    def _verify_mutation_auth(self) -> tuple[dict, int] | None:
        token = self.headers.get("X-Superharness-Token", "")
        if not token or token != self.auth_token:
            return ({"error": "forbidden"}, 403)

        expected_origin = self._expected_origin()
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")

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
            install_args = [
                sys.executable,
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
        if action == "normalize_stale":
            return self._run_cmd(["bash", normalize, "--project", str(self.project_dir), "--archive", "--drop-status", "stale"]), 200
        if action == "clear_resolved_inbox":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            contract = self.project_dir / ".superharness" / "contract.yaml"
            if not inbox.exists():
                return {"ok": True, "removed": 0}, 200
            # Load active task IDs from contract (non-done, non-archived)
            c_tasks = contract_tasks(contract)
            active_task_ids = {
                t["id"] for t in c_tasks
                if t.get("status") not in ("done", "archived")
                and t.get("id")
            }
            items = inbox_items(inbox)
            kept = [
                item for item in items
                if item.get("task") in active_task_ids
                or item.get("status") in ("pending", "launched", "running")
            ]
            removed = len(items) - len(kept)
            if removed > 0:
                import yaml as _yaml
                with open(inbox, "w", encoding="utf-8") as fh:
                    fh.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
                    for item in kept:
                        _yaml.dump([item], fh, default_flow_style=False, allow_unicode=True, sort_keys=True)
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
            harness_dir = self.project_dir / ".superharness"
            contract_file = harness_dir / "contract.yaml"
            try:
                import yaml as _yaml
                with open(contract_file) as _f:
                    _contract = _yaml.safe_load(_f)
                _tasks = _contract.get("tasks", [])
                _before = len(_tasks)
                _contract["tasks"] = [t for t in _tasks if t.get("id") != task_id]
                if len(_contract["tasks"]) == _before:
                    return ({"error": f"task '{task_id}' not found"}, 404)
                with open(contract_file, "w") as _f:
                    _yaml.safe_dump(_contract, _f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                return {"ok": True, "removed": task_id}, 200
            except Exception as exc:
                return ({"error": str(exc)}, 500)

        if action.startswith("set_owner:"):
            parts = action.split(":")
            if len(parts) < 3:
                return ({"error": "invalid action format"}, 400)
            task_id = parts[1]
            new_owner = parts[2]
            harness_dir = self.project_dir / ".superharness"
            contract_file = harness_dir / "contract.yaml"
            try:
                import yaml as _yaml
                with open(contract_file) as _f:
                    _contract = _yaml.safe_load(_f)
                _tasks = _contract.get("tasks", [])
                _found = False
                for t in _tasks:
                    if isinstance(t, dict) and t.get("id") == task_id:
                        t["owner"] = new_owner
                        _found = True
                        break
                if not _found:
                    return ({"error": f"task '{task_id}' not found"}, 404)
                with open(contract_file, "w") as _f:
                    _yaml.safe_dump(_contract, _f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                return {"ok": True, "task": task_id, "new_owner": new_owner}, 200
            except Exception as exc:
                return ({"error": str(exc)}, 500)

        if action.startswith("approve_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "plan_approved", from_status="plan_proposed")
            return result, (200 if result.get("ok") else 500)

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
            from superharness.commands.inbox_enqueue import infer_workflow as _infer_wf
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
            return self._run_cmd(inbox_py + ["remove", "--file", inbox_file, "--id", item_id]), 200

        return ({"error": f"unsupported action: {action}"}, 400)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        p = parsed.path
        if p in {"/", "/index.html"}:
            self._html(HTML)
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

        if p == "/api/status":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            ledger = self.project_dir / ".superharness" / "ledger.md"
            contract = self.project_dir / ".superharness" / "contract.yaml"
            outlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.out.log"
            errlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.err.log"
            now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            runtime = watcher_runtime(self.label)
            state = str(runtime.get("state", ""))
            items = inbox_items(inbox)
            wcfg = watcher_config(self.project_dir)
            self._json(
                {
                    "version": __version__,
                    "project": str(self.project_dir),
                    "label": self.label,
                    "launchctl_state": state or ("loaded" if runtime.get("loaded") else ""),
                    "watcher_health": watcher_health(runtime, items, now_utc),
                    "heartbeat": heartbeat_health(self.project_dir),
                    "agent_status": _agent_status_health(self.project_dir),
                    "watcher_runtime": runtime,
                    "watcher_project": str(wcfg.get("watcher_project", str(self.project_dir))),
                    "watcher_config": wcfg,
                    "contract_id": contract_id(contract),
                    "contract_tasks": contract_tasks(contract),
                    "contract_owners": contract_owners(contract),
                    "all_task_owners": list(set(KNOWN_AGENTS) | {
                        t.get("owner") for t in (contract_tasks(contract) or [])
                        if isinstance(t, dict) and t.get("owner")
                    } | {
                        item.get("to") for item in inbox_items(inbox)
                        if item.get("to")
                    }),
                    "active_inbox_tasks": list({
                        item.get("task") for item in inbox_items(inbox)
                        if item.get("status") in ("pending", "launched", "running")
                        and item.get("task")
                    }),
                    "paused_inbox_tasks": list({
                        item.get("task") for item in inbox_items(inbox)
                        if item.get("status") == "paused"
                        and item.get("task")
                    }),
                    "failed_inbox_tasks": list({
                        item.get("task") for item in inbox_items(inbox)
                        if item.get("status") in ("failed", "stale")
                        and item.get("task")
                    }),
                    "done_inbox_tasks": list({
                        item.get("task") for item in inbox_items(inbox)
                        if item.get("status") == "done"
                        and item.get("task")
                    }),
                    "inbox_counts": inbox_counts(inbox),
                    "inbox_owners": inbox_owner_counts(inbox),
                    "review_queue_count": sum(
                        1 for t in contract_tasks(contract)
                        if t.get("status") in {"review_requested", "review_passed", "review_failed"}
                    ),
                    "review_queue": review_queue(contract),
                    "board_columns": board_tasks(contract),
                    "budget": budget_signals(self.project_dir),
                    "git_context": git_context(self.project_dir),
                    "activity_feed": activity_feed(self.project_dir, inbox, ledger),
                    "ledger_tail": tail_lines(ledger, 18),
                    "out_tail": tail_lines(outlog, 16),
                    "err_tail": tail_lines(errlog, 16),
                    "now_utc": now_utc,
                    "refresh_seconds": self.refresh_seconds,
                }
            )
            return

        if p == "/api/inbox":
            qs = parse_qs(parsed.query)
            status_filter = qs.get("status", [""])[0]
            owner_filter = qs.get("owner", [])
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            items = inbox_items(inbox)
            if status_filter:
                if status_filter == "active":
                    _ACTIVE = {"pending", "launched", "running", "paused"}
                    items = [i for i in items if i.get("status") in _ACTIVE]
                else:
                    items = [i for i in items if i.get("status") == status_filter]
            if owner_filter:
                items = [i for i in items if i.get("to") in owner_filter]
            self._json({"items": items, "status": status_filter, "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return

        if p == "/api/adapter-preview":
            # Adapter-payload preview: render todo nodes from the live project
            contract = self.project_dir / ".superharness" / "contract.yaml"
            project_name = self.project_dir.name
            todo_tasks = []

            if contract.exists():
                try:
                    import yaml
                    doc = yaml.safe_load(contract.read_text()) or {}
                    for task in doc.get("tasks", []):
                        if isinstance(task, dict) and task.get("status") == "todo":
                            todo_tasks.append({
                                "id": task.get("id", ""),
                                "title": task.get("title", ""),
                                "owner": task.get("owner", ""),
                                "effort": task.get("effort", "medium"),
                                "blocked_by": _normalize_blocked_by(task.get("blocked_by")),
                            })
                except Exception as e:
                    self._json({"error": str(e), "project": project_name, "tasks": []}, 500)
                    return

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
            lines = int(qs.get("lines", ["200"])[0])
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
                # Include task metadata for dispatch preview
                task_meta = {}
                contract_file = self.project_dir / ".superharness" / "contract.yaml"
                if contract_file.exists():
                    import yaml as _y
                    doc = _y.safe_load(contract_file.read_text()) or {}
                    for t in doc.get("tasks") or []:
                        if isinstance(t, dict) and t.get("id") == task_id:
                            task_meta = {
                                "owner": t.get("owner", "claude-code"),
                                "status": t.get("status", "todo"),
                                "workflow": t.get("workflow", "implementation"),
                                "model": t.get("model", ""),
                                "effort": t.get("effort", "medium"),
                                "timeout_minutes": t.get("timeout_minutes"),
                                "test_types": ", ".join(t.get("test_types") or []),
                            }
                            break
                self._json({"task": task_id, "instructions": text, "task_meta": task_meta})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
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

        if p == "/api/board":
            contract = self.project_dir / ".superharness" / "contract.yaml"
            agent_health = _agent_status_health(self.project_dir)
            bv = board_view(contract)
            self._json({
                # New fields (feat.dashboard-operator-upgrade)
                "board": board_tasks(contract),
                "review_queue": review_queue(contract),
                "agent_health": agent_health,
                "budget": budget_signals(self.project_dir),
                # Legacy fields (backward compat with existing tests/JS)
                "columns": bv.get("columns", {}),
                "totals": bv.get("totals", {}),
                "agent_status": agent_health,
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        if p == "/api/review-queue":
            contract = self.project_dir / ".superharness" / "contract.yaml"
            self._json({
                "queue": review_queue(contract),
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        if p == "/api/costs":
            try:
                from superharness.engine.benchmark import load_records, aggregate
            except ImportError:
                self._json({"error": "benchmark module not available"}, 500)
                return
            qs = parse_qs(parsed.query)
            top_n = int(qs.get("top", ["20"])[0])
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
            except Exception:
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
            except Exception:
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
                # Remove all tasks owned by this owner
                try:
                    import yaml
                    doc = yaml.safe_load(contract.read_text()) or {}
                    tasks = doc.get("tasks") or []
                    doc["tasks"] = [t for t in tasks if not (isinstance(t, dict) and t.get("owner") == owner)]
                    contract.write_text(yaml.dump(doc, default_flow_style=False, sort_keys=False))
                except Exception as e:
                    self._json({"error": str(e)}, 500)
                    return
                self._json({"ok": True, "owners": contract_owners(contract)})
                return

            self._json({"error": f"unknown owner action: {action}"}, 400)
            return

        self._json({"error": "not found"}, 404)


def _get_installed_version() -> str:
    """Return the installed package version, or 'unknown' if unavailable."""
    try:
        import importlib.metadata
        return importlib.metadata.version("superharness")
    except Exception:
        return "unknown"


def _append_ledger(project_dir: str, line: str) -> None:
    """Append *line* to .superharness/ledger.md, creating the file if absent."""
    ledger_path = os.path.join(project_dir, ".superharness", "ledger.md")
    try:
        with open(ledger_path, "a") as fh:
            fh.write(line)
    except Exception:
        pass  # Ledger writes must never crash the watchdog


def autohealth_check(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """Ping the dashboard server. Returns True if healthy, False otherwise."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/status")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
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
            except Exception:
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
            except Exception:
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

    # Guard: prevent a second dashboard for the same project directory.
    _my_pid = os.getpid()
    try:
        import subprocess as _sp
        _ps = _sp.run(["ps", "ax", "-o", "pid=,args="], capture_output=True, text=True).stdout
        for _line in _ps.splitlines():
            _line = _line.strip()
            if "dashboard-ui.py" not in _line and "monitor-ui.py" not in _line:
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
                    capture_output=True, text=True,
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
                print(f"dashboard already running for project '{project_dir.name}' (pid={_other_pid}, {_url})")
                print(f"  kill it first:  shux dashboard-kill --project {project_dir}")
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass  # Guard failure must never block startup

    Handler.project_dir = project_dir
    Handler.label = project_label(project_dir)
    Handler.refresh_seconds = args.refresh_seconds
    Handler.scripts_dir = scripts_dir
    Handler.auth_token = secrets.token_urlsafe(24)

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
    url = f"http://{args.host}:{port}"
    print(f"dashboard: {url}")
    print(f"project: {project_dir}")
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


if __name__ == "__main__":
    raise SystemExit(main())
