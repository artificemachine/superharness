"""Python port of discussion-dispatch.sh.

Scans active discussions, checks for round completion, advances or closes,
and enqueues next-round inbox items for all participants.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone

_log = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_id_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_engine(args: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion"] + args,
        capture_output=True, text=True, check=False,
    )


def _run_inbox(args: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-m", "superharness.engine.inbox"] + args,
        capture_output=True, text=True, check=False,
    )


def _retry_exhausted(project_dir: str, agent: str, task_key: str) -> bool:
    """Return True if a prior inbox item for (agent, task_key) reached
    its max_retries cap. Used to short-circuit the discussion dispatcher
    so a permanently-failing agent doesn't keep getting re-enqueued
    every poll cycle.

    Best-effort: any DB or schema problem returns False so we never
    block dispatch on a query glitch.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            cursor = conn.execute(
                """
                SELECT retry_count, max_retries, status
                FROM inbox
                WHERE target_agent = ? AND task_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent, task_key),
            )
            row = cursor.fetchone()
            if not row:
                return False
            retry_count = int(row["retry_count"] or 0)
            max_retries = int(row["max_retries"] or 3)
            return retry_count >= max_retries
        finally:
            conn.close()
    except Exception as e:
        _log.warning("discussion_dispatch.py unexpected error: %s", e, exc_info=True)
        return False


def _retry_agent(project_dir: str, agent: str, task_key: str, disc_id: str, round_: int, round_title: str = "") -> bool:
    """Re-queue the last failed inbox row for (agent, task_key) with incremented retry_count.

    Unlike _enqueue_for_agent (which creates a NEW row with retry_count=0),
    this preserves the row identity, failed_reason, and increments retry_count
    so the retry cap actually works. Returns True if retried, False if no
    failed row was found.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = conn.execute(
                "SELECT id, retry_count, max_retries, failed_reason "
                "FROM inbox "
                "WHERE target_agent = ? AND task_id = ? AND status = 'failed' "
                "ORDER BY created_at DESC LIMIT 1",
                (agent, task_key),
            ).fetchone()
            if not row:
                return False
            new_count = int(row["retry_count"] or 0) + 1
            max_retries = int(row["max_retries"] or 3)
            if new_count > max_retries:
                return False
            preserved_reason = row["failed_reason"] or f"retry {new_count}/{max_retries}"
            now = _now_utc()
            inbox_dao.set_retry(conn, row["id"], new_count, preserved_reason, now)
            conn.commit()
            print(f"  Retried round {round_} for {agent}: {row['id']} (attempt {new_count}/{max_retries})")
            return True
        finally:
            conn.close()
    except Exception as e:
        _log.warning("discussion_dispatch.py _retry_agent failed: %s", e)
        return False


def _agent_available(agent: str, project_dir: str) -> tuple[bool, str]:
    """Check if an agent is available for dispatch.

    Returns (available: bool, reason: str).
    Unavailable reasons: binary not installed, rate limited, quota exhausted.
    """
    import shutil

    # 1. Check if the adapter binary is installed
    try:
        from superharness.engine.adapter_registry import load_manifest
        manifest = load_manifest(agent)
        required_bin = (manifest.requires or {}).get("bin")
        if required_bin and manifest.validation.get("check_bin", True):
            if not shutil.which(str(required_bin)):
                return False, f"binary '{required_bin}' not installed"
    except Exception:
        pass  # manifest load failure — don't block on it

    # 2. Check if agent recently hit rate limit or quota exhaustion
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = conn.execute(
                "SELECT failed_reason, created_at FROM inbox "
                "WHERE target_agent = ? AND status = 'failed' "
                "AND failed_reason IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (agent,),
            ).fetchone()
            if row:
                reason = str(row["failed_reason"] or "").lower()
                if "rate limit" in reason or "quota" in reason or "429" in reason:
                    return False, f"recent rate limit: {reason[:80]}"
                if "permanent block" in reason:
                    return False, f"permanent block: {reason[:80]}"

            # 3. Check if agent daemon is alive (recent heartbeat)
            hb = conn.execute(
                "SELECT updated_at, status FROM agent_heartbeats WHERE agent=?",
                (agent,),
            ).fetchone()
            if hb is None or hb["status"] == "zombie":
                return False, f"no daemon heartbeat (agent not running)"
        finally:
            conn.close()
    except Exception:
        pass

    return True, ""


def _recover_orphaned_dispatches(project_dir: str) -> None:
    """Mark stuck inbox items (launched/running with no heartbeat) as failed.

    When the watcher dies mid-dispatch, the agent process may keep running
    but the inbox item stays 'launched' forever with no PID tracking.
    This creates invisible failures — the agent never submits and the
    dispatcher never retries because there's no 'failed' row to retry.

    This function finds stuck inbox items (status IN ('launched','running'),
    last_heartbeat IS NULL or > timeout_ago) and marks them as failed so
    the normal retry mechanism picks them up on the next poll cycle.
    """
    import sqlite3
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            now = _now_utc()
            # Stuck = launched/running, no heartbeat in 15+ minutes
            stuck = conn.execute(
                """
                SELECT id, task_id, target_agent, status, launched_at, last_heartbeat
                FROM inbox
                WHERE status IN ('launched', 'running')
                  AND (last_heartbeat IS NULL
                       OR last_heartbeat < datetime('now', '-15 minutes'))
                """
            ).fetchall()
            for row in stuck:
                conn.execute(
                    "UPDATE inbox SET status = 'failed', failed_reason = ?, failed_at = ? WHERE id = ?",
                    ("orphaned_dispatch (watcher restart, no heartbeat)", now, row["id"]),
                )
                _log.warning(
                    "discussion_dispatch: orphaned inbox item %s (agent=%s task=%s) marked failed",
                    row["id"], row["target_agent"], row["task_id"],
                )
            if stuck:
                conn.commit()
                print(f"  Recovered {len(stuck)} orphaned dispatch(es)")
        finally:
            conn.close()
    except Exception as e:
        _log.warning("discussion_dispatch.py orphan recovery error: %s", e, exc_info=True)


def _ensure_round_task(project_dir: str, disc_id: str, round_: int, title: str) -> None:
    """Create the round task row in tasks if it doesn't already exist.

    inbox.task_id is a FK reference to tasks.id — enqueue fails with
    IntegrityError if the task row is absent. This happens on every
    round advance because only round-1 is seeded at discussion-start time.

    Copies model_tier and effort from round-1 so classification done at
    discussion creation carries through to all subsequent rounds.
    """
    from superharness.engine.db import get_connection, init_db
    task_id = f"{disc_id}/round-{round_}"
    # Read model_tier and effort from round-1 to propagate to later rounds
    model_tier = "standard"
    effort = "medium"
    if round_ > 1:
        round_1_id = f"{disc_id}/round-1"
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = conn.execute(
                "SELECT model_tier, effort FROM tasks WHERE id = ?",
                (round_1_id,),
            ).fetchone()
            if row:
                model_tier = row["model_tier"] or "standard"
                effort = row["effort"] or "medium"
        finally:
            conn.close()

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO tasks
                (id, title, owner, status, project_path, created_at, updated_at, workflow, model_tier, effort)
            VALUES (?, ?, 'claude-code', 'in_progress', ?, ?, ?, 'discussion', ?, ?)
            """,
            (task_id, title, project_dir, _now_utc(), _now_utc(), model_tier, effort),
        )
        conn.commit()
    finally:
        conn.close()


def _enqueue_for_agent(
    inbox_file: str,
    disc_id: str,
    round_: int,
    agent: str,
    project_dir: str,
    round_title: str = "",
) -> None:
    _ensure_round_task(project_dir, disc_id, round_, round_title or f"Discussion round {round_}: {disc_id}")
    item_id = f"{_now_id_ts()}-{disc_id}-r{round_}-{agent}-{os.getpid()}-{secrets.token_hex(3)}"
    rc = _run_inbox([
        "enqueue",
        "--file", inbox_file,
        "--id", item_id,
        "--to", agent,
        "--task", f"{disc_id}/round-{round_}",
        "--project", project_dir,
        "--priority", "1",
        "--created-at", _now_utc(),
    ])
    if rc.returncode == 0:
        print(f"  Enqueued round {round_} for {agent}: {item_id}")
    else:
        _log.warning("Failed to enqueue %s round %d for %s: %s", disc_id, round_, agent, rc.stderr)


def dispatch(project_dir: str) -> int:
    """Scan active discussions from SQLite and dispatch round completions."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    discussions_dir = os.path.join(project_dir, ".superharness", "discussions")
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")

    # Recover orphaned dispatches before scanning discussions.
    # If the watcher died mid-dispatch, the inbox item stays "launched"
    # forever and the dispatcher never retries. Mark them as failed here
    # so the normal retry flow kicks in on the next poll cycle.
    _recover_orphaned_dispatches(project_dir)

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        active = discussions_dao.get_all(conn, status="active")
    finally:
        conn.close()

    for disc in active:
        disc_id = disc.id
        discussion_dir = os.path.join(discussions_dir, disc_id)

        # Get status
        status_result = _run_engine(["status", "--discussion-dir", discussion_dir])
        if status_result.returncode != 0:
            continue
        try:
            status_json = json.loads(status_result.stdout)
        except json.JSONDecodeError:
            continue

        if status_json.get("status") != "active":
            continue

        current_round = int(status_json.get("current_round", 1))
        participants = status_json.get("participants") or []
        topic = status_json.get("topic") or disc_id
        created_at = status_json.get("created_at") or ""

        # Effort-based deadline: auto-close discussions that outlive their
        # classified effort budget. Prevents orphaned discussions that hang
        # forever when agents go silent. Deadline matches the timeout caps:
        # low=10min, medium=20min, high=30min. Unknown effort → 20min.
        if created_at:
            try:
                from superharness.engine import tasks_dao
                round_1_id = f"{disc_id}/round-1"
                conn2 = get_connection(project_dir)
                try:
                    init_db(conn2)
                    task = tasks_dao.get(conn2, round_1_id)
                    effort = (task.effort if task and task.effort else "medium")
                finally:
                    conn2.close()

                deadline_minutes = {"low": 10, "medium": 20, "high": 30}.get(effort, 20)
                from datetime import datetime, timezone, timedelta
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                deadline_dt = created_dt + timedelta(minutes=deadline_minutes)
                now = datetime.now(timezone.utc)

                if now > deadline_dt:
                    print(
                        f"Discussion {disc_id}: deadline exceeded "
                        f"(effort={effort}, {deadline_minutes}min, "
                        f"created={created_at}) — auto-closing"
                    )
                    _run_engine([
                        "close", "--discussion-dir", discussion_dir,
                        "--reason", f"deadline_exceeded ({deadline_minutes}min, effort={effort})",
                    ])
                    continue
            except Exception as e:
                _log.warning("discussion_dispatch.py deadline check error: %s", e, exc_info=True)

        # Check if current round is complete
        check_result = _run_engine([
            "check_round",
            "--discussion-dir", discussion_dir,
            "--round", str(current_round),
        ])
        if check_result.returncode != 0:
            continue
        try:
            check_json = json.loads(check_result.stdout)
        except json.JSONDecodeError:
            continue

        if check_json.get("complete"):
            # Advance: close with consensus/no_consensus or bump to next round
            advance_result = _run_engine(["advance", "--discussion-dir", discussion_dir])
            if advance_result.returncode != 0:
                continue
            try:
                advance_json = json.loads(advance_result.stdout)
            except json.JSONDecodeError:
                continue

            action = advance_json.get("action")
            if action == "advanced":
                next_round = int(advance_json.get("next_round", current_round + 1))
                print(f"Discussion {disc_id}: advanced to round {next_round}")
                round_title = f"Discussion round {next_round}: {topic}"
                for agent in participants:
                    _enqueue_for_agent(inbox_file, disc_id, next_round, agent, project_dir, round_title)

            elif action == "closed":
                reason = advance_json.get("reason", "unknown")
                round_closed = advance_json.get("round", current_round)
                print(f"Discussion {disc_id}: closed (reason={reason}, round={round_closed})")

        else:
            # Round not complete — re-enqueue only agents who have no
            # in-flight inbox item AND no submission file AND who have
            # not exhausted retries. Without this defense, every poll
            # cycle that sees agents_pending re-enqueues them, which
            # turns transient failures into a re-dispatch storm
            # (Bug G in docs/bugs/2026-05-11_discuss_dispatch_bugs.md).
            agents_pending = check_json.get("agents_pending") or []
            for agent in agents_pending:
                task_key = f"{disc_id}/round-{current_round}"

                # Belt-and-braces: even if check_round didn't see the
                # YAML on disk (race window between agent write and
                # this poll), skip if it exists now. cmd_check_round
                # already does this; this is a defense-in-depth guard.
                yaml_path = os.path.join(
                    discussion_dir, f"round-{current_round}-{agent}.yaml"
                )
                if os.path.isfile(yaml_path):
                    continue

                # Defense-in-depth: also check the discussion_rounds table.
                # cmd_check_round uses is_submitted() which covers this, but
                # if the discussion_dir is wrong or the round number mismatches,
                # we still catch already-submitted agents here.
                try:
                    from superharness.engine import discussions_dao as _ddao
                    if _ddao.is_submitted(conn, disc_id, current_round, agent):
                        continue
                except Exception:
                    pass  # don't block on DAO failure

                has_result = _run_inbox([
                    "has_active",
                    "--file", inbox_file,
                    "--to", agent,
                    "--task", task_key,
                ])
                already_active = has_result.returncode == 0 and has_result.stdout.strip() == "true"
                if already_active:
                    continue

                # Check if the agent is actually available (binary installed, not rate-limited)
                available, reason = _agent_available(agent, project_dir)
                if not available:
                    print(
                        f"  Skipping {agent} for round {current_round}: "
                        f"agent unavailable ({reason})"
                    )
                    continue

                # Honour the per-(discussion, round, agent) retry cap.
                # If a prior inbox item for this task_key reached its
                # max_retries threshold, treat the agent as a failed
                # participant and stop re-enqueuing. Without this, the
                # dispatcher would re-launch the agent every poll
                # cycle, costing real money on metered APIs.
                if _retry_exhausted(project_dir, agent, task_key):
                    print(
                        f"  Skipping {agent} for round {current_round}: "
                        f"retry budget exhausted for {task_key}"
                    )
                    continue

                # Re-queue existing failed row (preserves retry_count + failed_reason).
                # Falls back to creating a new row if no failed row exists (first launch).
                if not _retry_agent(project_dir, agent, task_key, disc_id, current_round,
                                    f"Discussion round {current_round}: {topic}"):
                    _enqueue_for_agent(inbox_file, disc_id, current_round, agent, project_dir,
                                       f"Discussion round {current_round}: {topic}")

    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="discussion_dispatch",
        description="Advance active discussions and enqueue next-round inbox items",
        add_help=True,
    )
    parser.add_argument("--project", "-p", required=True)

    opts = parser.parse_args(argv)
    project_dir = os.path.realpath(opts.project)

    if not os.path.isdir(project_dir):
        print(f"Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    rc = dispatch(project_dir)
    sys.exit(rc)


if __name__ == "__main__":
    main()
