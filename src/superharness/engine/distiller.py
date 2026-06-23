"""Memory distiller — turn the cheap session record into curated lessons.

Reads the high-volume, append-only session record (handoffs + ledger in
SQLite) and distills it into a small set of structured lessons worth keeping
as persistent project memory. This is the curate path; the write path
(handoffs/ledger) already exists and is untouched.

The LLM call is injected (`llm_fn`) so the extraction logic is deterministic
under test and degrades to an empty result whenever the model is unavailable.

Iteration 2 delivers extraction only (read-only). Persistence and confidence
gating land in Iteration 3 (`apply_lessons` in agent_memory).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from superharness.engine import state_reader

logger = logging.getLogger(__name__)

MAX_LESSONS_DEFAULT = 3
VALID_TYPES = ("user", "feedback", "project", "reference")
_DEFAULT_CONFIDENCE = 0.8

# llm_fn(system, user) -> raw text response (or None on fault).
LlmFn = Callable[[str, str], Optional[str]]

DISTILL_SYSTEM = """\
You are a memory consolidation assistant for a multi-agent engineering harness.
Analyze the session record below (task handoffs and operational ledger) and
extract durable lessons worth keeping for future sessions.

Focus ONLY on:
1. User preferences or working-style corrections revealed in the work
2. Project decisions or facts made explicit (NOT derivable from code/git)
3. Behavioral feedback for agents (what to do or avoid, and why)

Return a JSON object with key "lessons": a list of objects, each with:
  "text":       the lesson, one sentence; for feedback/project lead with the
                rule/fact
  "type":       "user" | "feedback" | "project" | "reference"
  "confidence": float 0.0-1.0 (~0.8 inferred, ~0.9 clearly stated)

Do NOT extract code patterns, architecture, file paths, git history, debugging
fixes, or anything already obvious from CLAUDE.md. Return {"lessons": []} if
nothing new is worth keeping. Quality over quantity."""


@dataclass
class LessonEntry:
    text: str
    type: str
    confidence: float
    source: str = "distill"
    date: str = field(default_factory=lambda: date.today().isoformat())


def _entry_date(created_at: str) -> date | None:
    try:
        return date.fromisoformat(str(created_at)[:10])
    except (ValueError, TypeError):
        return None


def gather_candidates(project_dir: str, since_days: int | None = None) -> str:
    """Build a condensed transcript from recent handoffs + ledger entries.

    Returns "" when there is nothing in range — callers skip the LLM then.
    """
    cutoff: date | None = None
    if since_days is not None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=since_days)

    parts: list[str] = []

    try:
        handoffs = state_reader.get_handoffs(project_dir)
    except Exception as e:
        logger.warning("distiller gather: handoffs read failed: %s", e)
        handoffs = []
    for h in handoffs:
        if not isinstance(h, dict):
            continue
        d = _entry_date(h.get("created_at", ""))
        if cutoff and d and d < cutoff:
            continue
        body = str(h.get("content") or h.get("metadata") or "").strip()
        if not body:
            continue
        agent = str(h.get("from_agent") or h.get("agent") or "agent")
        task = str(h.get("task_id") or "?")
        parts.append(f"[handoff {task} by {agent}] {body[:800]}")

    try:
        ledger = state_reader.get_ledger_entries(project_dir, limit=200)
    except Exception as e:
        logger.warning("distiller gather: ledger read failed: %s", e)
        ledger = []
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        d = _entry_date(entry.get("created_at", ""))
        if cutoff and d and d < cutoff:
            continue
        action = str(entry.get("action") or "").strip()
        if not action:
            continue
        agent = str(entry.get("agent") or "agent")
        parts.append(f"[ledger by {agent}] {action[:300]}")

    return "\n".join(parts)


def _coerce_lesson(raw: object) -> LessonEntry | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or raw.get("content") or "").strip()
    if not text:
        return None
    typ = str(raw.get("type") or "project")
    if typ not in VALID_TYPES:
        typ = "project"
    try:
        conf = float(raw.get("confidence", _DEFAULT_CONFIDENCE))
    except (TypeError, ValueError):
        conf = _DEFAULT_CONFIDENCE
    conf = min(1.0, max(0.0, conf))
    return LessonEntry(text=text, type=typ, confidence=conf, source="distill")


def distill(
    transcript: str,
    *,
    llm_fn: LlmFn,
    max_lessons: int = MAX_LESSONS_DEFAULT,
) -> list[LessonEntry]:
    """Extract <=max_lessons structured lessons from a transcript.

    Returns [] for an empty transcript, an unavailable/failing LLM, or
    malformed output. Never raises on LLM faults.
    """
    if not transcript.strip():
        return []
    try:
        raw_text = llm_fn(DISTILL_SYSTEM, transcript)
    except Exception as e:
        logger.warning("distiller: llm_fn raised: %s", e)
        return []
    if not raw_text:
        return []
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("distiller: malformed JSON from llm_fn")
        return []
    items = parsed.get("lessons") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return []
    out: list[LessonEntry] = []
    for item in items[:max_lessons]:
        entry = _coerce_lesson(item)
        if entry is not None:
            out.append(entry)
    return out
