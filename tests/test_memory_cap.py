"""Iteration 4 — confidence-aware capped index for pitfalls.md.

Replaces blind FIFO pruning for pitfalls.md: a hard line+byte cap that evicts
lowest-confidence / oldest distilled lines first and never evicts manual lines.
"""
from __future__ import annotations

import time
from pathlib import Path

from superharness.engine import agent_memory


def _line(text, conf, date="2026-06-01"):
    return f"- [c={conf:.2f} src=distill {date}] {text}"


def _write(path: Path, body_lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Pitfalls\n\n" + "\n".join(body_lines) + "\n")


def _body(path: Path):
    return [l for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]


def test_cap_evicts_lowest_confidence_first(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 2)
    p = tmp_path / "pitfalls.md"
    _write(p, [_line("high", 0.9), _line("mid", 0.8), _line("low", 0.7)])
    agent_memory._cap_index(str(p))
    text = p.read_text()
    assert "c=0.70" not in text          # lowest dropped first
    assert "c=0.90" in text
    assert "c=0.80" in text


def test_cap_never_evicts_manual_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 1)
    p = tmp_path / "pitfalls.md"
    _write(p, ["- manual authoritative note", _line("distilled a", 0.9), _line("distilled b", 0.8)])
    agent_memory._cap_index(str(p))
    text = p.read_text()
    assert "- manual authoritative note" in text


def test_line_cap_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 5)
    p = tmp_path / "pitfalls.md"
    _write(p, [_line(f"lesson {i}", 0.5 + i / 100) for i in range(10)])
    agent_memory._cap_index(str(p))
    assert len(_body(p)) <= 5


def test_byte_cap_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 10_000)
    monkeypatch.setattr(agent_memory, "MAX_INDEX_BYTES", 400)
    p = tmp_path / "pitfalls.md"
    _write(p, [_line("x" * 80, 0.5 + i / 100) for i in range(10)])
    agent_memory._cap_index(str(p))
    assert len(p.read_text().encode()) <= 400


def test_under_cap_noop(tmp_path):
    p = tmp_path / "pitfalls.md"
    _write(p, [_line("just one", 0.8)])
    before = p.read_text()
    agent_memory._cap_index(str(p))
    assert p.read_text() == before


# --------------------------------------------------------------------------
# Integration — apply then cap invariants hold
# --------------------------------------------------------------------------

def test_apply_then_cap_holds_invariants(clean_harness, monkeypatch):
    from superharness.engine.distiller import LessonEntry
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 3)
    lessons = [LessonEntry(text=f"lesson {i}", type="project", confidence=0.5 + i / 100, source="distill")
               for i in range(6)]
    agent_memory.apply_lessons(lessons, str(clean_harness))
    p = Path(agent_memory.project_memory_dir(str(clean_harness))) / "pitfalls.md"
    assert len(_body(p)) <= 3


# --------------------------------------------------------------------------
# Contract — post-cap file still parses as valid distilled lines
# --------------------------------------------------------------------------

def test_post_cap_lines_still_parse(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 2)
    p = tmp_path / "pitfalls.md"
    _write(p, [_line("a", 0.9), _line("b", 0.8), _line("c", 0.7)])
    agent_memory._cap_index(str(p))
    for raw in _body(p):
        _text, conf = agent_memory.parse_lesson_line(raw)
        assert conf is not None  # survivors are valid distilled lines


# --------------------------------------------------------------------------
# Regression — other memory files still use FIFO prune unchanged
# --------------------------------------------------------------------------

def test_conventions_still_fifo_pruned(clean_harness):
    big = "x" * 200
    for i in range(60):  # well over MEMORY_FILE_MAX_CHARS (5000)
        agent_memory.append(str(clean_harness), "conventions.md", f"{big} line {i}")
    p = Path(agent_memory.project_memory_dir(str(clean_harness))) / "conventions.md"
    assert len(p.read_text()) <= agent_memory.MEMORY_FILE_MAX_CHARS


# --------------------------------------------------------------------------
# Chaos — only manual lines, over cap → kept, not truncated
# --------------------------------------------------------------------------

def test_only_manual_over_cap_not_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "MAX_INDEX_LINES", 1)
    p = tmp_path / "pitfalls.md"
    _write(p, ["- manual one", "- manual two", "- manual three"])
    agent_memory._cap_index(str(p))
    text = p.read_text()
    assert "manual one" in text and "manual two" in text and "manual three" in text


# --------------------------------------------------------------------------
# Performance — cap of a 10k-line file is fast (runs on every append)
# --------------------------------------------------------------------------

def test_cap_perf_10k_lines(tmp_path):
    p = tmp_path / "pitfalls.md"
    _write(p, [_line(f"lesson number {i}", 0.5 + (i % 50) / 100) for i in range(10_000)])
    start = time.perf_counter()
    agent_memory._cap_index(str(p))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1, f"cap took {elapsed:.3f}s"
