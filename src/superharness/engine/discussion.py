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

import logging
logger = logging.getLogger(__name__)


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

        # Normalize verdict: agents sometimes copy the prompt's example verbatim
        # ("agree or disagree or partial") instead of picking one.
        # Only normalize when ALL options appear — a real "disagree or partial"
        # is ambiguous and should be rejected.
        valid_verdicts = {"agree", "disagree", "partial", "consensus", "abstain"}
        verdict_lower = str(verdict).strip().lower()
        if verdict_lower not in valid_verdicts:
            import re
            matches = [v for v in sorted(valid_verdicts) if re.search(r'\b' + re.escape(v) + r'\b', verdict_lower)]
            if len(matches) >= 3:
                # All three main options present → copied the prompt. Take first match.
                verdict_lower = matches[0]
                print(f"[discussion] normalized verdict '{verdict}' → '{verdict_lower}' (prompt copy)", file=sys.stderr)
            else:
                sys.exit(f"Invalid verdict '{verdict}'. Must be one of: {', '.join(sorted(valid_verdicts))}")
        verdict = verdict_lower

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
            except Exception as e:
                logger.warning("discussion.py unexpected error: %s", e, exc_info=True)
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

    # Only AI agents (those with registered adapters) are expected to submit
    # automatically. Human participants like "owner" are never dispatched via
    # inbox and must not block auto-consensus.
    try:
        from superharness.engine.adapter_registry import list_adapters
        ai_agents = set(list_adapters())
    except Exception as e:
        logger.warning("discussion.py unexpected error: %s", e, exc_info=True)
        ai_agents = set()
    agent_participants = [o for o in disc.owners if o in ai_agents] if ai_agents else list(disc.owners)
    total_participants = len(agent_participants) if agent_participants else len(disc.owners)
    # n=1 or n=2: all must submit; n≥3: n-1 suffices (one dissenter tolerated).
    required_count = total_participants if total_participants <= 2 else total_participants - 1

    if len(submitted_agents) < required_count:
        return

    # Auto-consensus requires every participant to not disagree.
    # "partial" still means "not fully convinced" — advance to next round.
    # "abstain" means "no objection" and closes the round via consensus.
    verdicts = [(r.verdict or "").lower() for r in rounds if r.round_number == round_]
    if not all(v in {"agree", "consensus", "abstain"} for v in verdicts):
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

        # Initialise shared variables before any loop that references them
        topic = str(disc.topic)[:80]
        now = _now_utc()
        project_dir = "/"  # fallback
        try:
            db_path = conn.execute("PRAGMA database_list").fetchone()
            if db_path:
                project_dir = os.path.dirname(os.path.dirname(db_path["file"]))
        except Exception as e:
            logger.warning("discussion.py unexpected error: %s", e, exc_info=True)
            pass

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

        # Extract individual action items from round submissions.
        # Each agent's non-agree verdict becomes a separate task with
        # the agent's content as the acceptance criteria.
        created = 0
        for r in rounds:
            if r.round_number != round_ or not r.verdict:
                continue
            v = r.verdict.lower()
            if v == "agree":
                continue
            # Create a task per non-agree verdict
            action_id = f"action-{disc_id[:20]}-{r.agent}-{round_}"
            action_criteria = [f"From {r.agent} (verdict: {v})"]
            if r.content:
                action_criteria.append(r.content[:200])
            tasks_dao.upsert(conn, TaskRow(
                id=action_id, title=f"[{v}] {topic[:60]}", owner=r.agent,
                status="plan_proposed", effort="medium", project_path=project_dir,
                development_method="tdd",
                acceptance_criteria=action_criteria,
                test_types=[], out_of_scope=[], definition_of_done=[],
                context=f"Auto-extracted from discussion {disc_id} round {round_} ({r.agent})",
                tdd=None, version=1, created_at=now,
            ))
            created += 1

        # Also create a summary task that collects all points
        criteria = [f"Implement consensus from {disc_id}"]
        for p in all_points:
            criteria.append(f"  * {p['id']} [{p['verdict']}]")
        owner = disc.owners[0] if disc.owners else "claude-code"
        tasks_dao.upsert(conn, TaskRow(
            id=task_id, title=f"Implement: {topic}", owner=owner,
            status="todo", effort="medium", project_path=project_dir,
            development_method="tdd",
            acceptance_criteria=list(criteria),
            test_types=[], out_of_scope=[], definition_of_done=[],
            context=f"Auto-created from discussion {disc_id} (consensus) — {created} actions extracted",
            tdd=None, version=1, created_at=now,
        ))
        print(f"[discussion] auto-task: {task_id} (plan_approved)", file=sys.stderr)

        # Auto-dispatch through orchestrator — use fallback to avoid blocking on Claude CLI.
        try:
            from superharness.engine.orchestrator import Orchestrator
            orch = Orchestrator(project_dir=project_dir)
            task_data = {
                "id": task_id,
                "title": f"Implement: {topic}",
                "owner": owner,
                "acceptance_criteria": list(criteria),
            }
            # Use fallback routing (no network call) — the task will be properly
            # routed when it's dispatched through the normal delegate pipeline.
            routing = orch._fallback_routing(task_data)
            print(f"[discussion] orchestrator: {task_id} → {routing.owner}/{routing.tier}", file=sys.stderr)
        except Exception as route_err:
            print(f"[discussion] orchestrator skipped: {route_err}", file=sys.stderr)
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

        done = []
        pending = []
        for agent in disc.owners:
            if discussions_dao.is_submitted(conn, disc_id, round_, agent, discussion_dir):
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
        round_nums = sorted({r.round_number for r in rounds})
        current_round = round_nums[-1] if round_nums else 1

        # Collect verdicts from DB submissions
        verdicts: dict[str, str] = {}
        for r in rounds:
            if r.round_number == current_round:
                verdicts[r.agent] = str(r.verdict or "").lower()

        # Also scan disk for YAML files — agents may write files without calling
        # cmd_submit_round(). If a round-N-agent.yaml exists, treat it as submitted.
        for agent in disc.owners:
            if agent not in verdicts:
                yaml_path = os.path.join(discussion_dir, f"round-{current_round}-{agent}.yaml")
                if os.path.isfile(yaml_path):
                    verdicts[agent] = "file_on_disk"

        # Require max(2, n-1) submissions — same formula as discuss.py
        total = len(disc.owners)
        required = max(2, total - 1) if total > 1 else 2
        all_submitted = len(verdicts) >= required
        consensus = all_submitted and "disagree" not in {v for v in verdicts.values() if v not in ("file_on_disk",)}

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


