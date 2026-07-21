"""rmdi_client control-plane auth (RMDI incident 2026-07-21, defect A).

Every router call must carry `Authorization: Bearer <token>` when a token
file is readable — the missing header was the root cause of the 10× 401
dispatch failure. Token resolution: RMDI_TOKEN_FILE override, else the
state-dir token, else the scoped per-user token (control-tokens/<user>).
"""

from __future__ import annotations

import io
import json
import urllib.request

import pytest

from superharness.engine import rmdi_client


@pytest.fixture(autouse=True)
def _reset_token_cache():
    rmdi_client._cached_token = rmdi_client._UNREAD
    yield
    rmdi_client._cached_token = rmdi_client._UNREAD


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture_request(monkeypatch):
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["req"] = req
        return _FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def test_request_attaches_bearer_from_rmdi_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("scoped-secret\n")
    monkeypatch.setenv("RMDI_TOKEN_FILE", str(token_file))
    seen = _capture_request(monkeypatch)

    rmdi_client._request("POST", "/dispatch/scout@main", {"from": "worker@shux"})

    assert seen["req"].get_header("Authorization") == "Bearer scoped-secret"
    assert seen["req"].get_header("Content-type") == "application/json"


def test_get_requests_also_carry_the_bearer(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("scoped-secret\n")
    monkeypatch.setenv("RMDI_TOKEN_FILE", str(token_file))
    seen = _capture_request(monkeypatch)

    rmdi_client._request("GET", "/health")

    assert seen["req"].get_header("Authorization") == "Bearer scoped-secret"


def test_missing_token_file_sends_no_header_fail_loud_at_router(monkeypatch, tmp_path):
    monkeypatch.setenv("RMDI_TOKEN_FILE", str(tmp_path / "absent"))
    seen = _capture_request(monkeypatch)

    rmdi_client._request("POST", "/dispatch/scout@main", {})

    assert seen["req"].get_header("Authorization") is None


def test_candidates_fall_back_to_per_user_scoped_token(monkeypatch):
    monkeypatch.delenv("RMDI_TOKEN_FILE", raising=False)
    monkeypatch.setattr(rmdi_client.getpass, "getuser", lambda: "yjjoe")

    assert rmdi_client._token_candidates() == [
        "/var/lib/rmdi/control-token",
        "/var/lib/rmdi/control-tokens/yjjoe",
    ]


def test_env_override_wins_alone(monkeypatch):
    monkeypatch.setenv("RMDI_TOKEN_FILE", "/tmp/x")
    assert rmdi_client._token_candidates() == ["/tmp/x"]
