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
        "endpoints": {
            "mini": "http://a/v1",
            "standard": "http://a/v1",
            "all": "http://a/v1",
        },
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

    fleet = {
        "endpoints": {"all": "http://127.0.0.1:11434/v1"},
        "models": {"all": "qwen2.5:7b"},
    }
    with patch(
        "superharness.engine.model_router._load_fleet_config", return_value=fleet
    ):
        with patch(
            "urllib.request.urlopen", return_value=_FakeResp(_chat_response("mini low"))
        ):
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

    with patch(
        "superharness.engine.model_router._load_fleet_config", return_value=fleet
    ):
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            result = _call_fleet("classify this")

    assert result == "standard medium"
    assert calls == [
        "http://dead/v1/models",
        "http://alive/v1/models",
        "http://dead/v1/chat/completions",
        "http://alive/v1/chat/completions",
    ]


def test_all_endpoints_failing_returns_none():
    from superharness.engine.model_router import _call_fleet

    fleet = {
        "endpoints": {"mini": "http://dead1/v1", "all": "http://dead2/v1"},
        "models": {"mini": "m1", "all": "m2"},
    }
    with patch(
        "superharness.engine.model_router._load_fleet_config", return_value=fleet
    ):
        with patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("refused")
        ):
            result = _call_fleet("classify this")
    assert result is None


def test_live_candidates_prefer_configured_brain_priority_and_loaded_models():
    """A fleet brain must only select advertised, loaded models.

    ``brain.model_priority`` is an operator policy, ordered from best to worst.
    It wins over endpoint/tier order, while a model marked ``loaded: false`` is
    never selected.
    """
    from superharness.engine.model_router import _live_fleet_candidates

    fleet = {
        "endpoints": {"mini": "http://mini/v1", "standard": "http://std/v1"},
        "models": {"mini": "small", "standard": "stale-model"},
        "brain": {"model_priority": ["strong", "small"]},
    }

    with patch(
        "superharness.engine.model_router._fetch_fleet_models",
        side_effect=lambda endpoint: {
            "http://mini/v1": ["small"],
            "http://std/v1": ["strong"],
        }.get(endpoint),
    ):
        assert _live_fleet_candidates(fleet) == [
            ("http://std/v1", "strong"),
            ("http://mini/v1", "small"),
        ]


def test_live_candidates_keep_static_pair_when_discovery_is_unavailable():
    """A transient /models failure must not disable a known-good fleet config."""
    from superharness.engine.model_router import _live_fleet_candidates

    fleet = {
        "endpoints": {"all": "http://local/v1"},
        "models": {"all": "local-model"},
    }

    with patch(
        "superharness.engine.model_router._fetch_fleet_models", return_value=None
    ):
        assert _live_fleet_candidates(fleet) == [("http://local/v1", "local-model")]


def test_deepseek_is_tried_only_after_every_fleet_candidate_fails(monkeypatch):
    """The external fallback is opt-in and comes after the local fleet."""
    from superharness.engine.model_router import _call_fleet

    fleet = {
        "endpoints": {"all": "http://local/v1"},
        "models": {"all": "local-model"},
        "deepseek_fallback": {
            "enabled": True,
            "endpoint": "https://api.deepseek.example/v1",
            "model": "deepseek-chat",
        },
    }
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def call(endpoint, model, prompt, expect_tokens, api_key=None):
        calls.append((endpoint, model, api_key))
        return "remote answer" if api_key else None

    with patch(
        "superharness.engine.model_router._load_fleet_config", return_value=fleet
    ), patch(
        "superharness.engine.model_router._live_fleet_candidates",
        return_value=[("http://local/v1", "local-model")],
    ), patch("superharness.engine.model_router._call_fleet_endpoint", side_effect=call):
        assert _call_fleet("classify this") == "remote answer"

    assert calls == [
        ("http://local/v1", "local-model", None),
        ("https://api.deepseek.example/v1", "deepseek-chat", "test-key"),
    ]
