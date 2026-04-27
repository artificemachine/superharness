"""HTTP integration tests for the dashboard server.

Starts a real ThreadingHTTPServer on a random port, sends live HTTP requests,
and validates responses. Covers every endpoint that cannot be tested at the
unit layer because it requires the full HTTP plumbing:

  GET endpoints:
    /                   → 200 HTML
    /api/status         → 200 JSON with required keys
    /api/inbox          → 200 JSON {items, status}
    /api/board          → 200 JSON {board, review_queue, columns}
    /api/review-queue   → 200 JSON {queue}
    /api/costs          → 200 JSON {leaderboard, summary}
    /api/task-report    → 200 / 404
    /api/task-instructions → 200 / 404
    unknown path        → 404

  POST /api/action (auth required):
    no token            → 403
    bad token           → 403
    valid token + action → 200 or business-logic code

    subprocess-delegating actions (mock _run_cmd):
      dispatch_print_codex / dispatch_print_claude → 200 {exit_code, stdout}
      normalize_stale      → 200
      recover_retry        → 200
      approve_report:<id>  → 200
      close_task:<id>      → 200
      watcher_start        → 200

    logic-bearing actions (real behaviour without subprocess):
      recover_failed       → 200 {ok, recovered}
      clear_resolved_inbox → 200 {ok, removed}
      disable_task:<id>    → 200
      enable_task:<id>     → 200
      approve_plan:<id>    → 200 / 500 (wrong from_status)
      unknown action       → 400

  POST /api/owners (auth required):
    add invalid name     → 400
    add valid name       → 200
    remove with min guard → 400
"""

import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ── import Handler from dashboard-ui.py (hyphen prevents normal import) ───────

import importlib.util
import sys
from pathlib import Path as _Path

_dashboard_src = _Path(__file__).parents[2] / "src" / "superharness" / "scripts" / "dashboard-ui.py"
_spec = importlib.util.spec_from_file_location("dashboard_ui", _dashboard_src)
dashboard_ui = importlib.util.module_from_spec(_spec)
sys.modules["dashboard_ui"] = dashboard_ui
_spec.loader.exec_module(dashboard_ui)

Handler = dashboard_ui.Handler
from superharness.engine.db import get_connection, init_db


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


def _write_contract(harness: Path, tasks: list[dict] | None = None) -> None:
    f = harness / "contract.yaml"
    f.write_text(yaml.dump({"id": "test", "tasks": tasks or []}, default_flow_style=False))


def _write_inbox(harness: Path, items: list[dict] | None = None) -> None:
    f = harness / "inbox.yaml"
    f.write_text(
        "# inbox\n" + yaml.dump(items or [], default_flow_style=False, allow_unicode=True)
    )


