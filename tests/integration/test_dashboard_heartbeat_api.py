"""Integration tests for GET /api/heartbeats dashboard endpoint.

Spins up a real ThreadingHTTPServer and validates:
  - Empty DB returns all KNOWN_AGENTS with level='gray' (never seen)
  - Fresh heartbeat row returns level='green' (age < 60s)
  - Old heartbeat row (>300s) returns level='red'
  - Zombie-status row returns level='red' regardless of age
  - Response always includes 'agents' and 'now_utc' keys
"""
from __future__ import annotations

import importlib.util
import json
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

# ── import Handler from dashboard-ui.py (hyphen prevents normal import) ──────

_dashboard_src = Path(__file__).parents[2] / "src" / "superharness" / "scripts" / "dashboard-ui.py"
_spec = importlib.util.spec_from_file_location("dashboard_ui_hb", _dashboard_src)
_dashboard_ui = importlib.util.module_from_spec(_spec)
sys.modules["dashboard_ui_hb"] = _dashboard_ui
_spec.loader.exec_module(_dashboard_ui)

Handler = _dashboard_ui.Handler
from superharness.engine.db import get_connection, init_db
from superharness.engine import heartbeat_dao


# ── helpers ───────────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _harness(tmp_path: Path) -> Path:
    h = tmp_path / ".superharness"
    h.mkdir(exist_ok=True)
    (h / "handoffs").mkdir(exist_ok=True)
    return h


def _init_db(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()


def _insert_heartbeat(tmp_path: Path, agent: str, status: str, updated_at: str) -> None:
    conn = get_connection(str(tmp_path))
    heartbeat_dao.upsert(conn, agent=agent, status=status, now=updated_at)
    conn.commit()
    conn.close()


def _get(base: str, path: str, token: str | None = None) -> tuple[int, dict]:
    url = base + path
    req = urllib.request.Request(url, method="GET")
    if token is not None:
        req.add_header("X-Superharness-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ── server fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def server(tmp_path):
    harness = _harness(tmp_path)
    (harness / "contract.yaml").write_text(
        yaml.dump({"id": "test", "tasks": []}, default_flow_style=False)
    )
    (harness / "inbox.yaml").write_text("# inbox\n[]\n")
    _init_db(tmp_path)

    port = _free_port()
    token = secrets.token_urlsafe(16)

    Handler.project_dir = tmp_path
    Handler.label = "com.superharness.test-hb"
    Handler.refresh_seconds = 5
    Handler.scripts_dir = Path(_dashboard_ui.__file__).resolve().parent
    Handler.auth_token = token

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    yield f"http://127.0.0.1:{port}", token, tmp_path

    httpd.shutdown()


# ── tests ─────────────────────────────────────────────────────────────────────

class TestHeartbeatEndpoint:
    def test_returns_200_with_required_keys(self, server):
        base, token, _ = server
        status, body = _get(base, "/api/heartbeats", token)
        assert status == 200
        assert "agents" in body
        assert "now_utc" in body

    def test_empty_db_returns_gray_for_known_agents(self, server):
        """All KNOWN_AGENTS should appear as gray when the table has no rows."""
        base, token, _ = server
        _, body = _get(base, "/api/heartbeats", token)
        agents = body["agents"]
        # Every default known agent must be present
        for agent in ["claude-code", "codex-cli", "gemini-cli", "opencode"]:
            assert agent in agents, f"{agent} missing from response"
            assert agents[agent]["level"] == "gray", f"{agent} should be gray (never seen)"
            assert agents[agent]["age_seconds"] == -1
            assert agents[agent]["status"] is None

    def test_fresh_heartbeat_is_green(self, server):
        """A row updated just now (age < 60s) should produce level='green'."""
        base, token, tmp_path = server
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _insert_heartbeat(tmp_path, "claude-code", "alive", now_ts)

        _, body = _get(base, "/api/heartbeats", token)
        info = body["agents"]["claude-code"]
        assert info["level"] == "green"
        assert info["age_seconds"] >= 0
        assert info["age_seconds"] < 60

    def test_old_heartbeat_is_red(self, server):
        """A row not updated for >300s should produce level='red'."""
        base, token, tmp_path = server
        # 6 minutes ago
        old_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 370)
        )
        _insert_heartbeat(tmp_path, "codex-cli", "alive", old_ts)

        _, body = _get(base, "/api/heartbeats", token)
        info = body["agents"]["codex-cli"]
        assert info["level"] == "red"
        assert info["age_seconds"] >= 300

    def test_zombie_status_is_red(self, server):
        """A row with status='zombie' should produce level='red' regardless of age."""
        base, token, tmp_path = server
        # Updated very recently but already marked zombie
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _insert_heartbeat(tmp_path, "gemini-cli", "zombie", now_ts)

        _, body = _get(base, "/api/heartbeats", token)
        info = body["agents"]["gemini-cli"]
        assert info["level"] == "red"

    def test_idle_heartbeat_is_yellow(self, server):
        """A row updated 60-300s ago should produce level='yellow'."""
        base, token, tmp_path = server
        ts_90s_ago = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 90)
        )
        _insert_heartbeat(tmp_path, "opencode", "alive", ts_90s_ago)

        _, body = _get(base, "/api/heartbeats", token)
        info = body["agents"]["opencode"]
        assert info["level"] == "yellow"
        assert 60 <= info["age_seconds"] < 300

    def test_agent_not_in_known_agents_appears_if_in_db(self, server):
        """Agents not in KNOWN_AGENTS but in the heartbeats table must still appear."""
        base, token, tmp_path = server
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _insert_heartbeat(tmp_path, "custom-bot", "alive", now_ts)

        _, body = _get(base, "/api/heartbeats", token)
        assert "custom-bot" in body["agents"]
        assert body["agents"]["custom-bot"]["level"] == "green"

    def test_response_includes_task_id_and_updated_at(self, server):
        """Heartbeat info includes task_id and updated_at when a row exists."""
        base, token, tmp_path = server
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = get_connection(str(tmp_path))
        heartbeat_dao.upsert(conn, agent="claude-code", task_id="feat.x", status="alive", now=now_ts)
        conn.commit()
        conn.close()

        _, body = _get(base, "/api/heartbeats", token)
        info = body["agents"]["claude-code"]
        assert info["task_id"] == "feat.x"
        assert info["updated_at"] == now_ts
