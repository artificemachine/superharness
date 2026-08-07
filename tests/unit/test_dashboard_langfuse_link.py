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


def test_dashboard_langfuse_link_uses_original_size_and_orange_pulse() -> None:
    dashboard_html = (
        _REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard.html"
    ).read_text(encoding="utf-8")
    link_rule = re.search(r"\.external-link\s*\{([^}]*)\}", dashboard_html)

    assert link_rule is not None
    declarations = link_rule.group(1)
    assert "padding:4px 12px" in declarations
    assert "font-size:12px" in declarations
    assert "border-radius:6px" in declarations
    assert "background:#f97316" in declarations
    assert "color:#1c1917" in declarations
    assert "animation:langfuse-pulse 3s ease-in-out infinite" in declarations
    assert "@keyframes langfuse-pulse" in dashboard_html
    assert "rgba(249,115,22,.42)" in dashboard_html
    assert re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{"
        r".*?\.external-link\s*\{[^}]*animation:none",
        dashboard_html,
        re.DOTALL,
    )


def test_dashboard_exposes_persistent_dark_light_and_monokai_themes() -> None:
    dashboard_html = (
        _REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert ':root[data-theme="light"]' in dashboard_html
    assert ':root[data-theme="monokai"]' in dashboard_html
    assert 'id="themeSelect"' in dashboard_html
    assert 'aria-label="Dashboard theme"' in dashboard_html
    for value, label in (
        ("dark", "Dark"),
        ("light", "Light"),
        ("monokai", "Monokai"),
    ):
        assert f'<option value="{value}">{label}</option>' in dashboard_html

    restore = "localStorage.getItem('superharness-theme')"
    assert restore in dashboard_html
    assert dashboard_html.index(restore) < dashboard_html.index("</head>")
    assert "let theme = 'monokai'" in dashboard_html
    assert "document.documentElement.dataset.theme = theme" in dashboard_html
    assert "localStorage.setItem('superharness-theme', theme)" in dashboard_html
    assert "document.documentElement.dataset.theme || 'monokai'" in dashboard_html
