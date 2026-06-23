"""Iteration 2 — distiller extraction core.

Gather recent handoffs+ledger and extract <=N structured candidate lessons
via an injected LLM. Read-only: no writes here. The LLM is injected so these
tests are deterministic and never touch the network.
"""
from __future__ import annotations

import json

import pytest

from superharness.engine import distiller


# --------------------------------------------------------------------------
# Unit — gather candidates honors `since`
# --------------------------------------------------------------------------

def test_gather_candidates_since(monkeypatch):
    """Only handoffs/ledger newer than `since_days` are gathered."""
    from superharness.engine import state_reader

    monkeypatch.setattr(state_reader, "get_handoffs", lambda *a, **k: [
        {"created_at": "2020-01-01T00:00:00Z", "content": "OLD handoff lesson",
         "from_agent": "claude-code", "task_id": "t1", "phase": "report"},
        {"created_at": "2099-01-01T00:00:00Z", "content": "NEW handoff lesson",
         "from_agent": "claude-code", "task_id": "t2", "phase": "report"},
    ])
    monkeypatch.setattr(state_reader, "get_ledger_entries", lambda *a, **k: [])

    transcript = distiller.gather_candidates(".", since_days=7)
    assert "NEW handoff lesson" in transcript
    assert "OLD handoff lesson" not in transcript


def test_gather_empty_when_no_state(monkeypatch):
    from superharness.engine import state_reader
    monkeypatch.setattr(state_reader, "get_handoffs", lambda *a, **k: [])
    monkeypatch.setattr(state_reader, "get_ledger_entries", lambda *a, **k: [])
    assert distiller.gather_candidates(".", since_days=None) == ""


# --------------------------------------------------------------------------
# Unit — distill parsing / capping
# --------------------------------------------------------------------------

def _stub_llm(payload: object):
    """Return an llm_fn that always yields the JSON-encoded payload."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return lambda system, user: text


def test_extract_caps_at_n():
    """A response with 7 lessons is truncated to max_lessons (default 3)."""
    lessons = [{"text": f"lesson {i}", "type": "project", "confidence": 0.8} for i in range(7)]
    llm = _stub_llm({"lessons": lessons})
    out = distiller.distill("some transcript", llm_fn=llm)
    assert len(out) == 3


def test_extract_parses_fields():
    """Each extracted lesson carries text/type/confidence/source."""
    llm = _stub_llm({"lessons": [
        {"text": "prefer bun over npm", "type": "feedback", "confidence": 0.9},
    ]})
    out = distiller.distill("t", llm_fn=llm)
    assert len(out) == 1
    e = out[0]
    assert e.text == "prefer bun over npm"
    assert e.type == "feedback"
    assert e.confidence == 0.9
    assert e.source == "distill"


def test_invalid_type_defaults_to_project():
    llm = _stub_llm({"lessons": [{"text": "x", "type": "bogus", "confidence": 0.8}]})
    out = distiller.distill("t", llm_fn=llm)
    assert out[0].type == "project"


def test_confidence_clamped_and_defaulted():
    llm = _stub_llm({"lessons": [
        {"text": "a", "type": "project"},                       # missing confidence
        {"text": "b", "type": "project", "confidence": 5.0},    # out of range
    ]})
    out = distiller.distill("t", llm_fn=llm)
    assert out[0].confidence == pytest.approx(0.8)
    assert out[1].confidence == pytest.approx(1.0)


def test_llm_unavailable_returns_empty():
    """Injected llm_fn returning None yields [] (no crash)."""
    out = distiller.distill("t", llm_fn=lambda s, u: None)
    assert out == []


def test_empty_transcript_skips_llm():
    """No transcript → no LLM call, empty result."""
    called = {"n": 0}

    def llm(s, u):
        called["n"] += 1
        return "{}"

    assert distiller.distill("   ", llm_fn=llm) == []
    assert called["n"] == 0


# --------------------------------------------------------------------------
# Contract — malformed LLM output
# --------------------------------------------------------------------------

def test_malformed_json_returns_empty():
    out = distiller.distill("t", llm_fn=lambda s, u: "this is not json")
    assert out == []


def test_missing_text_field_skipped():
    llm = _stub_llm({"lessons": [{"type": "project", "confidence": 0.8}]})
    assert distiller.distill("t", llm_fn=llm) == []


# --------------------------------------------------------------------------
# Chaos — llm_fn raises
# --------------------------------------------------------------------------

def test_llm_raises_returns_empty():
    def boom(system, user):
        raise RuntimeError("provider exploded")

    assert distiller.distill("t", llm_fn=boom) == []


# --------------------------------------------------------------------------
# Integration — real DAO state → gather → distill
# --------------------------------------------------------------------------

def test_gather_then_distill_roundtrip(clean_harness):
    from tests.helpers import seed_sqlite_handoff, seed_sqlite_ledger
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seed_sqlite_handoff(clean_harness, "t1", content="decided to use SQLite as SSOT", now=now)
    seed_sqlite_ledger(clean_harness, action="VERIFY passed for t1", now=now)

    transcript = distiller.gather_candidates(str(clean_harness), since_days=30)
    assert "SQLite" in transcript

    llm = _stub_llm({"lessons": [{"text": "SQLite is SSOT", "type": "project", "confidence": 0.85}]})
    out = distiller.distill(transcript, llm_fn=llm)
    assert out and out[0].text == "SQLite is SSOT"


# --------------------------------------------------------------------------
# Regression — adding complete() leaves existing summarizer prompt intact
# --------------------------------------------------------------------------

def test_existing_summarizer_prompt_unchanged():
    from superharness.engine import summarizer_providers as sp
    prompt = sp._build_prompt({"task_id": "t9", "phase": "report", "outcome": "did the thing"})
    assert "t9" in prompt
    assert "did the thing" in prompt
    # complete() is additive and present.
    assert hasattr(sp, "complete")


def test_cheap_model_resolves_mini_tier():
    from superharness.engine.model_router import cheap_model
    assert "haiku" in cheap_model().lower()
