"""RED tests: the dashboard's CSRF defence is derived from attacker-controlled input.

Verified chain before this fix:

  1. `_expected_origin()` returned f"http://{self.headers.get('Host','')}" — the
     value it compares against is taken from the request itself, so it always
     matches. Against DNS rebinding it is a no-op.
  2. The Origin check read `if origin and origin != expected` — a request with
     no Origin header skipped it entirely.
  3. `GET /` is unauthenticated and injects the auth token into the served page
     (`html.replace("__AUTH_TOKEN__", ...)`), so a rebound page could read the
     token straight out of the DOM.
  4. `/api/discussion/<id>/close` and `/api/discussion/<id>/create-task` called
     no auth helper at all, yet both `subprocess.run(["shux", ...])`.

Together: operator has the dashboard on a guessable loopback port, visits a
hostile page, that page rebinds DNS to 127.0.0.1, reads the token from `/`, and
POSTs to an action route that spawns an agent subprocess. Browser to RCE.

The server is already loopback-bind-enforced, which does not help against a
browser the attacker controls — so the fix is to validate the Host header
against the real bind address and to authenticate the two orphaned routes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_DASH = (
    Path(__file__).resolve().parents[2]
    / "src" / "superharness" / "scripts" / "dashboard-ui.py"
)


def _load_dashboard_module():
    spec = importlib.util.spec_from_file_location("dashboard_ui_under_test", _DASH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dashboard_ui_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dash():
    return _load_dashboard_module()


def _handler(dash, headers: dict, bind_host="127.0.0.1", bind_port=8787):
    """A real Handler instance with __init__ bypassed.

    BaseHTTPRequestHandler.__init__ would try to service a socket, so it is
    skipped via __new__ — but the object is still a genuine Handler, so class
    attributes (_ALLOWED_HOSTNAMES) and the real method bodies are exercised
    rather than a stand-in that could drift from them.
    """
    h = dash.Handler.__new__(dash.Handler)
    h.headers = headers
    h.bind_host = bind_host
    h.bind_port = bind_port
    h.auth_token = "correct-token"
    return h


def _bind(dash, handler, name):
    return getattr(handler, name)


class TestHostHeaderIsValidated:
    def test_rebound_host_is_rejected(self, dash):
        """A DNS-rebound request arrives with the attacker's hostname in Host.
        It must be rejected regardless of anything else in the request."""
        h = _handler(dash, {"Host": "evil.com"})
        assert _bind(dash, h, "_host_is_allowed")() is False

    @pytest.mark.parametrize("host", [
        "127.0.0.1:8787", "localhost:8787", "[::1]:8787", "127.0.0.1", "localhost",
    ])
    def test_loopback_hosts_accepted(self, dash, host):
        h = _handler(dash, {"Host": host})
        assert _bind(dash, h, "_host_is_allowed")() is True

    def test_expected_origin_not_derived_from_host_header(self, dash):
        """The whole point: the expected origin must come from the server's own
        bind address, so a forged Host cannot make the comparison pass."""
        h = _handler(dash, {"Host": "evil.com"})
        assert "evil.com" not in _bind(dash, h, "_expected_origin")()


class TestMutationAuth:
    def test_tokened_client_without_origin_is_allowed(self, dash):
        """A request with a valid token but no Origin/Referer must be allowed.

        CSRF is a browser-only attack, and browsers always send Origin on a
        cross-origin POST — so a request with neither header did not come from
        a page. It came from a client that already holds the token (curl, the
        e2e suite, scripts). Rejecting these buys no security and breaks
        legitimate automation; an earlier revision of this guard did exactly
        that and turned every e2e dashboard test into a 403.

        Rebinding is closed by _host_is_allowed() and by deriving the expected
        origin from the real bind address, not by demanding the header.
        """
        h = _handler(dash, {
            "Host": "127.0.0.1:8787",
            "X-Superharness-Token": "correct-token",
        })
        assert _bind(dash, h, "_verify_mutation_auth")() is None

    def test_rebound_request_is_still_rejected_without_origin(self, dash):
        """The permissive path above must not become a bypass: a rebound
        request carries the attacker's hostname in Host and is refused even
        with a valid token and no Origin header."""
        h = _handler(dash, {
            "Host": "evil.com",
            "X-Superharness-Token": "correct-token",
        })
        assert _bind(dash, h, "_verify_mutation_auth")() is not None

    def test_forged_host_cannot_authorise_mutation(self, dash):
        h = _handler(dash, {
            "Host": "evil.com",
            "Origin": "http://evil.com",
            "X-Superharness-Token": "correct-token",
        })
        assert _bind(dash, h, "_verify_mutation_auth")() is not None

    def test_same_origin_request_with_token_still_works(self, dash):
        """Guard must not break the dashboard's own UI."""
        h = _handler(dash, {
            "Host": "127.0.0.1:8787",
            "Origin": "http://127.0.0.1:8787",
            "X-Superharness-Token": "correct-token",
        })
        assert _bind(dash, h, "_verify_mutation_auth")() is None

    def test_bad_token_still_rejected(self, dash):
        h = _handler(dash, {
            "Host": "127.0.0.1:8787",
            "Origin": "http://127.0.0.1:8787",
            "X-Superharness-Token": "wrong",
        })
        assert _bind(dash, h, "_verify_mutation_auth")() is not None


class TestOrphanedRoutesAreAuthenticated:
    @pytest.mark.parametrize("route", ["/close", "/create-task"])
    def test_discussion_mutation_routes_call_auth(self, route):
        """Both routes subprocess out to `shux`; neither called the auth helper.
        Asserted on source because exercising them needs a full HTTP server."""
        src = _DASH.read_text()
        marker = f'p.endswith("{route}")'
        idx = src.find(marker)
        assert idx != -1, f"route handler for {route} not found"
        window = src[idx:idx + 700]
        assert "_verify_mutation_auth" in window, (
            f"POST {route} does not call _verify_mutation_auth within its handler "
            f"body — it spawns a shux subprocess unauthenticated"
        )
