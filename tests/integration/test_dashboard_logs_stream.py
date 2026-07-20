"""Integration tests for the dashboard /api/logs and /api/logs/stream endpoints."""
from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


def _load_dashboard_module():
    script = REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    spec = importlib.util.spec_from_file_location("dashboard_ui_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dashboard(tmp_path):
    """Start an in-process dashboard server pointed at a tmp project.

    Avoids spawning a subprocess so the test is not sensitive to startup timing
    or platform differences in process session handling (the macOS CI subprocess
    hang that plagued earlier versions of this file).
    """
    project = tmp_path / "proj"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("tasks: []\n")

    log_main = tmp_path / "main.log"
    log_audit = tmp_path / "audit.log"
    log_main.touch()
    log_audit.touch()

    # /api/logs resolves log paths from os.environ at request time; set them
    # here and restore on teardown.
    _saved = {
        "SUPERHARNESS_LOG_FILE": os.environ.get("SUPERHARNESS_LOG_FILE"),
        "SUPERHARNESS_AUDIT_LOG_FILE": os.environ.get("SUPERHARNESS_AUDIT_LOG_FILE"),
    }
    os.environ["SUPERHARNESS_LOG_FILE"] = str(log_main)
    os.environ["SUPERHARNESS_AUDIT_LOG_FILE"] = str(log_audit)

    module = _load_dashboard_module()
    module.Handler.project_dir = project
    module.Handler.label = module.project_label(project)
    module.Handler.refresh_seconds = 3
    module.Handler.scripts_dir = REPO_ROOT / "src" / "superharness" / "scripts"
    token = f"test-{uuid.uuid4().hex}"
    module.Handler.auth_token = token

    try:
        server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    except PermissionError as exc:
        pytest.skip(f"Socket bind not permitted in this environment: {exc}")

    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield {"port": port, "main": log_main, "audit": log_audit, "token": token}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for key, val in _saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _get_json(port: int, path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"X-Superharness-Token": token},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_api_logs_returns_recent_lines(dashboard):
    dashboard["main"].write_text("\n".join([
        "2026-05-06T12:00:00+0200 INFO superharness.x:fn:1 first",
        "2026-05-06T12:00:01+0200 ERROR superharness.x:fn:2 second",
    ]) + "\n")
    d = _get_json(dashboard["port"], "/api/logs?n=10", dashboard["token"])
    assert "first" in d["lines"]
    assert "second" in d["lines"]
    assert d["audit"] is False


def test_api_logs_filters_by_level(dashboard):
    dashboard["main"].write_text("\n".join([
        "2026-05-06T12:00:00+0200 DEBUG superharness.x:fn:1 debug-only",
        "2026-05-06T12:00:01+0200 ERROR superharness.x:fn:2 error-only",
    ]) + "\n")
    d = _get_json(dashboard["port"], "/api/logs?n=10&level=ERROR", dashboard["token"])
    assert "debug-only" not in d["lines"]
    assert "error-only" in d["lines"]


def test_api_logs_audit_flag_reads_audit_file(dashboard):
    dashboard["main"].write_text("2026-05-06T12:00:00+0200 INFO m:f:1 main-only\n")
    dashboard["audit"].write_text("2026-05-06T12:00:00+0200 INFO a:f:1 audit-only\n")
    d = _get_json(dashboard["port"], "/api/logs?n=10&audit=1", dashboard["token"])
    assert d["audit"] is True
    assert "audit-only" in d["lines"]
    assert "main-only" not in d["lines"]


def test_api_logs_stream_emits_new_line(dashboard):
    """SSE endpoint sends new lines as they're appended."""
    port = dashboard["port"]
    log = dashboard["main"]
    # Open stream. EventSource (the real browser client) can't set custom
    # headers, so dashboard-ui.py accepts the token via query param on this
    # one route too (see _verify_read_auth) — but this test uses urllib,
    # which can, so exercise the header path like every other GET.
    stream_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/logs/stream",
        headers={"X-Superharness-Token": dashboard["token"]},
    )
    req = urllib.request.urlopen(stream_req, timeout=10)

    # Append a line a moment later
    time.sleep(0.5)
    with log.open("a") as f:
        f.write("2026-05-06T12:00:00+0200 INFO superharness.x:fn:1 streamed-line\n")
        f.flush()

    # Collect data lines for up to 5s
    deadline = time.time() + 5.0
    saw = False
    while time.time() < deadline:
        line = req.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if text.startswith("data:") and "streamed-line" in text:
            saw = True
            break
    req.close()
    assert saw, "stream did not deliver the appended line"
