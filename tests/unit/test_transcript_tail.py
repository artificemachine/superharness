"""Tests for engine.transcript_tail — byte-offset transcript tailing for
live dispatch progress (migration v32).

Fence: all fixtures are fabricated JSONL files under tmp_path. Never reads
real ~/.claude/projects/ transcripts (SIDE-EFFECT FENCE).

See docs/PLAN-steal-omnigent.md iteration 7.
"""
from __future__ import annotations

import json
import time

from superharness.engine.db import get_connection, init_db
from superharness.engine.transcript_tail import select_transcript, tail_step


def _write_lines(path, lines: list[str]) -> None:
    with open(path, "w") as f:
        for line in lines:
            f.write(line)


def test_tail_reads_new_lines_from_offset(tmp_path):
    conn = get_connection(str(tmp_path))
    init_db(conn)

    transcript = tmp_path / "session.jsonl"
    line1 = json.dumps({"type": "text", "text": "hi"}) + "\n"
    line2 = json.dumps({"type": "tool_use", "name": "Bash"}) + "\n"
    line3 = json.dumps({"type": "tool_use", "name": "Read"}) + "\n"
    _write_lines(transcript, [line1, line2, line3])

    offset_after_line2 = len((line1 + line2).encode())
    from superharness.engine.transcript_tail import _set_cursor
    _set_cursor(conn, "d1", str(transcript), offset_after_line2)

    emitted = tail_step(conn, "d1", transcript)
    assert emitted == 1  # only line3 is a tool_use line after the cursor

    from superharness.engine.transcript_tail import _get_cursor
    cursor = _get_cursor(conn, "d1")
    assert cursor.byte_offset == len((line1 + line2 + line3).encode())
    conn.close()


def test_cursor_persists_across_calls(tmp_path):
    conn = get_connection(str(tmp_path))
    init_db(conn)

    transcript = tmp_path / "session.jsonl"
    line1 = json.dumps({"type": "tool_use", "name": "Bash"}) + "\n"
    _write_lines(transcript, [line1])

    emitted1 = tail_step(conn, "d1", transcript)
    assert emitted1 == 1

    # Append a second line; a second tail_step must not re-deliver line1.
    line2 = json.dumps({"type": "tool_use", "name": "Read"}) + "\n"
    with open(transcript, "a") as f:
        f.write(line2)

    emitted2 = tail_step(conn, "d1", transcript)
    assert emitted2 == 1  # only the new line
    conn.close()


def test_partial_last_line_not_consumed(tmp_path):
    conn = get_connection(str(tmp_path))
    init_db(conn)

    transcript = tmp_path / "session.jsonl"
    complete_line = json.dumps({"type": "tool_use", "name": "Bash"}) + "\n"
    partial = '{"type": "tool_use", "name": "Rea'  # no trailing newline
    _write_lines(transcript, [complete_line, partial])

    emitted = tail_step(conn, "d1", transcript)
    assert emitted == 1  # only the complete line delivered

    from superharness.engine.transcript_tail import _get_cursor
    cursor = _get_cursor(conn, "d1")
    assert cursor.byte_offset == len(complete_line.encode())  # partial bytes not consumed

    # Complete the second line and tail again — it must now be delivered exactly once.
    with open(transcript, "a") as f:
        f.write('d", "extra": true}\n')

    emitted2 = tail_step(conn, "d1", transcript)
    assert emitted2 == 1
    conn.close()


def test_truncated_file_resets_cursor(tmp_path, caplog):
    import logging

    # The logging.getLogger("superharness").propagate poisoning this used to
    # work around per-test is now fixed globally by the autouse
    # _superharness_logger_propagates fixture in tests/conftest.py.
    conn = get_connection(str(tmp_path))
    init_db(conn)

    transcript = tmp_path / "session.jsonl"
    long_line = json.dumps({"type": "tool_use", "name": "Bash", "pad": "x" * 200}) + "\n"
    _write_lines(transcript, [long_line])
    tail_step(conn, "d1", transcript)  # advances cursor past long_line

    # Truncate to something smaller than the stored offset (simulates rotation).
    short_line = json.dumps({"type": "tool_use", "name": "Read"}) + "\n"
    _write_lines(transcript, [short_line])

    with caplog.at_level(logging.WARNING):
        emitted = tail_step(conn, "d1", transcript)
    assert emitted == 1  # re-read from offset 0 after reset
    assert any("truncat" in rec.message.lower() or "reset" in rec.message.lower() for rec in caplog.records)
    conn.close()


