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

import getpass
import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ROUTER_URL = "http://127.0.0.1:8200"
DEFAULT_TOKEN_FILE = "/var/lib/rmdi/control-token"
_TIMEOUT_SECONDS = 5


def router_url() -> str:
    return os.environ.get("RMDI_ROUTER_URL", DEFAULT_ROUTER_URL).rstrip("/")


# R12 — control-plane bearer (mirrors pi-extension/client.ts): possession of
# a token file is the identity. Read lazily, cached for the process; a missing
# or unreadable file sends no header and the router answers 401 naming the fix
# (fail loud, never fail silent).
_UNREAD = object()
_cached_token: Any = _UNREAD


def _token_candidates() -> list[str]:
    """RMDI_TOKEN_FILE overrides everything. Otherwise try the state-dir
    token (root clients), then the scoped per-user token minted for non-root
    clients (incident 2026-07-21 A): <state-dir>/control-tokens/<user>."""
    override = os.environ.get("RMDI_TOKEN_FILE")
    if override:
        return [override]
    candidates = [DEFAULT_TOKEN_FILE]
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    if user:
        candidates.append(os.path.join(os.path.dirname(DEFAULT_TOKEN_FILE), "control-tokens", user))
    return candidates


def _control_token() -> str | None:
    global _cached_token
    if _cached_token is _UNREAD:
        _cached_token = None
        for path in _token_candidates():
            try:
                with open(path, encoding="utf-8") as f:
                    token = f.read().strip()
            except OSError:
                continue
            if token:
                _cached_token = token
                break
    return _cached_token


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
            "Delegation is halted: model authority lives in the router (RMDI prevails by default). "
            "Fix the router (systemctl status rmdi-router on vm740, or RMDI_ROUTER_URL), "
            "or opt out for THIS SESSION only with SUPERHARNESS_ROUTING_STRATEGY=native "
            "(ephemeral — never edit routing_strategy into profile.yaml to escape an outage)."
        )


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    url = f"{router_url()}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {"Content-Type": "application/json"} if data is not None else {}
    token = _control_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
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


# Step-0.4 §3 (incident 2026-07-21 B): every dispatch carries a conservative
# prompt-size estimate — the router's context_window_fits predicate rejects an
# over-window binding at bind time (fail-closed on a missing estimate). chars/3
# over-counts on purpose (never under-count across a window boundary); the
# envelope allowance covers system prompt + tool schemas.
_ENVELOPE_TOKENS = 6_000


def estimate_prompt_tokens(prompt: str) -> int:
    return len(prompt) // 3 + 1 + _ENVELOPE_TOKENS


def dispatch(
    seat: str,
    from_seat: str | None = None,
    consent: bool = False,
    *,
    estimated_prompt_tokens: int | None = None,
    prompt: str | None = None,
    requested_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Resolve a seat's binding for a delegation. Returns
    {binding, modelRef, baseUrl, roleClass, seatConfig}.

    The router requires estimatedPromptTokens (fail-closed) — pass either the
    number directly or the prompt text to estimate from."""
    body: dict[str, Any] = {}
    if from_seat:
        body["from"] = from_seat
    if consent:
        body["consent"] = True
    if estimated_prompt_tokens is None and prompt is not None:
        estimated_prompt_tokens = estimate_prompt_tokens(prompt)
    if estimated_prompt_tokens is not None:
        body["estimatedPromptTokens"] = estimated_prompt_tokens
    if requested_output_tokens is not None:
        body["requestedOutputTokens"] = requested_output_tokens
    return _request("POST", f"/dispatch/{seat}", body)


def bindings() -> list[dict[str, Any]]:
    return _request("GET", "/bindings")


# Sentinel: distinguish OMITTED usage (non-executed classes) from an explicit
# usage: null attestation (executed but unmeasured — priced unknown, not zero).
_USAGE_OMITTED = object()


def outcome(
    lineage_id: str,
    exit_code: int,
    error_class: str,
    *,
    duration_ms: int | None = None,
    usage: Any = _USAGE_OMITTED,
) -> dict[str, Any]:
    """Close a delegation's lineage record (R1). Pass usage=None to attest
    executed-but-unmeasured; omit it entirely for non-executed classes."""
    body: dict[str, Any] = {"id": lineage_id, "exitCode": exit_code, "errorClass": error_class}
    if duration_ms is not None:
        body["durationMs"] = duration_ms
    if usage is not _USAGE_OMITTED:
        body["usage"] = usage
    return _request("POST", "/outcomes", body)


def close_lineage(
    lineage_id: str,
    exit_code: int,
    error_class: str,
    *,
    duration_ms: int | None = None,
    usage: Any = _USAGE_OMITTED,
) -> str | None:
    """Best-effort close (incident 2026-07-21 defect D): every dispatch opens a
    lineage record, so every exit path must close one. Retry once; a 409
    ALREADY_CLOSED is success (a prior append landed, its response was lost).
    Never raises — returns an error string for the caller to SURFACE (stderr),
    because a silent orphan is the defect this exists to kill."""
    if not lineage_id:
        return None
    last: str | None = None
    for _ in range(2):
        try:
            outcome(lineage_id, exit_code, error_class, duration_ms=duration_ms, usage=usage)
            return None
        except RmdiError as e:
            if e.code == "ALREADY_CLOSED":
                return None
            last = str(e)
        except Exception as e:  # router down etc. — surfaced, never fatal
            last = str(e)
    return f"lineage orphan: outcome for {lineage_id} could NOT be recorded — {last}"


def chat_completions(
    base_url: str,
    model_id: str,
    prompt: str,
    *,
    max_tokens: int = 4000,
    timeout: int = 60,
    api_key: str | None = None,
) -> str:
    """One OpenAI-compatible chat call against a binding's baseUrl. The single
    chat implementation for engine callers (orchestrator decompose etc.) —
    raises on any failure (callers decide their own degrade policy)."""
    payload = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base_url.rstrip('/')}/chat/completions", data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return str(data["choices"][0]["message"]["content"]).strip()
