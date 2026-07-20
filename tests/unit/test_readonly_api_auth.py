"""Iteration 2 — every read-only /api/* GET must require the auth token.

Before this fix, `do_GET` never checked auth on any `/api/*` route: an
unauthenticated caller on the loopback port could read `/api/logs`,
`/api/status`, task reports, and handoffs. `GET /` must stay open — it is
what hands the token to the browser in the first place.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_DASH = (
    Path(__file__).resolve().parents[2]
    / "src" / "superharness" / "scripts" / "dashboard-ui.py"
)


def _load_dashboard_module():
    spec = importlib.util.spec_from_file_location("dashboard_ui_readauth_under_test", _DASH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dashboard_ui_readauth_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dash():
    return _load_dashboard_module()


def _handler(dash, path: str, headers: dict | None = None) -> object:
    """A real Handler instance with __init__ bypassed (see test_dashboard_csrf_guard.py)."""
    h = dash.Handler.__new__(dash.Handler)
    h.path = path
    # Default to a loopback Host. Every real HTTP client sends one, and do_GET
    # now refuses a rebound Host before routing (a rebound page could otherwise
    # read the auth token out of the unauthenticated `/` and replay it against
    # the read routes). Omitting it here would make these fixtures 403 for a
    # reason no real request ever hits — pass an explicit Host to test that.
    h.headers = {"Host": "127.0.0.1:8787", **(headers or {})}
    h.bind_host = "127.0.0.1"
    h.bind_port = 8787
    h.auth_token = "correct-token"
    h.project_dir = Path("/tmp/does-not-need-to-exist")
    h.label = "test"
    h.refresh_seconds = 5
    h.idle_timeout = 0
    return h


class TestReadOnlyAuth:
    def test_api_get_without_token_is_403(self, dash):
        h = _handler(dash, "/api/logs")
        h._json = MagicMock()
        h.do_GET()
        assert h._json.call_args[0][1] == 403

    def test_api_get_with_token_succeeds(self, dash):
        h = _handler(dash, "/api/logs", {"X-Superharness-Token": "correct-token"})
        h._json = MagicMock()
        h.do_GET()
        # No explicit status arg on the success path == the _json default (200).
        args = h._json.call_args[0]
        status = args[1] if len(args) > 1 else 200
        assert status == 200

    def test_root_page_stays_unauthenticated(self, dash):
        h = _handler(dash, "/")
        h._html = MagicMock()
        h._json = MagicMock()
        h.do_GET()
        h._html.assert_called_once()
        h._json.assert_not_called()

    def test_every_api_route_is_gated(self, dash):
        """Statically enumerate every `/api/` branch in do_GET and assert the
        auth gate precedes all of them, so a future route added after the
        gate cannot slip in ungated."""
        src = _DASH.read_text()
        start = src.index("def do_GET")
        end = src.index("def do_POST")
        body = src[start:end]

        gate_idx = body.index("self._verify_read_auth()")
        assert gate_idx != -1

        import re
        # Require at least one char after "/api/" so the gate's own bare
        # `if p.startswith("/api/"):` check (which has nothing after the
        # slash) is not mistaken for one of the specific routes it guards.
        branch_positions = [
            m.start()
            for m in re.finditer(r'if p(?: ==|\.startswith\()\s*["\']\/api\/[^"\']+["\']', body)
        ]
        assert len(branch_positions) >= 20, (
            "expected to find the known /api/ branches in do_GET; "
            "the enumeration pattern may be stale"
        )
        for pos in branch_positions:
            assert pos > gate_idx, (
                f"an /api/ branch at offset {pos} in do_GET appears before "
                f"the auth gate at offset {gate_idx} — it would be reachable "
                f"without a token"
            )
