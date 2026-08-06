"""Contract for the dashboard's optional Langfuse navigation link."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_UI = (
    _REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard-ui.py"
)
_SPEC = importlib.util.spec_from_file_location("dashboard_ui_langfuse", _DASHBOARD_UI)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_dashboard_header_links_safely_to_configured_langfuse() -> None:
    html = _MODULE.render_dashboard_html("https://langfuse.example.com")
    match = re.search(
        r'<a\b[^>]*href="https://langfuse\.example\.com"[^>]*>'
        r"[^<]*Langfuse[^<]*</a>",
        html,
    )

    assert match is not None
    anchor = match.group(0)
    assert 'target="_blank"' in anchor
    assert 'rel="noopener noreferrer"' in anchor


def test_dashboard_hides_langfuse_link_when_unconfigured() -> None:
    html = _MODULE.render_dashboard_html("")

    assert "Langfuse" not in html
    assert "__LANGFUSE_LINK__" not in html


def test_dashboard_rejects_unsafe_langfuse_url() -> None:
    html = _MODULE.render_dashboard_html("javascript:alert(1)")

    assert "Langfuse" not in html
    assert "javascript:" not in html


def test_dashboard_rejects_langfuse_url_with_embedded_credentials() -> None:
    html = _MODULE.render_dashboard_html(
        "https://operator:secret@langfuse.example.com"
    )

    assert "Langfuse" not in html
    assert "operator:secret" not in html


def test_dashboard_hides_link_for_malformed_langfuse_url() -> None:
    html = _MODULE.render_dashboard_html("https://[invalid")

    assert "Langfuse" not in html


def test_dashboard_template_uses_a_runtime_link_placeholder() -> None:
    dashboard_html = (
        _REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "__LANGFUSE_LINK__" in dashboard_html