def test_malformed_json_line_skipped(tmp_path, caplog):
    import logging

    conn = get_connection(str(tmp_path))
    init_db(conn)

    transcript = tmp_path / "session.jsonl"
    bad_line = "not valid json at all\n"
    good_line = json.dumps({"type": "tool_use", "name": "Bash"}) + "\n"
    _write_lines(transcript, [bad_line, good_line])

    with caplog.at_level(logging.WARNING):
        emitted = tail_step(conn, "d1", transcript)
    assert emitted == 1  # good_line still delivered
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)
    conn.close()


def test_events_emitted_per_tool_use_line(tmp_path):
    from superharness.engine import events

    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()

    events.configure(str(tmp_path))

    transcript = tmp_path / "session.jsonl"
    line = json.dumps({"type": "tool_use", "name": "Bash"}) + "\n"
    _write_lines(transcript, [line])

    conn = get_connection(str(tmp_path))
    init_db(conn)
    emitted = tail_step(conn, "task-42", transcript)
    conn.close()
    assert emitted == 1

    assert events.flush(timeout=5) is True
    conn = get_connection(str(tmp_path))
    row = conn.execute(
        "SELECT task_id FROM events WHERE kind = 'transcript_progress'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["task_id"] == "task-42"


def test_select_transcript_picks_newest_after_launch(tmp_path):
    project_dir = tmp_path / "claude-project"
    project_dir.mkdir()

    old = project_dir / "old-session.jsonl"
    old.write_text('{"type": "text"}\n')
    time.sleep(0.02)

    launched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    time.sleep(0.02)

    newer = project_dir / "new-session.jsonl"
    newer.write_text('{"type": "text"}\n')

    picked = select_transcript(str(project_dir), launched_at)
    assert picked == newer


def test_select_transcript_returns_none_when_no_match(tmp_path):
    project_dir = tmp_path / "claude-project"
    project_dir.mkdir()
    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    assert select_transcript(str(project_dir), future) is None


# ---------------------------------------------------------------------------
# Watcher-cycle wiring (docs/PLAN-steal-omnigent.md iteration 7)
# ---------------------------------------------------------------------------

def test_transcript_tail_disabled_by_default_is_noop(clean_harness):
    """Flag off by default: no-op, no dispatch_cursors row created."""
    from superharness.commands.inbox_watch import _run_transcript_tail_if_enabled

    project_dir = str(clean_harness)
    _run_transcript_tail_if_enabled(project_dir)  # no profile.yaml transcript_tail key

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = conn.execute("SELECT * FROM dispatch_cursors").fetchall()
    finally:
        conn.close()
    assert rows == []


def test_watcher_cycle_tail_step_lands_events_when_enabled(clean_harness, monkeypatch):
    """Integration: seeded tmp project + fake launched dispatch + fixture
    transcript -> one watcher-cycle tail step lands events in the events
    table. The fixture transcript dir stands in for ~/.claude/projects/
    (SIDE-EFFECT FENCE: never touch the real directory)."""
    import yaml
    from superharness.engine import tasks_dao, inbox_dao, events
    from superharness.commands import inbox_watch

    project_dir = str(clean_harness)
    (clean_harness / ".superharness" / "profile.yaml").write_text(
        yaml.dump({"transcript_tail": True})
    )

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        tasks_dao.upsert(conn, tasks_dao.TaskRow(
            id="t1", title="T", owner="claude-code", status="in_progress",
            effort=None, project_path=project_dir, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z", blocked_by=[],
        ))
        conn.commit()
        inbox_dao.enqueue(conn, id="i1", task_id="t1", target_agent="claude-code",
                           now="2026-01-01T00:00:00Z")
        conn.commit()
        inbox_dao.claim_next(conn, target_agent="claude-code", pid=1234, now="2026-01-01T00:01:00Z")
        conn.commit()
    finally:
        conn.close()

    fixture_dir = clean_harness / "fake-claude-transcripts"
    fixture_dir.mkdir()
    transcript = fixture_dir / "session.jsonl"
    transcript.write_text(json.dumps({"type": "tool_use", "name": "Bash"}) + "\n")
    # ensure mtime is after launched_at ("2026-01-01T00:01:00Z" is in the
    # past relative to "now", so any freshly-written fixture file qualifies)

    monkeypatch.setattr(inbox_watch, "_claude_transcript_dir", lambda project_dir: str(fixture_dir))

    events.configure(project_dir)
    inbox_watch._run_transcript_tail_if_enabled(project_dir)
    assert events.flush(timeout=5) is True

    conn = get_connection(project_dir)
    try:
        row = conn.execute(
            "SELECT task_id FROM events WHERE kind = 'transcript_progress'"
        ).fetchone()
        cursor_row = conn.execute("SELECT * FROM dispatch_cursors").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["task_id"] == "t1"
    assert cursor_row is not None
