"""Tests for the durable model catalog failure journal."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from superharness.engine import model_catalog_journal
from superharness.engine.model_catalog_journal import (
    JOURNAL_FILENAME,
    record_catalog_failure,
)


def test_record_appends_one_json_line(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_dir))
    when = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)

    first = record_catalog_failure("anthropic", "timeout", now=when)
    second = record_catalog_failure("openai", "bad json", now=when)

    assert first is True
    assert second is True
    lines = (state_dir / JOURNAL_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    entries = [json.loads(line) for line in lines]
    for entry in entries:
        assert set(entry) == {"at", "source", "reason"}
    assert entries[0] == {
        "at": "2026-10-26T12:00:00+00:00",
        "source": "anthropic",
        "reason": "timeout",
    }
    assert entries[1]["source"] == "openai"
    assert entries[1]["reason"] == "bad json"


def test_record_reports_its_own_write_failure(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("regular file", encoding="utf-8")
    # The state dir sits under a regular file, so creating it raises OSError.
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(blocker / "state"))

    with caplog.at_level(logging.WARNING, logger=model_catalog_journal.__name__):
        result = record_catalog_failure("anthropic", "timeout")

    assert result is False
    assert any(
        "could not journal model catalog failure" in record.getMessage()
        for record in caplog.records
    )
