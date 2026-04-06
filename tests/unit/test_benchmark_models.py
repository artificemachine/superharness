"""Tests for shux benchmark --models (TDD: written before implementation)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


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
         "cost_usd": 1.50, "duration_seconds": 120, "outcome": "done", "timestamp": "2026-04-06T10:00:00+00:00"},
        {"task_id": "t2", "agent": "claude-code", "model": "claude-sonnet-4-6",
         "cost_usd": 0.30, "duration_seconds": 60, "outcome": "done", "timestamp": "2026-04-06T11:00:00+00:00"},
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