def _reconcile_yaml_submissions(
    conn, disc, discussion_dir: str, round_: int
) -> list[str]:
    """Register on-disk YAML submissions that are absent from SQLite.

    Safety net called by cmd_advance before the completion check. The watcher's
    _auto_advance_orphaned_rounds() proactively registers YAML submissions on
    every poll cycle; this is a last-resort fallback for the window between an
    agent writing its YAML and the watcher running.

    Returns the list of agents whose submissions were recovered.
    """
    now = _now_utc()
    return [
        agent for agent in disc.owners
        if discussions_dao.register_yaml_submission(
            conn, disc.id, round_, agent, discussion_dir, now
        )
    ]


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
        # Advance markers store next_round as a positive round_number (Bug O fix).
        # Use them as the authoritative current_round so cmd_advance agrees with
        # cmd_status when an advance has already happened (e.g. round 1→2 marker
        # exists but round-2 submissions are YAML-only and not yet in SQLite).
        advance_markers = {r.round_number for r in rounds if r.agent == "_advance" and r.round_number > 0}
        submission_round_nums = sorted({r.round_number for r in rounds if r.agent != "_advance" and r.round_number > 0})
        if advance_markers:
            current_round = max(advance_markers)
        elif submission_round_nums:
            current_round = submission_round_nums[-1]
        else:
            current_round = 1

        # Reconcile any YAML-only submissions into SQLite before checking
        # completion. Without this, check_round returns complete=true (it
        # accepts YAML files as proof) but advance would exit "not complete"
        # (SQLite-only check), permanently sticking the discussion.
        _reconcile_yaml_submissions(conn, disc, discussion_dir, current_round)
        # Reload rounds after reconciliation so the completion check and
        # verdict gathering both see the newly-inserted rows.
        rounds = discussions_dao.get_rounds(conn, disc_id)

        # Check if all participants submitted current round
        submitted = {r.agent for r in rounds if r.round_number == current_round and r.agent != "_advance"}
        all_done = all(a in submitted for a in disc.owners)

        if not all_done:
            # If the advance marker already points to current_round but agents
            # haven't submitted yet, the previous advance already happened and
            # we're just waiting for new submissions — return idempotently.
            if current_round in advance_markers:
                result = {"action": "advanced", "next_round": current_round}
            else:
                sys.exit(f"Round {current_round} is not complete yet")
        else:
            # Gather verdicts
            verdicts: dict[str, str] = {}
            for r in rounds:
                if r.round_number == current_round and r.agent != "_advance":
                    verdicts[r.agent] = str(r.verdict or "").lower()
            consensus = all(v == "agree" for v in verdicts.values())

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
                next_round = current_round + 1
                # Idempotent: only insert the advance marker if not already present
                if next_round not in advance_markers:
                    conn.execute(
                        "INSERT INTO discussion_rounds (discussion_id, round_number, agent, content, verdict, created_at) VALUES (?, ?, '_advance', NULL, NULL, ?)",
                        (disc_id, next_round, now),
                    )
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
        max_round = max((r.round_number for r in rounds if r.round_number > 0 and r.agent != "_advance"), default=1)

        # Advance markers store next_round as a positive round_number (Bug O fix).
        # Negative sentinel (-2) markers from older code are ignored here.
        positive_advance_markers = [r.round_number for r in rounds if r.agent == "_advance" and r.round_number > 0]
        current_round = max(positive_advance_markers) if positive_advance_markers else max_round

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
            adv = [r.round_number for r in rounds if r.agent == "_advance" and r.round_number > 0]
            sub = [r.round_number for r in rounds if r.agent != "_advance" and r.round_number > 0]
            current_round = max(adv) if adv else (max(sub) if sub else 1)

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
