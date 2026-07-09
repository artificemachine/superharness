"""Python port of engine/discussion.rb — multi-round discussion engine.
v2: SQLite-only (post-YAML removal). All state lives in discussions + discussion_rounds tables.
"""
from __future__ import annotations

import json
import os
import re
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
            task_id=task_id, max_rounds=max_rounds, now=now,
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
        # Reject submissions with all options present — we cannot disambiguate
        # the agent's intent, and guessing produces misleading consensus.
        # (Fix: BUGREPORT-discussion-consensus-single-participant, root cause #4.)
        valid_verdicts = {"agree", "disagree", "partial", "consensus", "abstain"}
        verdict_lower = str(verdict).strip().lower()
        if verdict_lower not in valid_verdicts:
            import re
            matches = [v for v in sorted(valid_verdicts) if re.search(r'\b' + re.escape(v) + r'\b', verdict_lower)]
            if len(matches) >= 3:
                # All three main options present → copied the prompt verbatim.
                sys.exit(
                    f"Rejected prompt-copy verdict '{verdict}'. "
                    f"Please pick ONE of: {', '.join(sorted(valid_verdicts))}"
                )
            else:
                sys.exit(f"Invalid verdict '{verdict}'. Must be one of: {', '.join(sorted(valid_verdicts))}")
        verdict = verdict_lower

        # Check if already submitted this round
        existing = discussions_dao.get_rounds(conn, disc_id)
        for r in existing:
            if r.round_number == round_ and r.agent == agent:
                sys.exit(f"Round {round_} already submitted by {agent}")

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
        _check_all_submitted_and_set_consensus(conn, disc, round_, project_dir=project_dir)

        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"submitted": True, "round": round_, "agent": agent, "verdict": verdict}, separators=(", ", ": ")))
    return 0


_CONSENSUS_VERDICTS = frozenset({"agree", "consensus", "abstain"})


def compute_consensus(verdicts: dict[str, str], participants: list[str]) -> bool:
    """Return True when the submitted verdicts constitute a quorum consensus.

    Quorum rule: n≤2 requires all participants; n≥3 tolerates one abstaining
    participant (n-1 suffices).  Any 'disagree' or 'partial' verdict blocks.
    """
    n = len(participants)
    required = n if n <= 2 else n - 1
    submitted = {a: v.lower() for a, v in verdicts.items() if a in participants}
    if len(submitted) < required:
        return False
    return all(v in _CONSENSUS_VERDICTS for v in submitted.values())


def _check_all_submitted_and_set_consensus(conn, disc, round_: int, project_dir: str = "/") -> None:
    """If all participants submitted this round AND all verdicts agree,
    auto-transition the discussion to consensus. If any participant
    disagrees we leave status=active so the dispatcher can advance to
    the next round."""
    rounds = discussions_dao.get_rounds(conn, disc.id)

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

    verdicts_by_agent = {r.agent: (r.verdict or "").lower() for r in rounds if r.round_number == round_}
    if not compute_consensus(verdicts_by_agent, agent_participants):
        return

    submitted_agents = {a for a in verdicts_by_agent if a in agent_participants}
    conn.execute(
        "UPDATE discussions SET status='consensus', consensus=? WHERE id=?",
        (f"consensus — all {len(submitted_agents)} participants submitted round {round_}", disc.id),
    )
    print(
        f"[discussion] auto-consensus: all {len(submitted_agents)} participants submitted round {round_} → consensus",
        file=sys.stderr,
    )

    # Auto-create contract task from consensus points
    _create_consensus_task(conn, disc, round_, submitted_agents, project_dir=project_dir)


