"""Tests for the new summarizer section in get_insights()."""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import summarizer_calls
from superharness.engine.insights import get_insights


@pytest.fixture
def project_dir(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    c = get_connection(str(p))
    try:
        init_db(c, str(p))
    finally:
        c.close()
    return str(p)


def test_summarizer_section_empty_when_no_calls(project_dir):
    data = get_insights(project_dir)
    assert data["summarizer"] == []


def test_summarizer_section_returns_per_provider(project_dir):
    conn = get_connection(project_dir)
    try:
        summarizer_calls.record_call(conn, provider="anthropic", success=True,
                                     input_tokens=100, output_tokens=20)
        summarizer_calls.record_call(conn, provider="anthropic", success=True,
                                     input_tokens=200, output_tokens=40)
        summarizer_calls.record_call(conn, provider="anthropic", success=False)
        summarizer_calls.record_call(conn, provider="opencode", success=True)
    finally:
        conn.close()

    data = get_insights(project_dir)
    rows = {r["provider"]: r for r in data["summarizer"]}
    assert rows["anthropic"]["calls"] == 3
    assert rows["anthropic"]["successes"] == 2
    assert rows["anthropic"]["failures"] == 1
    assert rows["anthropic"]["input_tokens"] == 300
    assert rows["anthropic"]["output_tokens"] == 60
    assert rows["opencode"]["calls"] == 1
    assert rows["opencode"]["input_tokens"] == 0
    assert rows["opencode"]["output_tokens"] == 0


def test_summarizer_section_ordered_by_call_count(project_dir):
    conn = get_connection(project_dir)
    try:
        for _ in range(3):
            summarizer_calls.record_call(conn, provider="opencode", success=True)
        for _ in range(5):
            summarizer_calls.record_call(conn, provider="anthropic", success=True)
    finally:
        conn.close()

    data = get_insights(project_dir)
    providers_order = [r["provider"] for r in data["summarizer"]]
    assert providers_order == ["anthropic", "opencode"]


def test_summarizer_section_missing_db_path():
    """Older databases (or fresh project dirs) gracefully return empty."""
    data = get_insights("/nonexistent/xyz")
    assert data["summarizer"] == []


def test_summarizer_cli_renders_section(tmp_path, capsys, monkeypatch):
    """shux insights includes the new section in human-readable output."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c = get_connection(str(project_dir))
    try:
        init_db(c, str(project_dir))
        summarizer_calls.record_call(c, provider="opencode", success=True)
        summarizer_calls.record_call(c, provider="anthropic", success=True,
                                     input_tokens=100, output_tokens=20)
    finally:
        c.close()

    monkeypatch.chdir(project_dir)
    from superharness.commands.insights import main
    main(["-p", str(project_dir)])
    out = capsys.readouterr().out
    assert "── summarizer" in out
    assert "opencode" in out
    assert "anthropic" in out
    assert "in=100" in out
