"""Iteration 3 — confidence-gated apply to the project tier.

`apply_lessons` persists distilled lessons into project pitfalls.md: tagged,
deduped, refusing to overwrite a higher-confidence (or manual) existing entry.
"""
from __future__ import annotations

import re
from pathlib import Path

from superharness.engine import agent_memory
from superharness.engine.distiller import LessonEntry


TAG_RE = re.compile(r"^- \[c=(?P<conf>[0-9.]+) src=(?P<src>\S+) (?P<date>\d{4}-\d{2}-\d{2})\] (?P<text>.+)$")


def _pitfalls(project) -> Path:
    return Path(agent_memory.project_memory_dir(str(project))) / "pitfalls.md"


def _lesson(text, conf, typ="project"):
    return LessonEntry(text=text, type=typ, confidence=conf, source="distill")


# --------------------------------------------------------------------------
# Smoke
# --------------------------------------------------------------------------

def test_apply_empty_writes_nothing(clean_harness):
    n = agent_memory.apply_lessons([], str(clean_harness))
    assert n == 0
    assert not _pitfalls(clean_harness).exists()


# --------------------------------------------------------------------------
# Unit
# --------------------------------------------------------------------------

def test_apply_writes_tagged_line(clean_harness):
    n = agent_memory.apply_lessons([_lesson("use ruff for linting", 0.8)], str(clean_harness))
    assert n == 1
    body = [l for l in _pitfalls(clean_harness).read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    assert len(body) == 1
    m = TAG_RE.match(body[0])
    assert m and m.group("text") == "use ruff for linting"
    assert m.group("src") == "distill"


def test_apply_targets_project_tier(clean_harness):
    agent_memory.apply_lessons([_lesson("project scoped lesson", 0.8)], str(clean_harness))
    expected = Path(str(clean_harness)) / ".superharness" / "memory" / "pitfalls.md"
    assert expected.exists()
    assert "project scoped lesson" in expected.read_text()


def test_dedup_skips_existing_text(clean_harness):
    agent_memory.apply_lessons([_lesson("avoid global state", 0.8)], str(clean_harness))
    agent_memory.apply_lessons([_lesson("avoid global state", 0.8)], str(clean_harness))
    body = [l for l in _pitfalls(clean_harness).read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    assert len(body) == 1


def test_no_overwrite_higher_confidence(clean_harness):
    agent_memory.apply_lessons([_lesson("X is true", 0.9)], str(clean_harness))
    n = agent_memory.apply_lessons([_lesson("X is true", 0.7)], str(clean_harness))
    assert n == 0  # nothing written
    text = _pitfalls(clean_harness).read_text()
    assert "c=0.90" in text
    assert "c=0.70" not in text


def test_overwrites_lower_confidence(clean_harness):
    agent_memory.apply_lessons([_lesson("Y is better", 0.7)], str(clean_harness))
    n = agent_memory.apply_lessons([_lesson("Y is better", 0.95)], str(clean_harness))
    assert n == 1
    text = _pitfalls(clean_harness).read_text()
    assert "c=0.95" in text
    assert "c=0.70" not in text
    body = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    assert len(body) == 1  # replaced, not duplicated


def test_untagged_manual_line_preserved(clean_harness):
    p = _pitfalls(clean_harness)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Pitfalls\n\n- manual: always run shux doctor first\n")
    # An incoming lesson matching the manual line must not modify it.
    agent_memory.apply_lessons([_lesson("manual: always run shux doctor first", 0.99)], str(clean_harness))
    text = p.read_text()
    assert "- manual: always run shux doctor first" in text


# --------------------------------------------------------------------------
# Contract — line format round-trips
# --------------------------------------------------------------------------

def test_format_parse_roundtrip():
    line = agent_memory.format_lesson_line(_lesson("round trips cleanly", 0.83))
    text, conf = agent_memory.parse_lesson_line(line)
    assert text == "round trips cleanly"
    assert conf == 0.83


def test_parse_untagged_returns_none_confidence():
    text, conf = agent_memory.parse_lesson_line("- some manual note")
    assert conf is None


# --------------------------------------------------------------------------
# Regression — dispatch context includes project pitfalls.md
# --------------------------------------------------------------------------

def test_pitfalls_injected_into_dispatch_context(clean_harness):
    assert "pitfalls.md" in agent_memory.PROJECT_MEMORY_FILES
    agent_memory.apply_lessons([_lesson("inject me into context", 0.8)], str(clean_harness))
    ctx = agent_memory.get_dispatch_memory_context(str(clean_harness))
    assert "inject me into context" in ctx


def test_dispatch_context_mixed_tagged_and_manual(clean_harness):
    p = _pitfalls(clean_harness)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Pitfalls\n\n- manual note here\n")
    agent_memory.apply_lessons([_lesson("distilled note here", 0.8)], str(clean_harness))
    ctx = agent_memory.get_dispatch_memory_context(str(clean_harness))
    assert "manual note here" in ctx
    assert "distilled note here" in ctx


# --------------------------------------------------------------------------
# Chaos — corrupt existing line
# --------------------------------------------------------------------------

def test_corrupt_existing_line_survives(clean_harness):
    p = _pitfalls(clean_harness)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Pitfalls\n\n- [c=oops src= garbage line\n")
    # Should not crash; should still apply the new lesson.
    n = agent_memory.apply_lessons([_lesson("clean new lesson", 0.8)], str(clean_harness))
    assert n == 1
    assert "clean new lesson" in p.read_text()
