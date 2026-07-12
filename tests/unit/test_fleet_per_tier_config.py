"""RED tests for iteration 7 of PLAN-superharness-L5.md: vLLM per-tier fleet
endpoints. Pins the multi-tier shape that iterations 1 and 3 only exercised
against a single-endpoint config — the shape docs/fleet-vllm-enablement.md
promises works.
"""
from __future__ import annotations

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


def _models_response(model_ids: list[str]) -> bytes:
    import json
    return json.dumps({"data": [{"id": m} for m in model_ids]}).encode()


def test_per_tier_endpoints_resolve_in_candidates():
    from superharness.engine.model_router import _fleet_candidates

    fleet = {
        "endpoints": {"mini": "http://gpu-mini:8100/v1", "standard": "http://gpu-std:8100/v1"},
        "models": {"mini": "qwen3-14b", "standard": "qwen3-32b"},
    }
    candidates = _fleet_candidates(fleet)
    assert candidates[0] == ("http://gpu-mini:8100/v1", "qwen3-14b")
    assert ("http://gpu-std:8100/v1", "qwen3-32b") in candidates
    assert len(candidates) == 2


def test_doctor_health_covers_all_configured_tiers():
    from superharness.engine.model_router import fleet_health

    fleet = {
        "endpoints": {"mini": "http://gpu-mini:8100/v1", "standard": "http://gpu-std:8100/v1"},
        "models": {"mini": "qwen3-14b", "standard": "qwen3-32b"},
    }
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", return_value=_FakeResp(_models_response(["qwen3-14b", "qwen3-32b"]))):
            result = fleet_health()
    tiers = {r[0] for r in result}
    assert tiers == {"mini", "standard"}
    assert all(status == "ok" for _t, _m, status in result)
