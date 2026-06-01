from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscussionRow:
    id: str
    task_id: str | None
    topic: str
    owners: list[str]
    status: str
    consensus: str | None
    created_at: str
    closed_at: str | None


@dataclass(frozen=True)
class DiscussionRoundRow:
    id: int
    discussion_id: str
    round_number: int
    agent: str
    content: str | None
    verdict: str | None
    created_at: str


def create(
    conn: sqlite3.Connection,
    *,
    id: str,
    topic: str,
    owners: list[str],
    task_id: str | None = None,
    now: str,
) -> DiscussionRow:
    # If a task_id is provided but the row doesn't exist, treat the FK as
    # SET NULL upfront — tasks() may be created later (or may live only in
    # YAML before migration). The FK is intentionally nullable.
    if task_id:
        exists = conn.execute(
            "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not exists:
            task_id = None
    try:
        conn.execute(
            """
            INSERT INTO discussions (id, task_id, topic, owners, status, created_at)
            VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (id, task_id, topic, json.dumps(owners), now),
        )
        row = conn.execute("SELECT * FROM discussions WHERE id = ?", (id,)).fetchone()
        return _row_to_discussion(row)
    except sqlite3.IntegrityError as e:
        raise StateError(f"Discussion '{id}' already exists: {e}") from e
    except sqlite3.Error as e:
        raise StateError(f"Failed to create discussion '{id}': {e}") from e


def get(conn: sqlite3.Connection, id: str) -> DiscussionRow | None:
    row = conn.execute("SELECT * FROM discussions WHERE id = ?", (id,)).fetchone()
    return _row_to_discussion(row) if row else None


def get_all(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    task_id: str | None = None,
) -> list[DiscussionRow]:
    query = "SELECT * FROM discussions WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    query += " ORDER BY created_at DESC"
    return [_row_to_discussion(r) for r in conn.execute(query, params).fetchall()]


def close(
    conn: sqlite3.Connection,
    id: str,
    *,
    consensus: str | None,
    now: str,
) -> bool:
    cursor = conn.execute(
        "UPDATE discussions SET status='closed', consensus=?, closed_at=? WHERE id=? AND status IN ('active', 'consensus')",
        (consensus, now, id),
    )
    return cursor.rowcount > 0


def add_round(
    conn: sqlite3.Connection,
    *,
    discussion_id: str,
    round_number: int,
    agent: str,
    content: str | None = None,
    verdict: str | None = None,
    now: str,
) -> DiscussionRoundRow:
    try:
        cursor = conn.execute(
            """
            INSERT INTO discussion_rounds (discussion_id, round_number, agent, content, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (discussion_id, round_number, agent, content, verdict, now),
        )
        row = conn.execute(
            "SELECT * FROM discussion_rounds WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_round(row)
    except sqlite3.Error as e:
        raise StateError(f"Failed to add round to discussion '{discussion_id}': {e}") from e


def get_rounds(conn: sqlite3.Connection, discussion_id: str) -> list[DiscussionRoundRow]:
    rows = conn.execute(
        "SELECT * FROM discussion_rounds WHERE discussion_id = ? ORDER BY round_number, created_at",
        (discussion_id,),
    ).fetchall()
    return [_row_to_round(r) for r in rows]


def is_submitted(
    conn: sqlite3.Connection,
    disc_id: str,
    round_: int,
    agent: str,
    discussion_dir: str | None = None,
) -> bool:
    """Return True if agent has submitted for this round.

    A submission is proven by EITHER a discussion_rounds DB row (authoritative)
    OR a round-N-agent.yaml file on disk (evidence-of-work fallback, used when
    the agent wrote its position but the DB write never completed).

    Pass discussion_dir to enable the YAML fallback. Omit it for a DB-only check.
    """
    rows = get_rounds(conn, disc_id)
    if any(r.round_number == round_ and r.agent == agent for r in rows):
        return True
    if discussion_dir is not None:
        yaml_path = os.path.join(discussion_dir, f"round-{round_}-{agent}.yaml")
        return os.path.isfile(yaml_path)
    return False


def register_yaml_submission(
    conn: sqlite3.Connection,
    disc_id: str,
    round_: int,
    agent: str,
    discussion_dir: str,
    now: str,
) -> bool:
    """Parse round-N-agent.yaml and insert a discussion_rounds row if absent.

    This is the harness-side half of the two-phase submission: agents write
    the YAML, the harness is responsible for getting it into SQLite. Callers
    should commit after this returns True.

    Returns True if a new row was inserted, False if the row already existed
    or no YAML file was found. Silently skips on corrupt YAML.
    """
    rows = get_rounds(conn, disc_id)
    if any(r.round_number == round_ and r.agent == agent for r in rows):
        return False

    yaml_path = os.path.join(discussion_dir, f"round-{round_}-{agent}.yaml")
    if not os.path.isfile(yaml_path):
        return False

    try:
        try:
            from superharness.engine.yaml_helpers import safe_load
            data = safe_load(yaml_path)
        except Exception:
            import yaml as _yaml
            with open(yaml_path) as _f:
                data = _yaml.safe_load(_f)
        if not isinstance(data, dict):
            return False
        verdict = str(data.get("verdict") or "").lower()
        # Normalize prompt-copy verdicts: agents sometimes copy the full prompt
        # text ("agree or disagree or partial") instead of picking one value.
        # Reject submissions that are clearly unparsed prompt text.
        # (Fix: BUGREPORT-discussion-consensus-single-participant, root cause #4.)
        valid_verdicts = {"agree", "disagree", "partial", "consensus", "abstain"}
        if verdict not in valid_verdicts:
            import re as _vre
            matches = [v for v in sorted(valid_verdicts) if _vre.search(r'\b' + _vre.escape(v) + r'\b', verdict)]
            if len(matches) >= 3:
                # All three main options present → copied the prompt verbatim.
                # Reject instead of silently normalizing — we don't know which
                # position the agent actually intended.
                _log.warning(
                    "register_yaml_submission: disc=%s round=%d agent=%s — "
                    "rejected prompt-copy verdict '%s' (all options present, "
                    "cannot disambiguate)",
                    disc_id, round_, agent, verdict,
                )
                return False
            elif len(matches) == 0:
                # No valid verdict found in string — reject.
                _log.warning(
                    "register_yaml_submission: disc=%s round=%d agent=%s — "
                    "rejected invalid verdict '%s'",
                    disc_id, round_, agent, verdict,
                )
                return False
            else:
                # Ambiguous partial match → reject rather than guess.
                _log.warning(
                    "register_yaml_submission: disc=%s round=%d agent=%s — "
                    "rejected ambiguous verdict '%s' (matches: %s)",
                    disc_id, round_, agent, verdict, matches,
                )
                return False
        position = str(data.get("position") or "")
        add_round(
            conn,
            discussion_id=disc_id,
            round_number=round_,
            agent=agent,
            content=position,
            verdict=verdict,
            now=now,
        )
        _log.info(
            "Registered YAML submission: disc=%s round=%d agent=%s verdict=%s",
            disc_id, round_, agent, verdict,
        )
        return True
    except Exception as e:
        _log.warning("Failed to register YAML submission %s: %s", yaml_path, e)
        return False


def _row_to_discussion(row: sqlite3.Row) -> DiscussionRow:
    return DiscussionRow(
        id=row["id"],
        task_id=row["task_id"],
        topic=row["topic"],
        owners=json.loads(row["owners"]),
        status=row["status"],
        consensus=row["consensus"],
        created_at=row["created_at"],
        closed_at=row["closed_at"],
    )


def _row_to_round(row: sqlite3.Row) -> DiscussionRoundRow:
    return DiscussionRoundRow(
        id=row["id"],
        discussion_id=row["discussion_id"],
        round_number=row["round_number"],
        agent=row["agent"],
        content=row["content"],
        verdict=row["verdict"],
        created_at=row["created_at"],
    )
