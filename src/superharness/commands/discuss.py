"""Python port of discuss.sh — discussion and approval-gate management.

Wraps superharness.engine.discuss and superharness.engine.discussion.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from superharness.commands.task import VALID_OWNERS

import logging
logger = logging.getLogger(__name__)

# Primary agents always included in discussions by default (before contract-owner
# additions). Consistent with KNOWN_AGENTS / VALID_TARGETS across the codebase.
PRIMARY_AGENTS = ["claude-code", "codex-cli", "gemini-cli", "opencode"]


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _watcher_is_alive(project_dir: str) -> bool:
    """Return True when the watcher has a live (non-zombie) heartbeat."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import heartbeat_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            hb = heartbeat_dao.get(conn, "watcher")
            return hb is not None and hb.status not in ("zombie", None)
        finally:
            conn.close()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_status(handoff_dir: str, task_id: str | None = None) -> int:
    if not os.path.isdir(handoff_dir):
        print("No handoffs directory", file=sys.stderr)
        return 0

    from superharness.engine.discuss import cmd_status as engine_status
    engine_status(handoff_dir, task_filter=task_id or None)
    return 0


def cmd_approve(
    handoff_dir: str,
    contract_file: str,
    inbox_file: str,
    task_id: str,
    project_dir: str,
    actor: str,
    note: str,
) -> int:
    if not os.path.isdir(handoff_dir):
        _abort("No handoffs directory", 1)

    from superharness.engine.discuss import cmd_approve as engine_approve
    return engine_approve(
        handoff_dir=handoff_dir,
        contract_file=contract_file,
        inbox_file=inbox_file,
        task_id=task_id,
        project_dir=project_dir,
        actor=actor,
        note=note,
    )


def _read_contract_owners(contract_file: str) -> list[str]:
    """Return distinct owner values from contract tasks (SQLite only)."""
    seen: dict[str, None] = {}
    try:
        import os
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            for task in tasks_dao.get_all(conn):
                owner = getattr(task, "owner", None)
                if owner:
                    seen[owner] = None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("discuss.py unexpected error: %s", e, exc_info=True)
        pass
    return list(seen.keys())


def _normalize_owners(values: list[str] | None) -> list[str]:
    seen: dict[str, None] = {}
    for value in values or []:
        for owner in str(value).split(","):
            owner = owner.strip()
            if owner:
                seen[owner] = None
    return list(seen.keys())


