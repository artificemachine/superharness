"""RED tests for iteration 3 of PLAN-superharness-L5.md: _call_fleet endpoint failover.

_call_fleet picked exactly one endpoint (mini > standard > all precedence)
and returned None on any failure. _fleet_candidates() builds the ordered,
deduplicated (endpoint, model) pairs; _call_fleet tries each in order until
one succeeds.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _chat_response(content: str) -> bytes:
    import json
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def test_candidates_deduplicated_and_ordered():
    from superharness.engine.model_router import _fleet_candidates

    fleet = {
        "endpoints": {"mini": "http://a/v1", "standard": "http://a/v1", "all": "http://a/v1"},
        "models": {"mini": "m1", "standard": "m1", "all": "m1"},
    }
    assert _fleet_candidates(fleet) == [("http://a/v1", "m1")]

    fleet2 = {
        "endpoints": {"mini": "http://mini/v1", "all": "http://all/v1"},
        "models": {"mini": "m-small", "all": "m-big"},
    }
    candidates = _fleet_candidates(fleet2)
    assert candidates[0] == ("http://mini/v1", "m-small")
    assert ("http://all/v1", "m-big") in candidates


def test_single_endpoint_behavior_unchanged():
    from superharness.engine.model_router import _call_fleet

    fleet = {"endpoints": {"all": "http://127.0.0.1:11434/v1"}, "models": {"all": "qwen2.5:7b"}}
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", return_value=_FakeResp(_chat_response("mini low"))):
            result = _call_fleet("classify this")
    assert result == "mini low"


def test_failover_to_next_endpoint_on_error():
    from superharness.engine.model_router import _call_fleet

    fleet = {
        "endpoints": {"mini": "http://dead/v1", "all": "http://alive/v1"},
        "models": {"mini": "m-small", "all": "m-big"},
    }
    calls = []

    def _fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if "dead" in req.full_url:
            raise urllib.error.URLError("connection refused")
        return _FakeResp(_chat_response("standard medium"))

    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            result = _call_fleet("classify this")

    assert result == "standard medium"
    assert len(calls) == 2
    assert "dead" in calls[0]
    assert "alive" in calls[1]


def test_all_endpoints_failing_returns_none():
    from superharness.engine.model_router import _call_fleet

    fleet = {
        "endpoints": {"mini": "http://dead1/v1", "all": "http://dead2/v1"},
        "models": {"mini": "m1", "all": "m2"},
    }
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = _call_fleet("classify this")
    assert result is None
