"""Tests for watcher health monitoring: heartbeat file + session-start health check."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tests.helpers import run_bash, parse_json_output


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text("id: demo\nstatus: active\ntasks: []\n")
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    return project


# ---------------------------------------------------------------------------
# 1. Heartbeat: inbox-watch.sh writes .superharness/watcher.heartbeat
# ---------------------------------------------------------------------------


def test_watcher_writes_heartbeat_file(repo_root: Path, tmp_path: Path) -> None:
    """After a single watcher cycle, a heartbeat file must exist with a recent UTC timestamp."""
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    # No inbox file → watcher runs cycle but skips dispatch (normal).
    # Single-cycle mode (no --foreground).
    result = run_bash(
        repo_root / "scripts" / "inbox-watch.sh",
        cwd=repo_root,
        args=["--project", str(project)],
    )
    assert result.returncode == 0, result.stderr
    assert heartbeat.exists(), "watcher must write heartbeat file after cycle"
    content = heartbeat.read_text().strip()
    # Must be an ISO 8601 UTC timestamp
    assert content.endswith("Z"), f"heartbeat must be UTC ISO 8601, got: {content}"
    assert "T" in content, f"heartbeat must contain date and time, got: {content}"


def test_watcher_heartbeat_updates_each_cycle(repo_root: Path, tmp_path: Path) -> None:
    """Heartbeat timestamp must update on each cycle (not be stale from first write)."""
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    run_bash(
        repo_root / "scripts" / "inbox-watch.sh",
        cwd=repo_root,
        args=["--project", str(project)],
    )
    first = heartbeat.read_text().strip()

    time.sleep(1)

    run_bash(
        repo_root / "scripts" / "inbox-watch.sh",
        cwd=repo_root,
        args=["--project", str(project)],
    )
    second = heartbeat.read_text().strip()
    assert second >= first, "heartbeat must not go backwards"


# ---------------------------------------------------------------------------
# 2. Session-start hook: detects stale/missing heartbeat
# ---------------------------------------------------------------------------


def test_session_start_warns_when_heartbeat_missing(repo_root: Path, tmp_path: Path) -> None:
    """When no heartbeat file exists, session-start should warn that watcher may be down."""
    project = _setup_project(tmp_path)

    result = run_bash(
        repo_root / "adapters" / "claude-code" / "hooks" / "session-start.sh",
        cwd=project,
    )
    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    ctx = output.get("additionalContext", "")
    assert "heartbeat" in ctx.lower() or "watcher" in ctx.lower(), (
        "session-start must mention watcher health when heartbeat is missing"
    )
    assert "no heartbeat" in ctx.lower() or "not running" in ctx.lower() or "may not be running" in ctx.lower(), (
        f"session-start must warn about missing heartbeat, got: {ctx}"
    )


def test_session_start_warns_when_heartbeat_stale(repo_root: Path, tmp_path: Path) -> None:
    """When heartbeat is older than 2x expected interval, session-start should warn."""
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"
    # Write a heartbeat that is 10 minutes old (stale for any reasonable interval)
    stale_time = time.time() - 600
    from datetime import datetime, timezone

    stale_ts = datetime.fromtimestamp(stale_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(stale_ts + "\n")

    result = run_bash(
        repo_root / "adapters" / "claude-code" / "hooks" / "session-start.sh",
        cwd=project,
    )
    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    ctx = output.get("additionalContext", "")
    assert "stale" in ctx.lower() or "behind" in ctx.lower() or "ago" in ctx.lower(), (
        f"session-start must warn about stale heartbeat, got: {ctx}"
    )


def test_session_start_ok_when_heartbeat_fresh(repo_root: Path, tmp_path: Path) -> None:
    """When heartbeat is recent, session-start should report watcher as healthy."""
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"
    from datetime import datetime, timezone

    fresh_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(fresh_ts + "\n")

    result = run_bash(
        repo_root / "adapters" / "claude-code" / "hooks" / "session-start.sh",
        cwd=project,
    )
    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    ctx = output.get("additionalContext", "")
    # Should NOT contain stale/down warnings
    assert "stale" not in ctx.lower(), f"fresh heartbeat should not trigger stale warning: {ctx}"
    assert "not running" not in ctx.lower(), f"fresh heartbeat should not say not running: {ctx}"


# ---------------------------------------------------------------------------
# 3. Watcher cycle must not block on dispatch
# ---------------------------------------------------------------------------


def test_watcher_cycle_completes_while_dispatch_runs(repo_root: Path, tmp_path: Path) -> None:
    """Watcher cycle must return quickly even when dispatch launches a long-running process."""
    project = _setup_project(tmp_path)
    (project / ".superharness" / "inbox.yaml").write_text(
        "- id: slow-task\n"
        "  to: claude-code\n"
        "  task: test-slow\n"
        f"  project: {project}\n"
        "  status: pending\n"
        "  retry_count: 0\n"
        "  max_retries: 3\n"
        "  created_at: 2026-03-12T00:00:00Z\n"
    )

    fake_dispatch = tmp_path / "fake-dispatch.sh"
    fake_dispatch.write_text(
        "#!/bin/bash\n"
        f"echo $$ > {tmp_path}/dispatch.pid\n"
        "sleep 30\n"
    )
    fake_dispatch.chmod(0o755)

    fake_recover = tmp_path / "fake-recover.sh"
    fake_recover.write_text("#!/bin/bash\nexit 0\n")
    fake_recover.chmod(0o755)

    import subprocess

    env = os.environ.copy()
    env["DISPATCH"] = str(fake_dispatch)
    env["RECOVER"] = str(fake_recover)

    start = time.monotonic()
    result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "inbox-watch.sh"),
         "--project", str(project)],
        cwd=repo_root, capture_output=True, text=True, timeout=10, env=env,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 5, (
        f"Watcher cycle took {elapsed:.1f}s — dispatch is blocking the cycle. "
        "Dispatch must run in background."
    )

    pid_file = tmp_path / "dispatch.pid"
    if pid_file.exists():
        for line in pid_file.read_text().strip().splitlines():
            try:
                os.kill(int(line.strip()), 9)
            except (ProcessLookupError, ValueError):
                pass


def test_watcher_lock_released_during_dispatch(repo_root: Path, tmp_path: Path) -> None:
    """Watcher lock must be released after cycle even if dispatch is still running."""
    project = _setup_project(tmp_path)
    (project / ".superharness" / "inbox.yaml").write_text(
        "- id: lock-test\n"
        "  to: claude-code\n"
        "  task: test-lock\n"
        f"  project: {project}\n"
        "  status: pending\n"
        "  retry_count: 0\n"
        "  max_retries: 3\n"
        "  created_at: 2026-03-12T00:00:00Z\n"
    )

    fake_dispatch = tmp_path / "fake-dispatch.sh"
    fake_dispatch.write_text(
        "#!/bin/bash\n"
        f"echo $$ >> {tmp_path}/dispatch.pid\n"
        "sleep 30\n"
    )
    fake_dispatch.chmod(0o755)

    fake_recover = tmp_path / "fake-recover.sh"
    fake_recover.write_text("#!/bin/bash\nexit 0\n")
    fake_recover.chmod(0o755)

    import subprocess

    env = os.environ.copy()
    env["DISPATCH"] = str(fake_dispatch)
    env["RECOVER"] = str(fake_recover)

    subprocess.run(
        ["bash", str(repo_root / "scripts" / "inbox-watch.sh"),
         "--project", str(project)],
        cwd=repo_root, capture_output=True, text=True, timeout=10, env=env,
    )

    result2 = subprocess.run(
        ["bash", str(repo_root / "scripts" / "inbox-watch.sh"),
         "--project", str(project)],
        cwd=repo_root, capture_output=True, text=True, timeout=10, env=env,
    )

    assert "already running" not in result2.stdout.lower(), (
        "Lock must be released after cycle completes, but second cycle says 'already running'"
    )

    pid_file = tmp_path / "dispatch.pid"
    if pid_file.exists():
        for line in pid_file.read_text().strip().splitlines():
            try:
                os.kill(int(line.strip()), 9)
            except (ProcessLookupError, ValueError):
                pass
