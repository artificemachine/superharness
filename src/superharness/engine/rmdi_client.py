"""Thin HTTP client for the RMDI delegation router (vm740 :8200).

RMDI (Role-Model Decoupling Invariant) is the external binding authority:
no superharness semantics may name a model when routing_strategy is "rmdi" —
models are reached only through seats, and every dispatch records the binding
that authored it (seat, bindingVersion, modelRef).

Fail-loud by design (the RMDI idiom): a down router raises RmdiRouterDown
naming RMDI_ROUTER_URL and the escape hatch (profile routing_strategy: native).
Silent degrade to the native ladder would invisibly flip decision authority
from DDAP back to superharness — the exact split-brain the merge removes.

stdlib-only (urllib), mirroring engine/model_router.py:_call_fleet.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ROUTER_URL = "http://127.0.0.1:8200"
_TIMEOUT_SECONDS = 5


def router_url() -> str:
    return os.environ.get("RMDI_ROUTER_URL", DEFAULT_ROUTER_URL).rstrip("/")


class RmdiError(Exception):
    """A structured error response from the router (409/428/503/...)."""

    def __init__(self, status: int, code: str, payload: dict[str, Any]):
        self.status = status
        self.code = code
        self.payload = payload
        super().__init__(f"rmdi router: {status} {code} {json.dumps(payload)}")


class RmdiRouterDown(Exception):
    """The router is unreachable — fail loud, never degrade silently."""

    def __init__(self, detail: str):
        super().__init__(
            f"RMDI router unreachable at {router_url()} ({detail}). "
            "Delegation is halted: routing_strategy is 'rmdi' and model authority lives in the router. "
            "Fix the router (systemctl status rmdi-router on vm740, or RMDI_ROUTER_URL), "
            "or explicitly set routing_strategy: native in .superharness/profile.yaml."
        )


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    url = f"{router_url()}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        raise RmdiError(e.code, err.get("code", "HTTP_ERROR"), err) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise RmdiRouterDown(str(e)) from None


def health() -> dict[str, Any]:
    return _request("GET", "/health")


def recipes() -> list[dict[str, Any]]:
    return _request("GET", "/recipes")


def recipe_switch(
    name: str,
    user: str | None = None,
    consent: bool = False,
    source: str = "shux",
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "source": source}
    if user:
        body["user"] = user
    if consent:
        body["consent"] = True
    return _request("POST", "/recipes/switch", body)


def switch_events(limit: int = 20) -> list[dict[str, Any]]:
    return _request("GET", f"/recipes/switch-events?limit={limit}")


def dispatch(seat: str, from_seat: str | None = None, consent: bool = False) -> dict[str, Any]:
    """Resolve a seat's binding for a delegation. Returns
    {binding, modelRef, baseUrl, roleClass, seatConfig}."""
    body: dict[str, Any] = {}
    if from_seat:
        body["from"] = from_seat
    if consent:
        body["consent"] = True
    return _request("POST", f"/dispatch/{seat}", body)


def bindings() -> list[dict[str, Any]]:
    return _request("GET", "/bindings")
