"""Iteration 2 — `shux distill --dry-run` is read-only.

Smoke + CLI: the dry-run path prints candidate lessons and writes nothing.
"""
from __future__ import annotations

from pathlib import Path

from superharness.commands import distill as distill_cmd
from superharness.engine import agent_memory


def test_dryrun_exit_zero_empty_project(clean_harness, monkeypatch, capsys):
    """Smoke: dry-run on an empty project exits 0 and writes nothing."""
    # No state seeded → gather returns "" → no LLM call needed, but stub anyway.
    monkeypatch.setattr(distill_cmd, "default_llm_fn", lambda s, u: None)
    rc = distill_cmd.main(["--project", str(clean_harness), "--dry-run"])
    assert rc == 0


def test_dryrun_prints_candidates_no_write(clean_harness, monkeypatch, capsys):
    """Dry-run prints lessons but never touches pitfalls.md."""
    from tests.helpers import seed_sqlite_handoff
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seed_sqlite_handoff(clean_harness, "t1", content="use ruff for linting", now=now)

    monkeypatch.setattr(
        distill_cmd, "default_llm_fn",
        lambda s, u: '{"lessons": [{"text": "use ruff for linting", "type": "feedback", "confidence": 0.9}]}',
    )

    pitfalls = Path(agent_memory.project_memory_dir(str(clean_harness))) / "pitfalls.md"
    before = pitfalls.read_text() if pitfalls.exists() else None

    rc = distill_cmd.main(["--project", str(clean_harness), "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "use ruff for linting" in out
    after = pitfalls.read_text() if pitfalls.exists() else None
    assert after == before  # unchanged (still absent or identical)


def test_dryrun_is_default(clean_harness, monkeypatch):
    """No --apply flag means dry-run: pitfalls.md is not created."""
    from tests.helpers import seed_sqlite_handoff
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seed_sqlite_handoff(clean_harness, "t1", content="something", now=now)
    monkeypatch.setattr(
        distill_cmd, "default_llm_fn",
        lambda s, u: '{"lessons": [{"text": "x", "type": "project", "confidence": 0.8}]}',
    )
    distill_cmd.main(["--project", str(clean_harness)])
    pitfalls = Path(agent_memory.project_memory_dir(str(clean_harness))) / "pitfalls.md"
    assert not pitfalls.exists()
