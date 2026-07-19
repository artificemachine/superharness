"""Byte-offset transcript tailing for live dispatch progress (migration v32).

While a dispatch runs, the watcher can tail its Claude Code session
transcript JSONL by a persisted byte offset and emit telemetry events
(engine/events.py) for tool-use activity — live per-task progress without
parsing subprocess stdout.

Transcript path convention (not launched by this module — callers select a
transcript directory and pass a Path in): Claude Code writes session
transcripts to `~/.claude/projects/<munged-project-path>/<session-uuid>.jsonl`.
This module never touches that real directory itself (SIDE-EFFECT FENCE);
`select_transcript()` takes a directory as a parameter so tests and the
watcher's caller can point it anywhere, including fabricated fixtures.

Session-id selection limitation: there is no dispatch-to-session-uuid
mapping available in current dispatch metadata (checked: neither the
`inbox` nor `tasks` tables carry a Claude session id). `select_transcript`
therefore uses "newest .jsonl modified after dispatch launch_time" in the
given directory as the selection rule, per the plan's documented fallback.
If dispatch metadata later gains a session id column, prefer keying by it
directly instead of this heuristic.

See docs/PLAN-steal-omnigent.md iteration 7.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptProgress:
    """Telemetry event for one transcript line recognized as tool-use
    activity. Consumed by engine/events.py's generic emitter (any frozen
    dataclass with .kind and .task_id works there)."""

    task_id: str
    line_kind: str

    @property
    def kind(self) -> str:
        return "transcript_progress"


@dataclass(frozen=True)
class _Cursor:
    dispatch_id: str
    path: str
    byte_offset: int
    updated_at: Optional[str]


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def select_transcript(dir_path: str, launched_at: str) -> Optional[Path]:
    """Return the newest *.jsonl in dir_path modified at/after launched_at,
    or None if the directory doesn't exist or nothing qualifies."""
    directory = Path(dir_path)
    if not directory.is_dir():
        return None

    launched_dt = _parse_iso(launched_at)
    candidates: list[tuple[float, Path]] = []
    for p in directory.glob("*.jsonl"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if launched_dt is not None:
            mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            if mtime_dt < launched_dt:
                continue
        candidates.append((mtime, p))

    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


def _get_cursor(conn: sqlite3.Connection, dispatch_id: str) -> Optional[_Cursor]:
    row = conn.execute(
        "SELECT dispatch_id, path, byte_offset, updated_at FROM dispatch_cursors WHERE dispatch_id = ?",
        (dispatch_id,),
    ).fetchone()
    if row is None:
        return None
    return _Cursor(
        dispatch_id=row["dispatch_id"], path=row["path"],
        byte_offset=row["byte_offset"], updated_at=row["updated_at"],
    )


def _set_cursor(conn: sqlite3.Connection, dispatch_id: str, path: str, byte_offset: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO dispatch_cursors (dispatch_id, path, byte_offset, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dispatch_id) DO UPDATE SET
            path = excluded.path, byte_offset = excluded.byte_offset, updated_at = excluded.updated_at
        """,
        (dispatch_id, path, byte_offset, now),
    )
    conn.commit()


def _complete_lines(buf: bytes) -> tuple[list[bytes], int]:
    """Split buf into complete newline-terminated lines.

    Returns (lines, consumed_bytes) — a trailing partial line (no
    terminating newline) is NOT included and its bytes are NOT counted as
    consumed, so the next read starts from before it.
    """
    lines: list[bytes] = []
    consumed = 0
    start = 0
    for i, byte in enumerate(buf):
        if byte == 0x0A:  # b"\n"
            lines.append(buf[start:i])
            consumed = i + 1
            start = i + 1
    return lines, consumed


def _is_tool_use(record: dict) -> bool:
    """Recognize a transcript line as tool-use activity. Supports both a
    flat {"type": "tool_use"} shape and a nested Claude-Code-like
    {"message": {"content": [{"type": "tool_use"}, ...]}} shape."""
    if not isinstance(record, dict):
        return False
    if record.get("type") == "tool_use":
        return True
    message = record.get("message")
    if isinstance(message, dict):
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return True
    return False


def tail_step(conn: sqlite3.Connection, dispatch_id: str, transcript_path: Path) -> int:
    """Read new complete lines from transcript_path since the last stored
    cursor for dispatch_id, emit a telemetry event per tool-use line, and
    persist the advanced cursor. Returns the number of events emitted.

    Never raises on malformed content: bad JSON lines are skipped (logged
    WARNING) but do not block later lines. A file smaller than the stored
    offset (rotation/truncation) resets the cursor to 0 (logged WARNING).
    """
    path_str = str(transcript_path)
    stored = _get_cursor(conn, dispatch_id)
    offset = stored.byte_offset if (stored is not None and stored.path == path_str) else 0

    try:
        size = transcript_path.stat().st_size
    except OSError:
        return 0

    if size < offset:
        logger.warning(
            "transcript_tail: %s shrank below stored cursor offset (rotation/truncation); "
            "resetting cursor to 0", path_str,
        )
        offset = 0

    with open(transcript_path, "rb") as f:
        f.seek(offset)
        buf = f.read()

    lines, consumed = _complete_lines(buf)
    new_offset = offset + consumed

    emitted = 0
    if lines:
        from superharness.engine.events import emit

        for raw_line in lines:
            text = raw_line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("transcript_tail: malformed JSON line skipped in %s", path_str)
                continue
            if _is_tool_use(record):
                emit(TranscriptProgress(task_id=dispatch_id, line_kind="tool_use"))
                emitted += 1

    _set_cursor(conn, dispatch_id, path_str, new_offset)
    return emitted
