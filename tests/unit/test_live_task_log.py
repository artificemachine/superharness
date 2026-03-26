"""Unit tests for live task log feature (feat.live-task-log).

RED phase: Write failing tests first.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest



@pytest.mark.skipif(sys.platform == "win32", reason="bash shell launcher not available on Windows")
def test_launcher_creates_log_file(tmp_path: Path):
    """Test that launching a task creates a log file in .superharness/launcher-logs/"""
    # Setup
    project = tmp_path / "project"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    log_dir = harness / "launcher-logs"
    log_dir.mkdir()

    contract = harness / "contract.yaml"
    contract.write_text("""id: test-contract
created: 2026-03-20
goal: Test
tasks:
- id: test-task
  owner: claude-code
  status: todo
""")

    inbox = harness / "inbox.yaml"
    inbox.write_text(f"""# Inbox
- id: test-item-1
  to: claude-code
  task: test-task
  project: {project}
  status: pending
  priority: 1
  retry_count: 0
  max_retries: 3
""")

    (harness / "handoffs").mkdir(exist_ok=True)
    handoff = harness / "handoffs" / "test-task-instructions.md"
    handoff.write_text("""---
task: test-task
to: claude-code
---
Test instructions
""")

    # Create a mock launcher that just echoes output
    # The dispatcher looks for delegate-to-claude.sh
    mock_launcher = tmp_path / "delegate-to-claude.sh"
    mock_launcher.write_text("""#!/bin/bash
echo "Starting agent..."
sleep 0.1
echo "Agent output line 1"
echo "Agent output line 2" >&2
echo "Done"
exit 0
""")
    mock_launcher.chmod(0o755)

    # Run dispatcher with mock launcher
    # This will fail until we implement log capture
    import os
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"  # Prepend mock launcher path
    env["SUPERHARNESS_SCRIPTS_DIR"] = str(tmp_path)
    env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"

    result = subprocess.run(
        [
            sys.executable, "-m", "superharness.commands.inbox_dispatch",
            "--project", str(project),
            "--launcher-timeout", "5",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    # Assert: Log file should exist
    log_files = list(log_dir.glob("test-task-claude-code-*.log"))
    assert len(log_files) == 1, f"Expected 1 log file, found {len(log_files)}"

    log_content = log_files[0].read_text()
    assert "Starting agent..." in log_content
    assert "Agent output line 1" in log_content
    assert "Done" in log_content


def test_api_task_log_endpoint_returns_log_content(tmp_path: Path):
    """Test /api/task-log endpoint returns log file content."""
    import importlib.util
    import threading
    import urllib.request
    import uuid

    # Setup project with log file
    project = tmp_path / "project"
    harness = project / ".superharness"
    log_dir = harness / "launcher-logs"
    log_dir.mkdir(parents=True)

    (harness / "contract.yaml").write_text("id: test\ntasks: []")
    (harness / "inbox.yaml").write_text("# inbox")
    (harness / "ledger.md").write_text("# ledger")

    # Create a mock log file
    log_file = log_dir / "feat-ui-claude-code-20260320T120000Z.log"
    log_file.write_text("""[2026-03-20 12:00:00] Starting agent
[2026-03-20 12:00:01] Processing task
[2026-03-20 12:00:02] Agent output line 1
[2026-03-20 12:00:03] Agent output line 2
[2026-03-20 12:00:04] Complete
""")

    # Load monitor-ui module
    repo_root = Path(__file__).parent.parent.parent
    monitor_script = repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui", monitor_script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Start server
    module.Handler.project_dir = project
    module.Handler.label = "test-project"
    module.Handler.refresh_seconds = 3
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"
    module.Handler.auth_token = f"test-{uuid.uuid4().hex}"

    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    # Test: Call /api/task-log endpoint
    try:
        url = f"{base_url}/api/task-log?task=feat-ui&agent=claude-code"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read())

        # Assertions
        assert data["task"] == "feat-ui"
        assert data["agent"] == "claude-code"
        assert data["exists"] is True
        assert "Agent output line 1" in data["content"]
        assert data["size_bytes"] > 0

    finally:
        server.shutdown()


def test_ui_polls_live_output_for_launched_task(tmp_path: Path):
    """Test that UI JavaScript polls for live output when task is launched."""
    import re

    # Load monitor-ui HTML source
    repo_root = Path(__file__).parent.parent.parent
    monitor_script = repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py"
    source = monitor_script.read_text()

    # Extract JavaScript code
    js_match = re.search(r"<script>(.*?)</script>", source, re.DOTALL)
    assert js_match, "Could not find <script> block in monitor-ui.py"
    js_code = js_match.group(1)

    # Verify polling logic exists
    # Should call /api/task-log when viewing a launched/running task
    assert "api/task-log" in js_code, "/api/task-log endpoint not called in JavaScript"
    assert "setInterval" in js_code or "setTimeout" in js_code, "No polling mechanism found"

    # Verify it checks task status before polling
    assert "launched" in js_code.lower() or "running" in js_code.lower(), "No status check for launched/running"


def test_log_file_rotation_keeps_last_5_launches(tmp_path: Path):
    """Test that old log files are cleaned up (keep last 5 per task+agent)."""
    log_dir = tmp_path / "launcher-logs"
    log_dir.mkdir()

    # Create 7 log files for same task+agent
    for i in range(7):
        log_file = log_dir / f"task-1-claude-code-2026032{i}T120000Z.log"
        log_file.write_text(f"Log {i}")
        time.sleep(0.01)  # Ensure different mtimes

    # Import rotation function (will fail until implemented)
    from superharness.commands.delegate import _rotate_launcher_logs

    _rotate_launcher_logs(log_dir, "task-1", "claude-code", keep=5)

    # Assert: Only 5 most recent files remain
    remaining = sorted(log_dir.glob("task-1-claude-code-*.log"))
    assert len(remaining) == 5

    # Verify oldest 2 were deleted
    assert not (log_dir / "task-1-claude-code-20260320T120000Z.log").exists()
    assert not (log_dir / "task-1-claude-code-20260321T120000Z.log").exists()


def test_api_task_log_handles_missing_file_gracefully(tmp_path: Path):
    """Test /api/task-log returns exists=false when log file doesn't exist."""
    import importlib.util
    import threading
    import urllib.request
    import uuid

    # Setup project with NO log files
    project = tmp_path / "project"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: test\ntasks: []")
    (harness / "inbox.yaml").write_text("# inbox")
    (harness / "ledger.md").write_text("# ledger")

    # Load and start server
    repo_root = Path(__file__).parent.parent.parent
    monitor_script = repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui", monitor_script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.Handler.project_dir = project
    module.Handler.label = "test"
    module.Handler.refresh_seconds = 3
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"
    module.Handler.auth_token = f"test-{uuid.uuid4().hex}"

    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address

    try:
        url = f"http://{host}:{port}/api/task-log?task=nonexistent&agent=claude-code"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read())

        assert data["exists"] is False
        assert data["content"] == ""
        assert data["log_file"] is None or data["log_file"] == ""

    finally:
        server.shutdown()
