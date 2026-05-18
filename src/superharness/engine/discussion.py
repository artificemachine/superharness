"""Python port of engine/discussion.rb — multi-round discussion engine.
v2: SQLite-only (post-YAML removal). All state lives in discussions + discussion_rounds tables.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from superharness.engine.db import get_connection, init_db
from superharness.engine import discussions_dao


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_project_dir(discussion_dir: str) -> str:
    """Extract project root from a discussion directory path.

    Cross-platform: normalise both Windows backslashes and POSIX slashes
    before splitting. Without this, Windows paths fall through unchanged
    and the engine connects to an empty SQLite DB.
    """
    normalised = discussion_dir.replace("\\", "/")
    return normalised.rsplit("/.superharness/discussions/", 1)[0]


def _get_disc_id(discussion_dir: str) -> str:
    """Extract discussion ID from a discussion directory path.

    Strips trailing separators and normalises backslashes to forward slashes
    so basename works regardless of platform — POSIX os.path.basename does
    not treat `\\` as a separator.
    """
    return os.path.basename(discussion_dir.rstrip("/\\").replace("\\", "/"))


def _connect(project_dir: str):
    conn = get_connection(project_dir)
    init_db(conn)
    return conn


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(
    discussions_dir: str,
    topic: str,
    participants: list[str],
    max_rounds: int,
    task_id: str | None,
    project: str,
    created_by: str,
) -> int:
    disc_id = _generate_id()
    now = _now_utc()

    conn = _connect(project)
    try:
        discussions_dao.create(
            conn,
            id=disc_id, topic=topic, owners=participants,
            task_id=task_id, now=now,
        )
        conn.commit()
    finally:
        conn.close()

    # Filesystem dir is the scratch location where each agent writes
    # round-N-<agent>.yaml submissions during dispatch. State of record
    # lives in SQLite, but the dir must exist or delegate.py aborts
    # with "Discussion directory not found".
    discussion_dir = os.path.join(discussions_dir, disc_id)
    os.makedirs(discussion_dir, exist_ok=True)
    print(
        json.dumps(
            {
                "id": disc_id,
                "discussion_dir": discussion_dir,
                "status": "active",
                "current_round": 1,
                "participants": participants,
            },
            separators=(", ", ": "),
        )
    )
    return 0


def cmd_submit_round(
    discussion_dir: str,
    round_: int,
    agent: str,
    verdict: str,
    position: str,
    points_file: str | None,
) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)
    now = _now_utc()

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")
        if disc.status != "active":
            sys.exit(f"Discussion is not active (status={disc.status})")
        if agent not in disc.owners:
            sys.exit(f"Agent '{agent}' is not a participant")

        # Check if already submitted this round
        existing = discussions_dao.get_rounds(conn, disc_id)
        for r in existing:
            if r.round_number == round_ and r.agent == agent:
                sys.exit(f"Round {round_} already submitted by {agent}")

        # Parse points file if provided
        points: list = []
        if points_file and os.path.exists(points_file):
            try:
                from superharness.engine.yaml_helpers import safe_load
                raw = safe_load(points_file, list)
                if isinstance(raw, list):
                    points = raw
            except Exception:
                pass

        discussions_dao.add_round(
            conn,
            discussion_id=disc_id,
            round_number=round_,
            agent=agent,
            content=position,
            verdict=verdict,
            now=now,
        )

        # Auto-transition to consensus if all participants submitted
        _check_all_submitted_and_set_consensus(conn, disc, round_)

        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"submitted": True, "round": round_, "agent": agent, "verdict": verdict}, separators=(", ", ": ")))
    return 0


def _check_all_submitted_and_set_consensus(conn, disc, round_: int) -> None:
    """If all participants submitted this round AND all verdicts agree,
    auto-transition the discussion to consensus. If any participant
    disagrees we leave status=active so the dispatcher can advance to
    the next round."""
    rounds = discussions_dao.get_rounds(conn, disc.id)
    submitted_agents = {r.agent for r in rounds if r.round_number == round_}

    if len(submitted_agents) < len(disc.owners):
        return

    # Explicit disagreement → keep active and let the dispatcher advance
    # to the next round (or close as no_consensus when max_rounds is
    # reached). Verdicts of "agree" / "consensus" / "partial" / "" all
    # signal alignment; only "disagree" blocks the auto-transition.
    verdicts = {(r.verdict or "").lower() for r in rounds if r.round_number == round_}
    if "disagree" in verdicts:
        return

    now = _now_utc()
    conn.execute(
        "UPDATE discussions SET status='consensus', consensus=? WHERE id=?",
        (f"consensus — all {len(submitted_agents)} participants submitted round {round_}", disc.id),
    )
    print(
        f"[discussion] auto-consensus: all {len(submitted_agents)} participants submitted round {round_} → consensus",
        file=sys.stderr,
    )

    # Auto-create contract task from consensus points
    _create_consensus_task(conn, disc, round_, submitted_agents)


def _create_consensus_task(conn, disc, round_: int, submitted_agents: set[str]) -> None:
    """Auto-create a contract task from discussion consensus points (non-agree items)."""
    try:
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow

        disc_id = disc.id
        task_id = f"impl-{disc_id[:30]}"

        # Collect non-agree points from round submissions
        rounds = discussions_dao.get_rounds(conn, disc_id)
        all_points = []
        has_actionable = False
        for r in rounds:
            if r.round_number != round_:
                continue
            if r.verdict:
                v = r.verdict.lower()
                point_id = f"{r.agent}-{round_}"
                all_points.append({"id": point_id, "verdict": v})
                if v != "agree":
                    has_actionable = True

        if not has_actionable:
            return

        criteria = [f"Implement consensus from {disc_id}"]
        for p in all_points:
            criteria.append(f"  * {p['id']} [{p['verdict']}]")

        owner = disc.owners[0] if disc.owners else "claude-code"
        topic = str(disc.topic)[:80]
        now = _now_utc()
        # Derive project_dir from the connection path
        import sqlite3 as _sql
        project_dir = "/"  # fallback
        try:
            db_path = conn.execute("PRAGMA database_list").fetchone()
            if db_path:
                project_dir = os.path.dirname(os.path.dirname(db_path["file"]))
        except Exception:
            pass

        tasks_dao.upsert(conn, TaskRow(
            id=task_id, title=f"Implement: {topic}", owner=owner,
            status="todo", effort="medium", project_path=project_dir,
            development_method="tdd",
            acceptance_criteria=list(criteria),
            test_types=[], out_of_scope=[], definition_of_done=[],
            context=f"Auto-created from discussion {disc_id} (consensus)",
            tdd=None, version=1, created_at=now,
        ))
        print(f"[discussion] auto-task: {task_id}", file=sys.stderr)
    except Exception as e:
        print(f"[discussion] auto-task failed: {e}", file=sys.stderr)


def cmd_check_round(discussion_dir: str, round_: int) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")

        rounds = discussions_dao.get_rounds(conn, disc_id)
        done = []
        pending = []
        # An agent counts as "submitted" if EITHER:
        #   (a) a row exists in discussion_rounds (state-of-record), OR
        #   (b) a round-N-<agent>.yaml file exists in the discussion dir
        #       (the agent wrote its position but never called `shux discuss
        #       submit` — common when an agent crashes after writing the YAML).
        # Counting (b) is what unblocks Bug G: without it, the dispatcher
        # re-enqueues agents who have already done the work.
        for agent in disc.owners:
            submitted = any(r.round_number == round_ and r.agent == agent for r in rounds)
            if not submitted:
                yaml_path = os.path.join(
                    discussion_dir, f"round-{round_}-{agent}.yaml"
                )
                if os.path.isfile(yaml_path):
                    submitted = True
            if submitted:
                done.append(agent)
            else:
                pending.append(agent)

        print(
            json.dumps(
                {
                    "complete": len(pending) == 0,
                    "round": round_,
                    "agents_done": done,
                    "agents_pending": pending,
                },
                separators=(", ", ": "),
            )
        )
    finally:
        conn.close()
    return 0


def cmd_check_consensus(discussion_dir: str) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")

        rounds = discussions_dao.get_rounds(conn, disc_id)
        # Use first round number present or default to 1
        round_nums = sorted({r.round_number for r in rounds})
        current_round = round_nums[-1] if round_nums else 1

        verdicts: dict[str, str] = {}
        for r in rounds:
            if r.round_number == current_round:
                verdicts[r.agent] = str(r.verdict or "").lower()

        all_submitted = len(verdicts) == len(disc.owners)
        consensus = all_submitted and all(v == "agree" for v in verdicts.values())

        print(
            json.dumps(
                {
                    "consensus": consensus,
                    "round": current_round,
                    "verdicts": verdicts,
                    "all_submitted": all_submitted,
                },
                separators=(", ", ": "),
            )
        )
    finally:
        conn.close()
    return 0


def cmd_advance(discussion_dir: str) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)
    now = _now_utc()

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")
        if disc.status != "active":
            sys.exit(f"Discussion is not active (status={disc.status})")

        rounds = discussions_dao.get_rounds(conn, disc_id)
        round_nums = sorted({r.round_number for r in rounds})
        current_round = round_nums[-1] if round_nums else 1

        # Check if all participants submitted current round
        submitted = {r.agent for r in rounds if r.round_number == current_round}
        all_done = all(a in submitted for a in disc.owners)
        if not all_done:
            sys.exit(f"Round {current_round} is not complete yet")

        # Gather verdicts
        verdicts: dict[str, str] = {}
        for r in rounds:
            if r.round_number == current_round:
                verdicts[r.agent] = str(r.verdict or "").lower()
        consensus = all(v == "agree" for v in verdicts.values())

        max_rounds = 3  # default; not stored in discussions table currently
        # Check if discussion_rounds has max_rounds — we can infer from existing design
        # For now, use a reasonable default. In YAML version it was state.get("max_rounds", 3).
        # We don't store max_rounds in SQLite. Using default of 3, but add a fallback
        # by checking if there's a discussion_rounds row with max info.
        try:
            meta = conn.execute(
                "SELECT value FROM discussion_rounds WHERE discussion_id=? AND round_number=-1 AND agent='_meta'",
                (disc_id,),
            ).fetchone()
            if meta:
                max_rounds = int(meta["value"])
        except Exception:
            max_rounds = 3

        if consensus:
            conn.execute(
                "UPDATE discussions SET status='consensus', closed_at=?, consensus=? WHERE id=?",
                (now, f"consensus — all participants agreed round {current_round}", disc_id),
            )
            result = {"action": "closed", "reason": "consensus", "round": current_round}
        elif current_round >= max_rounds:
            conn.execute(
                "UPDATE discussions SET status='no_consensus', closed_at=? WHERE id=?",
                (now, disc_id),
            )
            result = {"action": "closed", "reason": "max_rounds_reached", "round": current_round}
        else:
            # Advance to next round — store as a meta marker
            next_round = current_round + 1
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO discussion_rounds (discussion_id, round_number, agent, created_at) VALUES (?, -2, '_advance', ?)",
                    (disc_id, now),
                )
            except Exception:
                pass
            result = {"action": "advanced", "next_round": next_round}

        conn.commit()
    finally:
        conn.close()

    if result is not None:
        print(json.dumps(result, separators=(", ", ": ")))
    return 0


def cmd_status(discussion_dir: str) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")

        rounds = discussions_dao.get_rounds(conn, disc_id)
        max_round = max((r.round_number for r in rounds if r.round_number > 0), default=1)

        # Detect current round from advance markers
        advances = [r.round_number for r in rounds if r.agent == "_advance"]
        current_round = max_round if advances else 1

        rounds_info = []
        for rn in range(1, current_round + 1):
            submissions = []
            for r in rounds:
                if r.round_number == rn and r.agent != "_advance":
                    submissions.append({
                        "agent": r.agent,
                        "verdict": r.verdict,
                        "submitted_at": r.created_at,
                    })
            rounds_info.append({"round": rn, "submissions": submissions})

        output = {
            "id": disc.id,
            "topic": disc.topic,
            "status": disc.status,
            "participants": disc.owners,
            "current_round": current_round,
            "max_rounds": 3,  # not stored in SQLite yet
            "created_at": disc.created_at,
            "closed_at": disc.closed_at,
            "rounds": rounds_info,
        }
        print(json.dumps(output, separators=(", ", ": ")))
    finally:
        conn.close()
    return 0


def cmd_list(discussions_dir: str) -> int:
    project_dir = discussions_dir.replace("/.superharness/discussions", "")
    from superharness.utils.paths import is_project_initialized
    if not is_project_initialized(project_dir):
        print("[]")
        return 0

    conn = _connect(project_dir)
    try:
        rows = discussions_dao.get_all(conn)
        discussions = []
        for row in rows:
            # Infer current_round from discussion_rounds
            rounds = discussions_dao.get_rounds(conn, row.id)
            round_nums = [r.round_number for r in rounds if r.round_number > 0]
            current_round = max(round_nums) if round_nums else 1

            discussions.append({
                "id": row.id,
                "topic": row.topic,
                "status": row.status,
                "current_round": current_round,
                "max_rounds": 3,
                "participants": row.owners,
                "dir": os.path.join(discussions_dir, row.id),
            })

        print(json.dumps(discussions, separators=(", ", ": ")))
    finally:
        conn.close()
    return 0


def cmd_close(discussion_dir: str, outcome: str, reason: str = "") -> int:
    """Close a discussion and cancel any pending inbox items for it.

    Bug G follow-up (docs/bugs/2026-05-11_discuss_dispatch_bugs.md §8):
    operators need a first-class way to terminate an active discussion
    short of killing the watcher. Setting discussions.status alone is
    not enough — leftover pending/launched inbox items for the rounds
    will still be claimed by the next watcher tick. So this command
    also cancels every matching inbox row in one transaction.
    """
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)
    now = _now_utc()

    cancelled_count = 0
    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")

        discussions_dao.close(conn, disc_id, consensus=None if outcome != "consensus" else "consensus", now=now)
        # Override status if outcome is not a standard close (e.g., cancelled, failed)
        if outcome not in ("consensus",):
            conn.execute(
                "UPDATE discussions SET status=?, closed_at=? WHERE id=?",
                (outcome, now, disc_id),
            )

        # Cancel any pending/launched/paused inbox items for rounds of
        # this discussion. We mark them 'done' (a terminal status the
        # rest of the system already understands) with a failed_reason
        # explaining the supersedence, so the row isn't re-claimed by
        # claim_next and is visible in audit trails.
        cancel_reason = f"discussion closed ({outcome})"
        if reason:
            cancel_reason = f"{cancel_reason}: {reason}"
        cur = conn.execute(
            """
            UPDATE inbox
            SET status = 'done',
                done_at = ?,
                failed_reason = ?
            WHERE task_id LIKE ?
              AND status IN ('pending', 'launched', 'running', 'paused')
            """,
            (now, cancel_reason, f"{disc_id}/round-%"),
        )
        cancelled_count = cur.rowcount or 0
        conn.commit()
    finally:
        conn.close()

    print(json.dumps(
        {"closed": True, "outcome": outcome, "cancelled_inbox_items": cancelled_count},
        separators=(", ", ": "),
    ))
    return 0


def cmd_round_context(discussion_dir: str, round_: int, agent: str) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")

        other_agents = [a for a in disc.owners if a != agent]
        rounds = discussions_dao.get_rounds(conn, disc_id)

        context: dict = {
            "discussion_id": disc.id,
            "topic": disc.topic,
            "round": round_,
            "max_rounds": 3,
            "agent": agent,
            "other_agents": other_agents,
            "prior_rounds": [],
        }

        # Collect prior rounds
        prior_round_nums = sorted({r.round_number for r in rounds if r.round_number > 0 and r.round_number < round_})
        for rn in prior_round_nums:
            positions = []
            for r in rounds:
                if r.round_number == rn:
                    positions.append({
                        "discussion_id": r.discussion_id,
                        "round": r.round_number,
                        "agent": r.agent,
                        "verdict": r.verdict,
                        "position": r.content,
                        "submitted_at": r.created_at,
                    })
            if positions:
                context["prior_rounds"].append({"round": rn, "positions": positions})

        print(json.dumps(context, separators=(", ", ": ")))
    finally:
        conn.close()
    return 0


# ---------------------------------------------------------------------------
# ID generation (kept for backward compat with cmd_start)
# ---------------------------------------------------------------------------

def _generate_id() -> str:
    import random
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"discuss-{ts}-{os.getpid()}-{random.randint(0, 999999999)}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(
            "Usage: discussion <start|submit_round|check_round|check_consensus"
            "|advance|status|list|close|round_context> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = argv[0]
    rest = argv[1:]

    valid = {
        "start", "submit_round", "check_round", "check_consensus",
        "advance", "status", "list", "close", "round_context",
    }
    if cmd not in valid:
        print(
            "Usage: discussion <start|submit_round|check_round|check_consensus"
            "|advance|status|list|close|round_context> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    if cmd == "start":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussions-dir", dest="discussions_dir")
        parser.add_argument("--topic")
        parser.add_argument("--participant", dest="participants", action="append", default=[])
        parser.add_argument("--max-rounds", dest="max_rounds", type=int, default=3)
        parser.add_argument("--task")
        parser.add_argument("--project")
        parser.add_argument("--created-by", dest="created_by", default="owner")
        opts = parser.parse_args(rest)
        if not opts.discussions_dir:
            sys.exit("--discussions-dir is required")
        if not opts.topic:
            sys.exit("--topic is required")
        if len(opts.participants) < 2:
            sys.exit("Need at least 2 --participant flags")
        if not opts.project:
            sys.exit("--project is required")
        sys.exit(
            cmd_start(
                opts.discussions_dir, opts.topic, opts.participants,
                opts.max_rounds, opts.task, opts.project, opts.created_by,
            )
        )

    elif cmd == "submit_round":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--round", dest="round_", type=int)
        parser.add_argument("--agent")
        parser.add_argument("--verdict")
        parser.add_argument("--position")
        parser.add_argument("--points-file", dest="points_file")
        opts = parser.parse_args(rest)
        for attr in ("discussion_dir", "round_", "agent", "verdict", "position"):
            if getattr(opts, attr, None) is None:
                flag = attr.replace("_", "-")
                sys.exit(f"--{flag} is required")
        sys.exit(
            cmd_submit_round(
                opts.discussion_dir, opts.round_, opts.agent,
                opts.verdict, opts.position, opts.points_file,
            )
        )

    elif cmd == "check_round":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--round", dest="round_", type=int)
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        if opts.round_ is None:
            sys.exit("--round is required")
        sys.exit(cmd_check_round(opts.discussion_dir, opts.round_))

    elif cmd == "check_consensus":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_check_consensus(opts.discussion_dir))

    elif cmd == "advance":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_advance(opts.discussion_dir))

    elif cmd == "status":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_status(opts.discussion_dir))

    elif cmd == "list":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussions-dir", dest="discussions_dir")
        opts = parser.parse_args(rest)
        if not opts.discussions_dir:
            sys.exit("--discussions-dir is required")
        sys.exit(cmd_list(opts.discussions_dir))

    elif cmd == "close":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--outcome", default="cancelled")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_close(opts.discussion_dir, opts.outcome))

    elif cmd == "round_context":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--round", dest="round_", type=int)
        parser.add_argument("--agent")
        opts = parser.parse_args(rest)
        for attr in ("discussion_dir", "round_", "agent"):
            if getattr(opts, attr, None) is None:
                flag = attr.replace("_", "-")
                sys.exit(f"--{flag} is required")
        sys.exit(cmd_round_context(opts.discussion_dir, opts.round_, opts.agent))


if __name__ == "__main__":
    main()
