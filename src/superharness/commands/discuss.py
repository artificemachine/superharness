"""Python port of discuss.sh — discussion and approval-gate management.

Wraps superharness.engine.discuss and superharness.engine.discussion.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from superharness.commands.task import VALID_OWNERS


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_status(handoff_dir: str, task_id: str | None = None) -> int:
    if not os.path.isdir(handoff_dir):
        print("No handoffs directory", file=sys.stderr)
        return 0

    from superharness.engine.discuss import cmd_status as engine_status
    return engine_status(handoff_dir, task_filter=task_id or None)


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
    """Return distinct owner values from contract tasks, in order."""
    try:
        import yaml
        with open(contract_file) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return []
    tasks = doc.get("tasks") or []
    seen: dict[str, None] = {}
    for t in tasks:
        if isinstance(t, dict) and t.get("owner"):
            seen[t["owner"]] = None
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
    owners: list[str] | None = None,
    exclude: list[str] | None = None,
) -> int:
    import secrets
    import subprocess

    os.makedirs(discussions_dir, exist_ok=True)

    from superharness.engine.inbox import HEADER, _inbox_lock, enqueue

    # Derive participants from explicit owners or the contract, applying exclusions.
    all_owners = _normalize_owners(owners) or _read_contract_owners(contract_file)
    exclude_set = set(exclude or [])
    participants = [o for o in all_owners if o not in exclude_set]

    if len(participants) < 2:
        print(
            f"Error: discussions require at least 2 distinct task owners in contract "
            f"(found: {len(participants)} after exclusions).",
            file=sys.stderr,
        )
        if exclude_set:
            print(f"Excluded: {' '.join(sorted(exclude_set))}", file=sys.stderr)
        if owners:
            print("Pass at least 2 owners after exclusions.", file=sys.stderr)
        else:
            print("Add tasks for both claude-code and codex-cli or pass --owners.", file=sys.stderr)
        return 2

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

    return 0


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
        outcome_lines.append(f"  {agent}: {', '.join(vs)}")

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
    p.add_argument("--owners", action="append", default=[], metavar="OWNER[,OWNER...]")
    p.add_argument("--exclude", action="append", default=[], metavar="OWNER")

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
        rc = cmd_status(handoff_dir, task_id=getattr(opts, "task", None))

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
            owners=opts.owners,
            exclude=opts.exclude,
        )

    elif opts.subcmd == "rounds":
        rc = cmd_rounds(discussions_dir, opts.disc_id)

    elif opts.subcmd == "consensus":
        rc = cmd_consensus(discussions_dir, opts.disc_id)

    elif opts.subcmd == "list":
        rc = cmd_list(discussions_dir)

    elif opts.subcmd == "summary":
        rc = cmd_summary(discussions_dir, opts.disc_id, handoff_dir)

    else:
        _abort(f"Unknown discuss subcommand: {opts.subcmd}", 2)

    sys.exit(rc)


if __name__ == "__main__":
    main()
