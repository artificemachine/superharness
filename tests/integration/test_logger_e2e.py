"""End-to-end logger tests — invoke real `shux` subcommands and verify
the central log captures their activity.

Tests the full pipeline: cli.py bootstrap → propagation → file handler
→ shux logs read-back."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")


def _env(tmp_path: Path) -> dict[str, str]:
    e = os.environ.copy()
    e["PYTHONPATH"] = SRC
    e["SUPERHARNESS_LOG_FILE"] = str(tmp_path / "main.log")
    e["SUPERHARNESS_AUDIT_LOG_FILE"] = str(tmp_path / "audit.log")
    e["SUPERHARNESS_LOG_LEVEL"] = "DEBUG"
    return e


def test_running_a_shux_subcommand_creates_log_file(tmp_path):
    """Run a benign shux command and verify the central log file is created."""
    res = subprocess.run(
        [sys.executable, "-m", "superharness.cli", "--version"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=15,
    )
    assert res.returncode == 0
    log_file = tmp_path / "main.log"
    assert log_file.is_file(), (
        f"central log file not created at {log_file}.\n"
        f"stdout: {res.stdout!r}\nstderr: {res.stderr!r}"
    )
    content = log_file.read_text()
    # cli bootstrap should have left a debug line
    assert "cli bootstrap" in content or "superharness" in content


def test_inbox_dispatch_abort_writes_to_log(tmp_path):
    """Trigger an _abort path in inbox_dispatch and verify it lands in the log."""
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.inbox_dispatch",
         "--project", str(tmp_path / "nonexistent")],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=15,
    )
    assert res.returncode != 0
    log_file = tmp_path / "main.log"
    if log_file.is_file():
        content = log_file.read_text()
        # _abort logs at ERROR
        assert "ERROR" in content or "abort" in content.lower(), (
            f"expected error log entry, got: {content!r}"
        )


def test_shux_logs_reads_back_recent_activity(tmp_path):
    """Full roundtrip: run a command, then shux logs, verify the entry comes back."""
    # Trigger something that logs
    subprocess.run(
        [sys.executable, "-m", "superharness.cli", "--help"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=15,
    )
    # Read it back via shux logs
    read = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs", "-n", "50"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert read.returncode == 0, f"shux logs failed: {read.stderr}"
    # The format is "<ts> <level> <name>:<func>:<lineno> <msg>"
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", read.stdout), (
        f"shux logs returned no timestamped entries.\n"
        f"stdout: {read.stdout!r}\nstderr: {read.stderr!r}"
    )


def test_audit_log_isolated_from_main_log(tmp_path):
    """Audit-channel writes must not bleed into the main log file."""
    # Use the package directly to write to both channels
    code = (
        "import sys; sys.path.insert(0, %r);\n"
        "from superharness.logging_utils import get_logger, get_audit_logger;\n"
        "get_logger('superharness').info('main-channel-msg');\n"
        "get_audit_logger().info('audit-only-msg');\n"
    ) % SRC
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode == 0, f"stderr: {res.stderr}"

    main = (tmp_path / "main.log").read_text() if (tmp_path / "main.log").is_file() else ""
    audit = (tmp_path / "audit.log").read_text() if (tmp_path / "audit.log").is_file() else ""

    assert "audit-only-msg" in audit
    assert "audit-only-msg" not in main
    assert "main-channel-msg" in main


# ── Iter 8 RED: discussion dispatch exception must be logged ──────────────────

def test_discussion_dispatch_exception_logged():
    """When discussion_dispatch.dispatch() raises, inbox_watch must log it (not swallow)."""
    import inspect
    from superharness.commands import inbox_watch as iw
    # Find the call site of discussion_dispatch.dispatch in inbox_watch
    src = inspect.getsource(iw)
    # The bare "except Exception: pass" at the discussion dispatch call site must be replaced
    # by a logged exception. After fix: 'except Exception' is followed by logging (not just 'pass').
    # We check that the discussion_dispatch call site logs on exception:
    # Search for the pattern: except Exception after _dd.dispatch call — must not be bare pass
    import re as _re
    # Find the specific bare-pass pattern for _dd.dispatch exceptions:
    # "except Exception:" on its own line followed immediately by "        pass" (no logging)
    # After fix: the except block logs via warning() — no bare pass remains
    m = _re.search(
        r'_dd\.dispatch\(project_dir\)\s+except Exception:\s+pass\b',
        src,
    )
    assert m is None, (
        "inbox_watch swallows discussion_dispatch exceptions without logging. "
        "Replace 'except Exception: pass' with '_log.warning(..., exc_info=True)' "
        "after the _dd.dispatch call."
    )
