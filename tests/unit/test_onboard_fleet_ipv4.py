"""RED tests for iteration 2 of PLAN-superharness-L5.md: onboard fleet template IPv4 fix.

_section_fleet probed and wrote "localhost:11434" — ambiguous under IPv6-first
resolution, which is exactly what caused the fleet brain's six-month silent
death (see docs/brain-multi-agent-tiers-fleet.md: two Ollama servers shared
port 11434, "localhost" resolved to the wrong one). Must always use explicit
127.0.0.1.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_no_localhost_literal_in_fleet_section():
    from superharness.commands.onboard import _section_fleet

    source = inspect.getsource(_section_fleet)
    assert "localhost" not in source, (
        "fleet section must use explicit 127.0.0.1, never localhost "
        "(ambiguous under IPv6-first resolution)"
    )


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_written_fleet_config_uses_ipv4_loopback(tmp_path, monkeypatch):
    from superharness.commands.onboard import _section_fleet

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    tags_payload = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()

    with patch("urllib.request.urlopen", return_value=_FakeResp(tags_payload)):
        _section_fleet(tmp_path / "proj", {}, non_interactive=True)

    fleet_path = tmp_path / ".config" / "superharness" / "fleet.yaml"
    assert fleet_path.exists()
    import yaml
    written = yaml.safe_load(fleet_path.read_text())
    endpoint = written["fleet"]["endpoints"]["all"]
    assert endpoint.startswith("http://127.0.0.1:11434"), endpoint


def test_probe_url_uses_ipv4_loopback(tmp_path, monkeypatch):
    from superharness.commands.onboard import _section_fleet

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    tags_payload = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
    captured_urls = []

    def _fake_urlopen(req, timeout=None):
        captured_urls.append(req.full_url)
        return _FakeResp(tags_payload)

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        _section_fleet(tmp_path / "proj", {}, non_interactive=True)

    assert captured_urls, "probe never ran"
    for url in captured_urls:
        assert "127.0.0.1" in url, url
        assert "localhost" not in url, url