def _init_db(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()


def _insert_task(tmp_path: Path, task_id: str, status: str, owner: str = "claude-code") -> None:
    conn = get_connection(str(tmp_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    now = "2026-04-27T00:00:00Z"
    conn.execute(
        "INSERT OR REPLACE INTO tasks (id, title, status, owner, created_at, acceptance_criteria, test_types, out_of_scope, definition_of_done) VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, task_id, status, owner, now, "[]", "[]", "[]", "[]"),
    )
    conn.commit()
    conn.close()


# ── server fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def server(tmp_path):
    """Spin up a real ThreadingHTTPServer for the duration of each test."""
    harness = _harness(tmp_path)
    _write_contract(harness)
    _write_inbox(harness)
    _init_db(tmp_path)

    port = _free_port()
    token = secrets.token_urlsafe(16)

    # Set Handler class-level attributes (mirrors dashboard-ui.py main())
    Handler.project_dir = tmp_path
    Handler.label = "com.superharness.test"
    Handler.refresh_seconds = 5
    Handler.scripts_dir = Path(dashboard_ui.__file__).resolve().parent
    Handler.auth_token = token

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    yield f"http://127.0.0.1:{port}", token

    httpd.shutdown()


# ── request helpers ───────────────────────────────────────────────────────────

def _get(base: str, path: str) -> tuple[int, dict]:
    url = base + path
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post_action(base: str, token: str, action: str, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps({"action": action, **(payload or {})}).encode()
    req = urllib.request.Request(
        base + "/api/action",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-Superharness-Token": token,
            "Origin": base,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post_owners(base: str, token: str, action: str, owner: str) -> tuple[int, dict]:
    body = json.dumps({"action": action, "owner": owner}).encode()
    req = urllib.request.Request(
        base + "/api/owners",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-Superharness-Token": token,
            "Origin": base,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ── GET endpoint tests ────────────────────────────────────────────────────────

class TestGetEndpoints:
    def test_root_returns_html(self, server):
        base, _ = server
        req = urllib.request.Request(base + "/", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
            ct = r.headers.get("Content-Type", "")
            assert "text/html" in ct

    def test_api_status_200_with_required_keys(self, server):
        base, _ = server
        status, body = _get(base, "/api/status")
        assert status == 200
        for key in ("version", "contract_tasks", "inbox_items", "activity_feed"):
            assert key in body, f"/api/status missing key '{key}'"

    def test_api_status_contract_tasks_is_list(self, server):
        base, _ = server
        _, body = _get(base, "/api/status")
        assert isinstance(body["contract_tasks"], list)

    def test_api_inbox_no_filter(self, server):
        base, _ = server
        status, body = _get(base, "/api/inbox")
        assert status == 200
        assert "items" in body
        assert isinstance(body["items"], list)

    def test_api_inbox_status_filter_field_returned(self, server):
        base, _ = server
        _, body = _get(base, "/api/inbox?status=paused")
        assert body.get("status") == "paused"

    def test_api_board_shape(self, server):
        base, _ = server
        status, body = _get(base, "/api/board")
        assert status == 200
        assert "board" in body
        assert "review_queue" in body
        assert "columns" in body

    def test_api_review_queue_shape(self, server):
        base, _ = server
        status, body = _get(base, "/api/review-queue")
        assert status == 200
        assert "queue" in body
        assert isinstance(body["queue"], list)

    def test_api_costs_shape(self, server):
        base, _ = server
        status, body = _get(base, "/api/costs")
        assert status == 200
        assert "leaderboard" in body
        assert "summary" in body
        assert isinstance(body["leaderboard"], list)

    def test_api_task_report_unknown_task_returns_200_with_data(self, server):
        """task-report always returns 200 — unknown tasks get a best-effort response."""
        base, _ = server
        status, body = _get(base, "/api/task-report?task=ghost-id")
        assert status == 200
        # No task found — body may contain an error key or empty fields
        assert isinstance(body, dict)

    def test_api_task_instructions_unknown_task_returns_200(self, server):
        """task-instructions always returns 200 — generates best-effort instructions."""
        base, _ = server
        status, body = _get(base, "/api/task-instructions?task=ghost-id")
        assert status == 200
        assert "instructions" in body

    def test_unknown_path_404(self, server):
        base, _ = server
        status, _ = _get(base, "/api/does-not-exist")
        assert status == 404

    def test_api_task_report_known_task_200(self, server, tmp_path):
        base, _ = server
        _insert_task(tmp_path, "t-report", "in_progress")
        status, body = _get(base, "/api/task-report?task=t-report")
        assert status == 200
        assert body.get("contract_status") == "in_progress"

    def test_api_task_instructions_known_task_200(self, server, tmp_path):
        base, _ = server
        _insert_task(tmp_path, "t-instr", "todo")
        status, body = _get(base, "/api/task-instructions?task=t-instr")
        assert status == 200
        assert "instructions" in body
        assert "task_meta" in body
        assert body["task_meta"].get("title") == "t-instr"


# ── POST auth tests ───────────────────────────────────────────────────────────

class TestPostAuth:
    def test_no_token_returns_403(self, server):
        base, _ = server
        body = json.dumps({"action": "recover_failed"}).encode()
        req = urllib.request.Request(
            base + "/api/action",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403

    def test_wrong_token_returns_403(self, server):
        base, _ = server
        status, _ = _post_action(base, "wrong-token", "recover_failed")
        assert status == 403

    def test_valid_token_passes_auth(self, server):
        base, token = server
        status, body = _post_action(base, token, "recover_failed")
        assert status == 200


# ── POST /api/action — subprocess-delegating (mocked _run_cmd) ───────────────

class TestSubprocessActions:
    """Actions that shell out — mock _run_cmd so tests don't spawn real processes."""

    def _mock_run(self, exit_code: int = 0, stdout: str = "ok") -> dict:
        return {"exit_code": exit_code, "stdout": stdout, "stderr": "", "cmd": "mocked"}

    @pytest.mark.parametrize("action", ["dispatch_print_codex", "dispatch_print_claude"])
    def test_dispatch_print_returns_200(self, server, action):
        base, token = server
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()):
            status, body = _post_action(base, token, action)
        assert status == 200
        assert body.get("exit_code") == 0

    def test_normalize_stale_returns_200(self, server):
        base, token = server
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()):
            status, body = _post_action(base, token, "normalize_stale")
        assert status == 200

    def test_recover_retry_returns_200(self, server):
        base, token = server
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()):
            status, body = _post_action(base, token, "recover_retry")
        assert status == 200

    def test_approve_report_delegates_to_close_cmd(self, server, tmp_path):
        base, token = server
        _insert_task(tmp_path, "t-close", "report_ready")
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()) as mock_cmd:
            status, _ = _post_action(base, token, "approve_report:t-close")
        assert status == 200
        # Verify close command was called with correct task id
        call_args = mock_cmd.call_args[0][0]
        assert "t-close" in call_args
        assert "close" in " ".join(call_args)

    def test_close_task_delegates_to_close_cmd(self, server, tmp_path):
        base, token = server
        _insert_task(tmp_path, "t-close2", "done")
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()) as mock_cmd:
            status, _ = _post_action(base, token, "close_task:t-close2")
        assert status == 200
        call_args = mock_cmd.call_args[0][0]
        assert "t-close2" in call_args

    def test_watcher_start_delegates_to_launchctl(self, server):
        base, token = server
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()):
            status, body = _post_action(base, token, "watcher_start")
        assert status == 200
        assert "exit_code" in body

    def test_watcher_restart_delegates_to_launchctl(self, server):
        base, token = server
        with patch.object(Handler, "_run_cmd", return_value=self._mock_run()):
            status, body = _post_action(base, token, "watcher_restart")
        assert status == 200


# ── POST /api/action — logic-bearing (no subprocess mock needed) ──────────────

class TestLogicActions:
    def test_recover_failed_no_items_returns_recovered_0(self, server):
        base, token = server
        status, body = _post_action(base, token, "recover_failed")
        assert status == 200
        assert body.get("ok") is True
        assert body.get("recovered") == 0

    def test_recover_failed_flips_failed_items(self, server, tmp_path):
        base, token = server
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT OR REPLACE INTO inbox (id, task_id, target_agent, status, priority, max_retries, created_at) VALUES (?,?,?,?,2,3,?)",
            ("i-fail", "t1", "claude-code", "failed", now),
        )
        conn.commit()
        conn.close()

        status, body = _post_action(base, token, "recover_failed")
        assert status == 200
        assert body.get("recovered", 0) >= 1

    def test_clear_resolved_inbox_returns_ok(self, server):
        base, token = server
        status, body = _post_action(base, token, "clear_resolved_inbox")
        assert status == 200
        assert body.get("ok") is True

    def test_disable_task_sets_stopped(self, server, tmp_path):
        base, token = server
        _insert_task(tmp_path, "t-dis", "todo")
        status, body = _post_action(base, token, "disable_task:t-dis")
        assert status == 200
        assert body.get("ok") is True
        conn = get_connection(str(tmp_path))
        row = conn.execute("SELECT status FROM tasks WHERE id='t-dis'").fetchone()
        conn.close()
        assert row[0] == "stopped"

    def test_enable_task_transitions_stopped_to_todo(self, server, tmp_path):
        base, token = server
        _insert_task(tmp_path, "t-en", "stopped")
        status, body = _post_action(base, token, "enable_task:t-en")
        assert status == 200
        assert body.get("ok") is True
        conn = get_connection(str(tmp_path))
        row = conn.execute("SELECT status FROM tasks WHERE id='t-en'").fetchone()
        conn.close()
        assert row[0] == "todo"

    def test_approve_plan_correct_status_succeeds(self, server, tmp_path):
        base, token = server
        _insert_task(tmp_path, "t-plan", "plan_proposed")
        status, body = _post_action(base, token, "approve_plan:t-plan")
        assert status == 200
        assert body.get("ok") is True
        conn = get_connection(str(tmp_path))
        row = conn.execute("SELECT status FROM tasks WHERE id='t-plan'").fetchone()
        conn.close()
        assert row[0] == "plan_approved"

    def test_approve_plan_wrong_status_fails(self, server, tmp_path):
        base, token = server
        _insert_task(tmp_path, "t-plan2", "todo")
        status, body = _post_action(base, token, "approve_plan:t-plan2")
        assert status in (200, 500)
        conn = get_connection(str(tmp_path))
        row = conn.execute("SELECT status FROM tasks WHERE id='t-plan2'").fetchone()
        conn.close()
        assert row[0] == "todo", "wrong-from-status must leave task unchanged"

    def test_unknown_action_returns_400(self, server):
        base, token = server
        status, body = _post_action(base, token, "totally_unknown_action")
        assert status == 400
        assert "error" in body

    def test_missing_task_id_returns_400(self, server):
        base, token = server
        for action in ["approve_plan:", "disable_task:", "enable_task:", "close_task:"]:
            status, body = _post_action(base, token, action)
            assert status == 400, f"'{action}' with empty id must return 400"

    def test_recover_failed_does_not_touch_running_items(self, server, tmp_path):
        base, token = server
        conn = get_connection(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = OFF")
        now = "2026-04-27T00:00:00Z"
        conn.execute(
            "INSERT OR REPLACE INTO inbox (id, task_id, target_agent, status, priority, max_retries, created_at) VALUES (?,?,?,?,2,3,?)",
            ("i-run", "t2", "claude-code", "running", now),
        )
        conn.commit()
        conn.close()

        _post_action(base, token, "recover_failed")

        conn2 = get_connection(str(tmp_path))
        row = conn2.execute("SELECT status FROM inbox WHERE id='i-run'").fetchone()
        conn2.close()
        assert row[0] == "running"


# ── POST /api/owners ──────────────────────────────────────────────────────────

class TestOwnersEndpoint:
    def test_invalid_owner_name_returns_400(self, server):
        base, token = server
        for bad in ["bad name", "bad.name", "", "a@b"]:
            status, body = _post_owners(base, token, "add", bad)
            assert status == 400, f"owner='{bad}' must return 400"

    def test_add_valid_owner_returns_200(self, server, tmp_path):
        base, token = server
        # Insert existing owner into SQLite (contract_owners prefers SQLite over YAML)
        _insert_task(tmp_path, "agent-claude-code", "todo", owner="claude-code")
        # owners/add calls subprocess.run directly (not _run_cmd) — patch it
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch.object(dashboard_ui.subprocess, "run", return_value=mock_result):
            status, body = _post_owners(base, token, "add", "new-agent")
        assert status == 200
        assert body.get("ok") is True

    def test_remove_below_minimum_returns_400(self, server, tmp_path):
        base, token = server
        # Insert both owners into SQLite (contract_owners prefers SQLite over YAML)
        _insert_task(tmp_path, "agent-claude-code", "todo", owner="claude-code")
        _insert_task(tmp_path, "agent-codex-cli", "todo", owner="codex-cli")
        status, body = _post_owners(base, token, "remove", "codex-cli")
        assert status == 400
        assert "at least" in body.get("error", "").lower()

    def test_no_auth_returns_403(self, server):
        base, _ = server
        body = json.dumps({"action": "add", "owner": "test-agent"}).encode()
        req = urllib.request.Request(
            base + "/api/owners",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403
