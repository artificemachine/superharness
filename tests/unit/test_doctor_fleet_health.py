"""RED tests for iteration 1 of PLAN-superharness-L5.md: doctor fleet health gate.

shux doctor currently prints PASS for the fleet section purely from
_load_fleet_config() succeeding — it never contacts the endpoint. This let
the fleet brain stay silently dead for six months (see
docs/brain-scan-2026-07-12.md, "Fleet fix applied"). model_router.fleet_health()
actually calls the endpoint's /models list and verifies each configured
model is present.
"""
from __future__ import annotations

import io
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _models_response(model_ids: list[str]) -> bytes:
    import json
    return json.dumps({"data": [{"id": m} for m in model_ids]}).encode()


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fleet_health_ok_when_model_listed():
    from superharness.engine.model_router import fleet_health

    fleet = {"endpoints": {"all": "http://127.0.0.1:11434/v1"}, "models": {"all": "qwen2.5:7b"}}
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", return_value=_FakeResp(_models_response(["qwen2.5:7b", "other"]))):
            result = fleet_health()
    assert result == [("all", "qwen2.5:7b", "ok")]


def test_fleet_health_model_missing():
    from superharness.engine.model_router import fleet_health

    fleet = {"endpoints": {"all": "http://127.0.0.1:11434/v1"}, "models": {"all": "qwen2.5:7b"}}
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", return_value=_FakeResp(_models_response(["some-other-model"]))):
            result = fleet_health()
    assert result == [("all", "qwen2.5:7b", "model-missing")]


def test_fleet_health_endpoint_unreachable():
    from superharness.engine.model_router import fleet_health

    fleet = {"endpoints": {"all": "http://127.0.0.1:11434/v1"}, "models": {"all": "qwen2.5:7b"}}
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = fleet_health()
    assert result == [("all", "qwen2.5:7b", "endpoint-unreachable")]


def test_fleet_health_timeout_reported_as_unreachable():
    from superharness.engine.model_router import fleet_health

    fleet = {"endpoints": {"all": "http://127.0.0.1:11434/v1"}, "models": {"all": "qwen2.5:7b"}}
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fleet):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = fleet_health(timeout=0.01)
    assert result == [("all", "qwen2.5:7b", "endpoint-unreachable")]


def test_fleet_health_no_config_returns_empty():
    from superharness.engine.model_router import fleet_health

    with patch("superharness.engine.model_router._load_fleet_config", return_value=None):
        result = fleet_health()
    assert result == []


def test_doctor_warns_on_unhealthy_fleet():
    from superharness.commands import doctor

    # doctor only calls fleet_health() inside `if fleet:` — a machine with no
    # fleet.yaml at all (e.g. a bare CI runner) never reaches that branch, so
    # mocking fleet_health() alone is not enough; _load_fleet_config() must
    # also be mocked truthy regardless of what's actually on disk.
    fake_fleet = {"endpoints": {"all": "http://127.0.0.1:11434/v1"}, "models": {"all": "qwen2.5:7b"}}
    with patch("superharness.engine.model_router._load_fleet_config", return_value=fake_fleet):
        with patch(
            "superharness.engine.model_router.fleet_health",
            return_value=[("all", "qwen2.5:7b", "model-missing")],
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                try:
                    doctor.main(["--project", str(REPO_ROOT)])
                except SystemExit:
                    pass
    output = buf.getvalue()
    assert "WARN fleet/" in output
    summary_line = [l for l in output.splitlines() if l.startswith("summary:")][0]
    warnings_count = int(summary_line.split("warnings=")[1])
    assert warnings_count >= 1
