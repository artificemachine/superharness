"""Light coverage that the dashboard HTML template still has the
observation-card scaffolding wired in.

Browser-side JS behaviour is exercised through manual smoke testing
(open the dashboard, click Observations on a task report). This test
exists to catch accidental deletion of the IDs and entry points the
JS depends on.
"""
from __future__ import annotations

from pathlib import Path


_HTML = Path(__file__).resolve().parents[2] / "src" / "superharness" / "scripts" / "dashboard.html"


def test_dashboard_html_exists():
    assert _HTML.is_file(), _HTML


def test_observations_card_present():
    text = _HTML.read_text(encoding="utf-8")
    assert 'id="observationsCard"' in text
    assert 'id="observationsMeta"' in text
    assert 'id="observationsBody"' in text


def test_citation_card_present():
    text = _HTML.read_text(encoding="utf-8")
    assert 'id="citationCard"' in text
    assert 'id="citationBody"' in text


def test_observations_button_on_task_report():
    text = _HTML.read_text(encoding="utf-8")
    assert "loadObservationsForCurrentTask" in text


def test_load_observations_function_defined():
    text = _HTML.read_text(encoding="utf-8")
    assert "async function loadObservations(taskId)" in text
    assert "/api/task/' + encodeURIComponent(taskId) + '/observations" in text


def test_show_citation_function_defined():
    text = _HTML.read_text(encoding="utf-8")
    assert "async function showCitation(kind, id)" in text
    assert "/api/' + encodeURIComponent(kind)" in text


def test_linkify_handles_all_four_kinds():
    text = _HTML.read_text(encoding="utf-8")
    # Regex must enumerate observation, handoff, decision, failure
    for kind in ("observation", "handoff", "decision", "failure"):
        assert kind in text


def test_html_escape_helper_defined():
    text = _HTML.read_text(encoding="utf-8")
    assert "_obsEscapeHtml" in text
