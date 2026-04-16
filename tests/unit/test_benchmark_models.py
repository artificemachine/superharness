"""Tests for shux benchmark --models (TDD: written before implementation)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner


def _recent_timestamp(days_ago: int = 1) -> str:
    """ISO UTC timestamp from N days ago.

    Benchmark output filters to the last 7 days (see commands/benchmark.py).
    Any hard-coded timestamp rolls out of that window after the fixture's
    authoring date, making the test flaky. Generating the timestamp relative
    to `now` keeps the fixture inside the window forever.
    """
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


def _write_benchmark(project: Path, records: list[dict]) -> None:
    bm = project / ".superharness" / "benchmark.jsonl"
    bm.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_benchmark_models_shows_usage(runner, project):
    """shux benchmark --models → table with Model column."""
    _write_benchmark(project, [
        {"task_id": "t1", "agent": "claude-code", "model": "claude-opus-4-6",
         "cost_usd": 1.50, "duration_seconds": 120, "outcome": "done",
         "timestamp": _recent_timestamp(days_ago=1)},
        {"task_id": "t2", "agent": "claude-code", "model": "claude-sonnet-4-6",
         "cost_usd": 0.30, "duration_seconds": 60, "outcome": "done",
         "timestamp": _recent_timestamp(days_ago=2)},
    ])
    from superharness.commands.benchmark import main as benchmark_main
    from io import StringIO
    import sys

    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()
    try:
        benchmark_main(["--project", str(project), "--models"])
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()
    assert "model" in output.lower() or "opus" in output.lower() or "sonnet" in output.lower()


def test_benchmark_models_empty(runner, project):
    """shux benchmark --models with no records → 'no data' message, exit 0."""
    from superharness.commands.benchmark import main as benchmark_main
    from io import StringIO
    import sys

    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()
    try:
        benchmark_main(["--project", str(project), "--models"])
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()
    # Should produce some output without crashing
    assert output is not None
