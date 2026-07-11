"""Unit tests: _tail_lines reads the last N lines of a file without loading
the whole thing into memory.

Root cause this replaces (found live, 2026-07-11): _reinforce_loop read
trace.jsonl with `trace_file.read_text().splitlines()` — TWICE per call,
once to scan every historical event for agent-pause counts, once again to
check the last 50 lines for a dedup marker. Profiled at 1,379,991
json.loads calls in a single tick against a 181 MB file. Cost scales with
the file's entire lifetime history, and the file is append-only, so cost
only grows.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


class TestTailLines:
    def test_returns_last_n_lines_in_order(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _tail_lines
        f = tmp_path / "log.jsonl"
        f.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
        assert _tail_lines(f, 3) == ["line8", "line9", "line10"]

    def test_file_shorter_than_n_returns_all_lines(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _tail_lines
        f = tmp_path / "log.jsonl"
        f.write_text("a\nb\nc\n")
        assert _tail_lines(f, 100) == ["a", "b", "c"]

    def test_missing_file_returns_empty(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _tail_lines
        assert _tail_lines(tmp_path / "does_not_exist.jsonl", 50) == []

    def test_empty_file_returns_empty(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _tail_lines
        f = tmp_path / "log.jsonl"
        f.write_text("")
        assert _tail_lines(f, 50) == []

    def test_no_trailing_blank_line_from_trailing_newline(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _tail_lines
        f = tmp_path / "log.jsonl"
        f.write_text("a\nb\nc\n")
        assert _tail_lines(f, 2) == ["b", "c"]

    def test_handles_a_line_with_no_trailing_newline(self, tmp_path: Path):
        from superharness.commands.inbox_watch import _tail_lines
        f = tmp_path / "log.jsonl"
        f.write_text("a\nb\nc")  # no trailing \n
        assert _tail_lines(f, 2) == ["b", "c"]

    def test_cost_does_not_scale_with_file_history(self, tmp_path: Path):
        """The actual bug: reading the WHOLE file to get the tail. A
        multi-tens-of-MB file with the tail requested must not take
        proportionally long — a full-file read/split/parse of a file this
        size measurably takes well over the ceiling asserted below on any
        normal machine; a real tail read stays near-instant regardless of
        how much history precedes it."""
        from superharness.commands.inbox_watch import _tail_lines
        f = tmp_path / "big.jsonl"
        # ~40 MB of history ahead of the tail we actually want.
        with f.open("w") as fh:
            for i in range(400_000):
                fh.write('{"type":"process_recovery","i":%d,"pad":"%s"}\n' % (i, "x" * 60))
            for i in range(5):
                fh.write('{"type":"reinforce_agent_pause","agent":"codex-cli","i":%d}\n' % i)

        start = time.monotonic()
        lines = _tail_lines(f, 50)
        elapsed = time.monotonic() - start

        assert len(lines) == 50
        assert lines[-1].endswith('"i":4}')
        assert elapsed < 0.5, f"_tail_lines took {elapsed:.2f}s on a 40MB file — reading whole file, not tailing"
