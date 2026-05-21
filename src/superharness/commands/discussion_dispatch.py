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


def _ensure_round_task(project_dir: str, disc_id: str, round_: int, title: str) -> None:
    """Create the round task row in tasks if it doesn't already exist.

    inbox.task_id is a FK reference to tasks.id — enqueue fails with
    IntegrityError if the task row is absent. This happens on every
    round advance because only round-1 is seeded at discussion-start time.
    """
    from superharness.engine.db import get_connection, init_db
    task_id = f"{disc_id}/round-{round_}"
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO tasks
                (id, title, owner, status, project_path, created_at, updated_at, workflow)
            VALUES (?, ?, 'claude-code', 'in_progress', ?, ?, ?, 'discussion')
            """,
            (task_id, title, project_dir, _now_utc(), _now_utc()),
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

                has_result = _run_inbox([
                    "has_active",
                    "--file", inbox_file,
                    "--to", agent,
                    "--task", task_key,
                ])
                already_active = has_result.returncode == 0 and has_result.stdout.strip() == "true"
                if already_active:
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
