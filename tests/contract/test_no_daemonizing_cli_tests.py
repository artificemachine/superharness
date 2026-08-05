"""Regression guards for tests that exercise daemon-capable CLI commands."""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_operator_start_test_runs_in_foreground() -> None:
    """A CliRunner test must not fork a second pytest process on macOS."""
    source = (_REPO_ROOT / "tests/unit/test_dispatch_pending_bugs.py").read_text()

    assert re.search(
        r'runner\.invoke\(\s*start_cmd,\s*\[\s*"--project", str\(tmp_path\), '
        r'"--no-open", "--no-daemon"\s*\]',
        source,
    )
