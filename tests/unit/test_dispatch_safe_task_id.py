"""Regression test for launcher log path sanitization.

Task IDs such as `discuss-<uuid>/round-N` contain `/`. Unsanitized, they cause
`os.path.join(launcher_log_dir, f"{task_id}-...")` to resolve into a
nonexistent subdirectory, which made `script(1)` exit 1 and marked every
discussion round-1+ dispatch as failed. See docs/claude_superharness_review.md
section "Launcher log path corrupts on any task ID containing /".
"""
from __future__ import annotations

import os

from superharness.commands.inbox_dispatch import _safe_task_id_for_path


def test_plain_id_passes_through_unchanged():
    assert _safe_task_id_for_path("feat.simple-task") == "feat.simple-task"


def test_single_slash_is_sanitized():
    assert _safe_task_id_for_path("discuss-abc123/round-1") == "discuss-abc123_round-1"


def test_multiple_slashes_are_sanitized():
    assert _safe_task_id_for_path("a/b/c/d") == "a_b_c_d"


def test_parent_directory_escape_is_sanitized():
    assert _safe_task_id_for_path("..").find("..") == -1
    assert _safe_task_id_for_path("../../etc/passwd") == "_/_/etc/passwd".replace("/", "_")


def test_sanitized_id_yields_single_file_path():
    """The ONLY behavior that matters at dispatch time: after sanitization,
    os.path.dirname of the built log path must equal the launcher_log_dir.
    If this regresses, script(1) will fail because the parent dir is missing.
    """
    launcher_log_dir = "/tmp/launcher-logs"
    task_id = "discuss-20260424T115728Z-84915-223275561/round-1"
    safe = _safe_task_id_for_path(task_id)
    log_path = os.path.join(launcher_log_dir, f"{safe}-claude-code-20260424T120000Z.log")
    assert os.path.dirname(log_path) == launcher_log_dir, (
        f"log path escaped into subdirectory: {log_path}"
    )
    assert "/" not in safe, f"task id still contains slash after sanitization: {safe}"