def cmd_start(
    discussions_dir: str,
    inbox_file: str,
    contract_file: str,
    topic: str,
    task_id: str | None,
    max_rounds: int,
    project_dir: str,
    actor: str,
    tier: str | None = None,
    effort: str | None = None,
    owners: list[str] | None = None,
    exclude: list[str] | None = None,
    force: bool = False,
) -> int:
    import secrets
    import subprocess

    os.makedirs(discussions_dir, exist_ok=True)

    # Pre-condition: check if the watcher is alive before starting a discussion.
    # Without the watcher, discussion rounds will sit undispatched forever.
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import heartbeat_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            watcher = heartbeat_dao.get(conn, "watcher")
            if watcher is None or watcher.status == "zombie":
                print(
                    "⚠️  Watcher is not running. Discussion rounds will NOT be dispatched. "
                    "Start the watcher first: shux operator start",
                    file=sys.stderr,
                )
        finally:
            conn.close()
    except Exception:
        pass  # best-effort check, don't block on it

    from superharness.engine.inbox import HEADER, _inbox_lock, enqueue

    # Derive participants from explicit owners or the contract, applying exclusions.
    norm_owners = _normalize_owners(owners)
    if "all" in norm_owners:
        from superharness.engine.adapter_registry import list_adapters
        all_owners = list_adapters()
    elif not norm_owners:
        contract_owners = _read_contract_owners(contract_file)
        all_owners = list(dict.fromkeys(PRIMARY_AGENTS + contract_owners))
    else:
        all_owners = norm_owners

    # _normalize_owners splits comma-joined values so "--exclude foo,bar" works
    # the same as "--exclude foo --exclude bar". Without this, "foo,bar" is
    # treated as a single literal name and neither agent is excluded.
    exclude_set = set(_normalize_owners(exclude))
    candidates = [o for o in all_owners if o not in exclude_set]

    # Only AI agents (those with registered adapters) can participate in a discussion.
    # Human roles like "owner" are never dispatched via inbox and would permanently
    # block verdict collection and auto-consensus.
    from superharness.engine.adapter_registry import list_adapters
    _ai_agents = set(list_adapters())
    non_agents = [o for o in candidates if o not in _ai_agents]
    participants = [o for o in candidates if o in _ai_agents]

    if non_agents:
        print(
            f"Note: {', '.join(non_agents)} removed from participants "
            f"(not a registered AI agent — human roles cannot receive inbox dispatch).",
            file=sys.stderr,
        )

    # Agent availability check: verify which participants have recent heartbeats
    # (i.e., are actually running). Discussions with < 2 available agents are
    # blocked unless --force is passed, because single-participant discussions
    # cannot reach consensus.
    AGENT_HEARTBEAT_STALE_SECONDS = 300  # 5 min — same as watcher's poll cycle
    available_agents = []
    unavailable_agents = []
    try:
        from datetime import datetime, timezone
        conn2 = get_connection(project_dir)
        try:
            init_db(conn2)
            now = datetime.now(timezone.utc)
            for p in participants:
                hb = heartbeat_dao.get(conn2, p)
                if hb and hb.written_at:
                    try:
                        hb_ts = datetime.fromisoformat(str(hb.written_at).replace("Z", "+00:00"))
                        age = (now - hb_ts).total_seconds()
                        if age < AGENT_HEARTBEAT_STALE_SECONDS and hb.status not in ("zombie", None):
                            available_agents.append(p)
                            continue
                    except (ValueError, TypeError):
                        pass
                unavailable_agents.append(p)
        finally:
            conn2.close()
    except Exception:
        pass  # best-effort check

    if unavailable_agents:
        for agent in unavailable_agents:
            print(
                f"⚠️  {agent}: may not respond — no daemon heartbeat (agent not running)",
                file=sys.stderr,
            )

    if len(available_agents) < 2 and not force:
        if len(participants) >= 2 and _watcher_is_alive(project_dir):
            print(
                f"Note: {len(available_agents)}/{len(participants)} agents have heartbeats "
                f"but the watcher is active — rounds will be dispatched via inbox.",
                file=sys.stderr,
            )
        else:
            print(
                f"\nError: only {len(available_agents)} of {len(participants)} participants "
                f"are running (have recent heartbeats).",
                file=sys.stderr,
            )
            print(
                f"At least 2 running agents are required for a valid discussion. "
                f"Use --force to override.",
                file=sys.stderr,
            )
            print(
                f"\nTip: submit verdicts manually via CLI — no agent session needed:",
                file=sys.stderr,
            )
            for agent in participants:
                print(
                    f"  shux discuss submit --project {project_dir} "
                    f"--discussion <id> --agent {agent} --round <N> "
                    f"--verdict <agree|disagree|partial|consensus|abstain>",
                    file=sys.stderr,
                )
            print(
                f"\nAvailable: {', '.join(available_agents) if available_agents else 'none'}",
                file=sys.stderr,
            )
            return 1
    elif len(available_agents) < len(participants):
        print(
            f"Note: {len(available_agents)}/{len(participants)} participants are running. "
            f"Missing agents can submit manually via CLI or will time out.",
            file=sys.stderr,
        )

    # Require at least n-1 of the available AI agents (minimum 2).
    available = sorted(set(candidates) & _ai_agents)
    required = max(2, len(available) - 1)

    if len(participants) < required:
        print(
            f"Error: discussions require at least {required} AI-agent participants "
            f"(found: {len(participants)} of {len(available)} available).",
            file=sys.stderr,
        )
        if exclude_set:
            print(f"Excluded: {' '.join(sorted(exclude_set))}", file=sys.stderr)
        if non_agents:
            print(f"Non-agent (removed): {' '.join(non_agents)}", file=sys.stderr)
        print(
            "Pass --owners " + " ".join(available)
            + f" (at least {required} required).",
            file=sys.stderr,
        )
        return 2

    # Check agent availability: warn about agents without running daemons.
    unavailable = []
    try:
        from superharness.commands.discussion_dispatch import _agent_available
        for agent in participants:
            ok, reason = _agent_available(agent, project_dir)
            if not ok:
                unavailable.append((agent, reason))
    except Exception:
        pass  # best-effort check, don't block on it
    if unavailable:
        for agent, reason in unavailable:
            print(
                f"⚠️  {agent}: may not respond — {reason}",
                file=sys.stderr,
            )

    # Recommend full coverage when fewer than all available agents are included.
    missing = sorted(set(available) - set(participants))
    if missing:
        print(
            f"Note: {len(participants)} agent(s) selected, {len(missing)} excluded: "
            f"{' '.join(missing)}.",
            file=sys.stderr,
        )

    participant_args: list[str] = []
    for p in participants:
        participant_args += ["--participant", p]

    result = subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion", "start",
         "--discussions-dir", discussions_dir,
         "--topic", topic,
         "--max-rounds", str(max_rounds),
         "--project", project_dir,
         "--created-by", actor]
        + participant_args
        + (["--task", task_id] if task_id else []),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    try:
        disc = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Failed to parse discussion engine output: {e}", file=sys.stderr)
        return 1

    disc_id = disc["id"]
    disc_dir = disc["discussion_dir"]

    print(f"Discussion started: {disc_id}")
    print(f"  Topic: {topic}")
    print(f"  Max rounds: {max_rounds}")
    print(f"  Participants: {' '.join(participants)}")
    print(f"  Directory: {disc_dir}")

    # Create contract task for round 1
    round_task_id = f"{disc_id}/round-1"
    round_task_owner = next((p for p in participants if p in VALID_OWNERS), participants[0])
    subprocess.run(
        [sys.executable, "-m", "superharness.commands.task", "create",
         "--project", project_dir,
         "--id", round_task_id,
         "--title", f"Discussion round 1: {topic}",
         "--owner", round_task_owner,
         "--status", "in_progress",
         "--workflow", "discussion"],
        capture_output=True, check=False,
    )

    # Classify the discussion topic to determine model tier and effort.
    # Uses the multi-agent classifier chain (cheapest mini model first).
    # Falls back to standard/medium on any failure.
    # --tier and --effort flags override auto-classification.
    try:
        from superharness.engine.model_router import classify_task
        from superharness.engine.db import get_connection, init_db

        if tier and effort:
            # Both flags given: skip classifier entirely
            print(f"  Tier override: {tier}, effort override: {effort}")
        elif tier:
            # --tier given: classify effort only
            _, effort = classify_task(title=topic, project_dir=project_dir)
            print(f"  Tier override: {tier} (classified effort: {effort})")
        elif effort:
            # --effort given: classify tier only
            tier, _ = classify_task(title=topic, project_dir=project_dir)
            print(f"  Effort override: {effort} (classified tier: {tier})")
        else:
            tier, effort = classify_task(title=topic, project_dir=project_dir)
            print(f"  Classified: tier={tier} effort={effort}")

        conn = get_connection(project_dir)
        try:
            init_db(conn)
            conn.execute(
                "UPDATE tasks SET model_tier = ?, effort = ? WHERE id = ?",
                (tier, effort, round_task_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        # Classification is best-effort. Failure falls back to standard at dispatch.
        logger.warning("discuss.py unexpected error: %s", e, exc_info=True)

    # Ensure inbox file exists
    if not os.path.exists(inbox_file):
        with open(inbox_file, "w") as f:
            f.write(HEADER)

    # Enqueue round 1 inbox items for each participant
    for agent in participants:
        now_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rand_part = secrets.token_hex(3)
        item_id = f"{now_ts}-{disc_id}-r1-{agent}-{os.getpid()}-{rand_part}"
        created_at = _now_utc()

        with _inbox_lock(inbox_file):
            rc = enqueue(
                file=inbox_file,
                id=item_id,
                to=agent,
                task=f"{disc_id}/round-1",
                project=project_dir,
                priority=1,
                created_at=created_at,
            )
        if rc == 0:
            print(f"  Enqueued round 1 for {agent}: {item_id}")
        # Shadow entry in SQLite so the watcher can see discussion items
        _enqueue_sqlite_shadow(project_dir, item_id, disc_id, agent, created_at)

    # Show manual submission instructions — no active session required.
    # Each participant can submit via CLI, or the watcher dispatches via session-inject.
    print()
    print("═" * 60)
    print("Manual submission (no agent session needed):")
    print("═" * 60)
    for agent in participants:
        print(f"  {agent}:")
        print(f"    shux discuss submit --project {project_dir} \\")
        print(f"      --discussion {disc_id} --agent {agent} --round 1 \\")
        print(f'      --verdict <agree|disagree|partial|consensus|abstain> \\')
        print(f'      --position "your analysis here"')
        print()
    print(f"Status: shux discuss list --project {project_dir}")
    print("═" * 60)

    return 0


def _enqueue_sqlite_shadow(
    project_dir: str,
    item_id: str,
    disc_id: str,
    agent: str,
    created_at: str,
) -> None:
    """Write a shadow inbox row with type='discussion' so the watcher can track it."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao as _dao
        from superharness.engine.state_errors import StateError

        conn = get_connection(project_dir)
        try:
            init_db(conn)
            # Discussion shadow rows reference a disc_id, not a task id — relax FK
            conn.execute("PRAGMA foreign_keys=OFF")
            _dao.enqueue(
                conn,
                id=item_id,
                task_id=f"{disc_id}/round-1",
                target_agent=agent,
                priority=1,
                max_retries=3,
                project_path=project_dir,
                plan_only=False,
                type="discussion",
                now=created_at,
            )
            conn.commit()
        except StateError:
            # Already enqueued by primary path — idempotent, skip silently
            pass
        finally:
            conn.close()
    except Exception as e:
        logger.warning("discuss.py unexpected error: %s", e, exc_info=True)
        pass
def cmd_rounds(discussions_dir: str, disc_id: str) -> int:
    disc_dir = os.path.join(discussions_dir, disc_id)
    if not os.path.isdir(disc_dir):
        _abort(f"Discussion not found: {disc_id}")

    result = _subprocess_run_capture(
        [sys.executable, "-m", "superharness.engine.discussion", "status",
         "--discussion-dir", disc_dir]
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    try:
        d = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        return 0

    print(f"Discussion: {d['id']}")
    print(f"  Topic: {d['topic']}")
    print(f"  Status: {d['status']}")
    print(f"  Round: {d['current_round']}/{d['max_rounds']}")
    print(f"  Participants: {', '.join(d.get('participants') or [])}")
    print()
    for r in d.get("rounds") or []:
        print(f"  Round {r['round']}:")
        subs = r.get("submissions") or []
        if not subs:
            print("    (no submissions yet)")
        else:
            for s in subs:
                print(f"    {s.get('agent', '')}: verdict={s.get('verdict', '')} ({s.get('submitted_at', '')})")
    return 0


def cmd_consensus(discussions_dir: str, disc_id: str) -> int:
    disc_dir = os.path.join(discussions_dir, disc_id)
    if not os.path.isdir(disc_dir):
        _abort(f"Discussion not found: {disc_id}")

    result = _subprocess_run_capture(
        [sys.executable, "-m", "superharness.engine.discussion", "check_consensus",
         "--discussion-dir", disc_dir]
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    try:
        r = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        return 0

    if r.get("consensus"):
        print(f"CONSENSUS reached at round {r.get('round', '')}")
    else:
        print(f"No consensus at round {r.get('round', '')}")
        for a, v in (r.get("verdicts") or {}).items():
            print(f"  {a}: {v}")
    return 0


def cmd_list(discussions_dir: str) -> int:
    os.makedirs(discussions_dir, exist_ok=True)

    result = _subprocess_run_capture(
        [sys.executable, "-m", "superharness.engine.discussion", "list",
         "--discussions-dir", discussions_dir]
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    try:
        ds = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        return 0

    if not ds:
        print("No discussions.")
    else:
        for d in ds:
            print(
                f"{d.get('id', '')}  status={d.get('status', '')}  "
                f"round={d.get('current_round', '')}/{d.get('max_rounds', '')}  "
                f"topic={d.get('topic', '')}"
            )
    return 0


def cmd_summary(discussions_dir: str, disc_id: str, handoff_dir: str) -> int:
    """Write a handoff YAML summarising a concluded discussion (Phase 5).

    Reads all round submissions, extracts verdicts and notes, and writes
    a machine-readable handoff to .superharness/handoffs/ so the next agent
    can load the outcome via `shux recall`.
    """
    disc_dir = os.path.join(discussions_dir, disc_id)
    if not os.path.isdir(disc_dir):
        _abort(f"Discussion not found: {disc_id}")

    # Load discussion state via engine
    result = _subprocess_run_capture(
        [sys.executable, "-m", "superharness.engine.discussion", "status",
         "--discussion-dir", disc_dir]
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    try:
        d = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"discuss summary: could not parse discussion state", file=sys.stderr)
        return 1

    topic = d.get("topic", "unknown")
    status = d.get("status", "unknown")
    participants = d.get("participants") or []
    rounds = d.get("rounds") or []

    # Aggregate verdicts and notes across all rounds
    verdicts: dict[str, list[str]] = {}
    notes: list[str] = []
    for r in rounds:
        for sub in (r.get("submissions") or []):
            agent = sub.get("agent", "unknown")
            verdict = sub.get("verdict", "")
            note = sub.get("note", "")
            verdicts.setdefault(agent, []).append(verdict)
            if note:
                notes.append(f"{agent} (round {r.get('round', '?')}): {note}")

    outcome_lines = [f"Topic: {topic}", f"Status: {status}",
                     f"Participants: {', '.join(participants)}"]
    for agent, vs in verdicts.items():
        vs_str = ", ".join(str(v) for v in vs)
        outcome_lines.append(f"  {agent}: {vs_str}")

    now = _now_utc()
    safe_id = disc_id.replace("/", "_").replace("..", "_")
    filename = f"discuss.{safe_id}.summary-{now[:10]}.yaml"
    os.makedirs(handoff_dir, exist_ok=True)
    handoff_path = os.path.join(handoff_dir, filename)

    content = (
        f"task: discuss.{disc_id}\n"
        f"phase: summary\n"
        f"status: {status}\n"
        f"from: discuss\n"
        f"to: owner\n"
        f"date: {now}\n"
        f"outcome: |\n"
        + "\n".join(f"  {line}" for line in outcome_lines) + "\n"
    )
    if notes:
        content += "notes:\n" + "\n".join(f"  - |\n    {n}" for n in notes) + "\n"

    with open(handoff_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Discussion summary written: {handoff_path}")
    return 0


def _subprocess_run_capture(cmd: list[str]) -> "subprocess.CompletedProcess":
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="discuss",
        description="superharness discussion and approval-gate management",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="subcmd")

    # status
    p = sub.add_parser("status", add_help=True)
    p.add_argument("disc_id", nargs="?", default=None,
                   help="Optional discussion ID to filter output")
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--task", default=None)

    # approve
    p = sub.add_parser("approve", add_help=True)
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--task", required=True)
    p.add_argument("--by", default="owner", dest="actor")
    p.add_argument("--note", default="")

    # start
    p = sub.add_parser("start", add_help=True)
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--topic", required=True)
    p.add_argument("--task", default=None)
    p.add_argument("--max-rounds", type=int, default=3)
    p.add_argument("--tier", default=None, choices=["mini", "standard", "max"],
                   help="Force discussion tier (bypasses auto-classification)")
    p.add_argument("--effort", default=None, choices=["low", "medium", "high"],
                   help="Force discussion effort (bypasses auto-classification)")
    p.add_argument("--owners", action="append", default=[], metavar="OWNER[,OWNER...]")
    p.add_argument("--exclude", action="append", default=[], metavar="OWNER")
    p.add_argument("--force", action="store_true", default=False,
                   help="Allow discussion with fewer than 2 running agents")

    # rounds
    p = sub.add_parser("rounds", add_help=True)
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--id", required=True, dest="disc_id")

    # consensus
    p = sub.add_parser("consensus", add_help=True)
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--id", required=True, dest="disc_id")

    # list
    p = sub.add_parser("list", add_help=True)
    p.add_argument("--project", "-p", default=None)

    # summary
    p = sub.add_parser("summary", add_help=True,
                       help="Write a handoff YAML from a concluded discussion")
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--id", required=True, dest="disc_id")

    # submit
    p = sub.add_parser("submit", add_help=True,
                       help="Submit a discussion round response")
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--discussion", required=True, dest="disc_id")
    p.add_argument("--agent", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--verdict", required=True, help="consensus|disagree|abstain")
    p.add_argument("--position", required=True, help="Your position statement")
    p.add_argument("--points-file", default=None, help="YAML file with point-by-point responses")

    # close — first-class way to terminate an active discussion AND cancel
    # any pending inbox items for its rounds. Bug G follow-up
    # (docs/bugs/2026-05-11_discuss_dispatch_bugs.md §8).
    p = sub.add_parser("close", add_help=True,
                       help="Close an active discussion and cancel its pending rounds")
    p.add_argument("--project", "-p", default=None)
    p.add_argument("--id", required=True, dest="disc_id")
    p.add_argument("--outcome", default="closed",
                   help="Status to set: closed|cancelled|failed|consensus (default: closed)")
    p.add_argument("--reason", default="",
                   help="Free-text reason recorded on each cancelled inbox item")

    opts = parser.parse_args(argv)
    if not opts.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    harness_dir = os.path.join(project_dir, ".superharness")
    handoff_dir = os.path.join(harness_dir, "handoffs")
    contract_file = os.path.join(harness_dir, "contract.yaml")
    inbox_file = os.path.join(harness_dir, "inbox.yaml")
    discussions_dir = os.path.join(harness_dir, "discussions")

    if not os.path.isdir(harness_dir):
        _abort(f"Missing .superharness directory: {harness_dir}")

    if opts.subcmd == "status":
        filter_id = getattr(opts, "disc_id", None) or getattr(opts, "task", None)
        rc = cmd_status(handoff_dir, task_id=filter_id)

    elif opts.subcmd == "approve":
        if not os.path.isdir(handoff_dir):
            _abort("No handoffs directory", 1)
        rc = cmd_approve(
            handoff_dir=handoff_dir,
            contract_file=contract_file,
            inbox_file=inbox_file,
            task_id=opts.task,
            project_dir=project_dir,
            actor=opts.actor,
            note=opts.note,
        )

    elif opts.subcmd == "start":
        rc = cmd_start(
            discussions_dir=discussions_dir,
            inbox_file=inbox_file,
            contract_file=contract_file,
            topic=opts.topic,
            task_id=opts.task or None,
            max_rounds=opts.max_rounds,
            project_dir=project_dir,
            actor="owner",
            tier=opts.tier,
            effort=opts.effort,
            owners=opts.owners,
            exclude=opts.exclude,
            force=opts.force,
        )

    elif opts.subcmd == "rounds":
        rc = cmd_rounds(discussions_dir, opts.disc_id)

    elif opts.subcmd == "consensus":
        rc = cmd_consensus(discussions_dir, opts.disc_id)

    elif opts.subcmd == "list":
        rc = cmd_list(discussions_dir)

    elif opts.subcmd == "summary":
        rc = cmd_summary(discussions_dir, opts.disc_id, handoff_dir)

    elif opts.subcmd == "submit":
        from superharness.engine.discussion import cmd_submit_round
        disc_dir = os.path.join(discussions_dir, opts.disc_id)
        rc = cmd_submit_round(
            discussion_dir=disc_dir,
            round_=opts.round,
            agent=opts.agent,
            verdict=opts.verdict,
            position=opts.position,
            points_file=opts.points_file,
        )

    elif opts.subcmd == "close":
        from superharness.engine.discussion import cmd_close
        disc_dir = os.path.join(discussions_dir, opts.disc_id)
        rc = cmd_close(
            discussion_dir=disc_dir,
            outcome=opts.outcome,
            reason=opts.reason,
        )

    else:
        _abort(f"Unknown discuss subcommand: {opts.subcmd}", 2)

    sys.exit(rc)


if __name__ == "__main__":
    main()