def _create_consensus_task(
    conn, disc, round_: int, submitted_agents: set[str], project_dir: str = "/"
) -> None:
    """Auto-create a contract task from discussion points that block consensus."""
    try:
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow

        disc_id = disc.id
        task_id = f"impl-{disc_id[:30]}"

        # Initialise shared variables before any loop that references them
        topic = str(disc.topic)[:80]
        now = _now_utc()

        # Collect points from round submissions. This gate governs whether the
        # `impl-*` summary task is created at all; a unanimous 'agree' round
        # produces no follow-up work.
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
        #
        # Only a verdict that *blocks* consensus is an action item. 'abstain'
        # and 'consensus' permit a close exactly as 'agree' does, so a bare
        # `== "agree"` skip fabricated `[abstain]`/`[consensus]` implementation
        # tasks for agents who had agreed or explicitly declined to weigh in.
        created = 0
        for r in rounds:
            if r.round_number != round_ or not r.verdict:
                continue
            v = r.verdict.lower()
            if v in _CONSENSUS_VERDICTS:
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

        # file_on_disk entries are placeholders; exclude from verdict check
        db_verdicts = {k: v for k, v in verdicts.items() if v != "file_on_disk"}
        consensus = compute_consensus(db_verdicts, disc.owners)
        all_submitted = consensus or len(verdicts) >= (
            len(disc.owners) if len(disc.owners) <= 2 else len(disc.owners) - 1
        )

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
            consensus = compute_consensus(verdicts, disc.owners)

            max_rounds = disc.max_rounds

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


def _max_round_on_disk(discussion_dir: str) -> int:
    """Highest round number with a `round-N-<agent>.yaml` file present.

    An agent that outlived its discussion may have written a round the DB never
    recorded, so the round count cannot be derived from SQLite alone.
    """
    # `round-N-<agent>.yaml` are the agents' two-phase submission artifacts, not
    # state-of-record: the harness is responsible for registering them INTO
    # SQLite (discussions_dao.register_yaml_submission already reads these same
    # files). Discovering which rounds exist on disk is the first half of that
    # contract. SQLite remains the source of truth.
    highest = 0
    try:
        for name in os.listdir(discussion_dir):  # noqa: state-read — agent submission artifacts, registered into SQLite below
            m = re.match(r"^round-(\d+)-.+\.yaml$", name)
            if m:
                highest = max(highest, int(m.group(1)))
    except OSError:
        pass
    return highest


def _reconcile_orphaned_submissions(conn, disc, discussion_dir: str, through_round: int) -> None:
    """Register on-disk submissions that SQLite never recorded.

    `cmd_close` cancels a discussion's inbox rows but does not signal the agent
    processes already launched for it. Those agents run to completion and write
    `round-N-<agent>.yaml`. Neither caller of `register_yaml_submission` can pick
    them up afterwards: `_reconcile_yaml_submissions` runs only from
    `cmd_advance`, and the watcher's reconciler filters `status="active"` —
    which closing is precisely what stops. The files were reachable only by
    listing the directory.

    Registration is idempotent, skips corrupt YAML, and never touches
    `discussions.status`, so a closed discussion stays closed.
    """
    now = _now_utc()
    for round_ in range(1, through_round + 1):
        for agent in disc.owners:
            discussions_dao.register_yaml_submission(
                conn, disc.id, round_, agent, discussion_dir, now
            )
    conn.commit()


def cmd_status(discussion_dir: str) -> int:
    project_dir = _get_project_dir(discussion_dir)
    disc_id = _get_disc_id(discussion_dir)

    conn = _connect(project_dir)
    try:
        disc = discussions_dao.get(conn, disc_id)
        if not disc:
            sys.exit(f"Discussion not found: {disc_id}")

        # Surface agent output written to disk but never registered — otherwise
        # a round with completed submissions renders as "(no submissions yet)".
        _known = max(
            (r.round_number for r in discussions_dao.get_rounds(conn, disc_id)
             if r.round_number > 0),
            default=1,
        )
        _reconcile_orphaned_submissions(
            conn, disc, discussion_dir,
            max(_known, _max_round_on_disk(discussion_dir)),
        )

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

        # Cancel ALL inbox items for rounds of this discussion — not just
        # pending/launched. dispatched and failed items also need cleanup
        # to prevent stale re-dispatch storms when the discussion is restarted.
        # (Fix: stale inbox leak from discuss close → start cycle)
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
              AND status IN ('pending', 'launched', 'running', 'paused',
                             'dispatched', 'failed')
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
        opts = parser.parse_args(rest)
        for attr in ("discussion_dir", "round_", "agent", "verdict", "position"):
            if getattr(opts, attr, None) is None:
                flag = attr.replace("_", "-")
                sys.exit(f"--{flag} is required")
        sys.exit(
            cmd_submit_round(
                opts.discussion_dir, opts.round_, opts.agent,
                opts.verdict, opts.position,
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
