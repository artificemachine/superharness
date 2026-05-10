"""Integration tests for the dashboard /api/logs and /api/logs/stream endpoints."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

# TODO(macos-flake): the dashboard subprocess never becomes responsive on
# macos GitHub runners and produces no stdout/stderr even with
# PYTHONUNBUFFERED=1, defeating both the timeout-bump and stream-capture
# diagnostics. The same dashboard runs cleanly on ubuntu and on
# Windows-Native E2E. Skipping until the macos-specific stall is rooted
# out — the dashboard endpoints themselves are exercised on linux, and
# real macos coverage comes from the local pre-merge run.
pytestmark = pytest.mark.skipif(
    sys.platform == "darwin" and os.environ.get("CI") == "true",
    reason="dashboard subprocess silently hangs on macos GitHub runners; tracked as follow-up",
)

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _read_tail(p: Path | None) -> str:
    if p is None or not p.exists():
        return "<absent>"
    try:
        return p.read_text()[-2000:]
    except Exception as exc:
        return f"<read error: {exc}>"


def _wait_until_alive(
    port: int,
    timeout: float = 30.0,
    *,
    proc=None,
    stderr_path: Path | None = None,
    stdout_path: Path | None = None,
) -> None:
    """Poll the dashboard's /api/status until it responds or timeout elapses.

    macOS GitHub runners are noticeably slower at subprocess startup than
    ubuntu — 10s was tight enough to flake regularly even on a healthy run.
    Bumped to 30s. Also surfaces subprocess crash reasons so future failures
    are diagnosable instead of silent.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(
                f"dashboard subprocess exited with code {proc.returncode} "
                f"before becoming live.\n"
                f"--- stdout ---\n{_read_tail(stdout_path)}\n"
                f"--- stderr ---\n{_read_tail(stderr_path)}"
            )
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1).read()
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(
        f"dashboard never came up on port {port} within {timeout}s.\n"
        f"--- stdout ---\n{_read_tail(stdout_path)}\n"
        f"--- stderr ---\n{_read_tail(stderr_path)}"
    )


@pytest.fixture
def dashboard(tmp_path):
    """Spawn the dashboard pointed at a tmp project + isolated log files."""
    project = tmp_path / "proj"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("tasks: []\n")

    log_main = tmp_path / "main.log"
    log_audit = tmp_path / "audit.log"
    log_main.parent.mkdir(parents=True, exist_ok=True)
    log_main.touch()
    log_audit.touch()

    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = SRC
    env["SUPERHARNESS_LOG_FILE"] = str(log_main)
    env["SUPERHARNESS_AUDIT_LOG_FILE"] = str(log_audit)
    env["SUPERHARNESS_NO_AUTO_INSTALL"] = "1"
    # When stdout/stderr are pipes (not a terminal) Python block-buffers
    # them — without unbuffering, any prints from the dashboard's startup
    # path get lost when the test terminate()s the proc on timeout, and
    # the failure looks like "empty stdout/stderr". Force line buffering
    # so diagnostic prints reach the log files immediately.
    env["PYTHONUNBUFFERED"] = "1"

    stdout_log = tmp_path / "dashboard.stdout"
    stderr_log = tmp_path / "dashboard.stderr"
    stdout_fh = open(stdout_log, "wb")
    stderr_fh = open(stderr_log, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "superharness.scripts.dashboard-ui",
         "--port", str(port), "--project", str(project), "--no-open"],
        env=env, stdout=stdout_fh, stderr=stderr_fh,
        start_new_session=True,
    )
    try:
        _wait_until_alive(port, proc=proc, stderr_path=stderr_log, stdout_path=stdout_log)
        yield {"port": port, "main": log_main, "audit": log_audit, "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stdout_fh.close()
        stderr_fh.close()


def _get_json(port: int, path: str) -> dict:
    import json
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


def test_api_logs_returns_recent_lines(dashboard):
    dashboard["main"].write_text("\n".join([
        "2026-05-06T12:00:00+0200 INFO superharness.x:fn:1 first",
        "2026-05-06T12:00:01+0200 ERROR superharness.x:fn:2 second",
    ]) + "\n")
    d = _get_json(dashboard["port"], "/api/logs?n=10")
    assert "first" in d["lines"]
    assert "second" in d["lines"]
    assert d["audit"] is False


def test_api_logs_filters_by_level(dashboard):
    dashboard["main"].write_text("\n".join([
        "2026-05-06T12:00:00+0200 DEBUG superharness.x:fn:1 debug-only",
        "2026-05-06T12:00:01+0200 ERROR superharness.x:fn:2 error-only",
    ]) + "\n")
    d = _get_json(dashboard["port"], "/api/logs?n=10&level=ERROR")
    assert "debug-only" not in d["lines"]
    assert "error-only" in d["lines"]


def test_api_logs_audit_flag_reads_audit_file(dashboard):
    dashboard["main"].write_text("2026-05-06T12:00:00+0200 INFO m:f:1 main-only\n")
    dashboard["audit"].write_text("2026-05-06T12:00:00+0200 INFO a:f:1 audit-only\n")
    d = _get_json(dashboard["port"], "/api/logs?n=10&audit=1")
    assert d["audit"] is True
    assert "audit-only" in d["lines"]
    assert "main-only" not in d["lines"]


def test_api_logs_stream_emits_new_line(dashboard):
    """SSE endpoint sends new lines as they're appended."""
    port = dashboard["port"]
    log = dashboard["main"]
    # Open stream
    req = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/logs/stream", timeout=10)

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
