"""Unit tests for live task log feature (feat.live-task-log).

RED phase: Write failing tests first.
"""

from __future__ import annotations

import json
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest








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




@pytest.mark.skipif(
    sys.platform == "win32", reason="script PTY wrapper is unavailable on Windows"
)
def test_launcher_log_receives_forwarded_child_output(tmp_path: Path) -> None:
    """The dispatch-style PTY log records output forwarded by launch_agent."""
    child = tmp_path / "child.py"
    child.write_text("print('fixture launcher output')\n", encoding="utf-8")
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "from superharness.engine.platform_runtime import launch_agent\n"
        "import sys\n"
        f"raise SystemExit(launch_agent([sys.executable, {str(child)!r}], cwd={str(tmp_path)!r}))\n",
        encoding="utf-8",
    )
    log_file = tmp_path / "launcher.log"
    if platform.system() == "Darwin":
        script_args = [
            "script",
            "-q",
            "-F",
            str(log_file),
            sys.executable,
            str(launcher),
        ]
    else:
        script_args = [
            "script",
            "-q",
            "-f",
            "-c",
            shlex.join([sys.executable, str(launcher)]),
            str(log_file),
        ]

    result = subprocess.run(
        script_args,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert log_file.read_text(encoding="utf-8").count("fixture launcher output") == 1
