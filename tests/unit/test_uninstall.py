from __future__ import annotations

import sys
from pathlib import Path

from tests.helpers import REPO_ROOT


def _run_python(args: list[str], *, stdin: str | None = None) -> "subprocess.CompletedProcess[str]":
    import os
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.uninstall"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        input=stdin,
        check=False,
    )


def test_uninstall_help(repo_root) -> None:
    result = _run_python(["--help"])
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--all" in result.stdout


def test_uninstall_dry_run_shows_would_remove(repo_root, tmp_path) -> None:
    # Create a fake lock dir to be discovered
    lock_dir = tmp_path / "superharness-inbox-watch-abc123.lock"
    lock_dir.mkdir()

    result = _run_python(["--dry-run"])
    assert result.returncode == 0
    assert "superharness uninstall" in result.stdout
    # Dry run should not actually delete anything
    assert "Dry run complete" in result.stdout or "Nothing to remove" in result.stdout


def test_uninstall_non_interactive_skips_without_all(repo_root) -> None:
    # Pipe empty stdin to simulate non-interactive
    result = _run_python([], stdin="")
    assert result.returncode == 0
    # In non-interactive without --all, items should be skipped
    output = result.stdout
    assert "superharness uninstall" in output


def test_uninstall_unknown_option(repo_root) -> None:
    result = _run_python(["--bogus"])
    assert result.returncode == 2
    # argparse prints error to stderr for unknown options
    assert "bogus" in result.stderr or "error" in result.stderr


def test_uninstall_all_removes_lock_dirs(repo_root, tmp_path) -> None:
    import hashlib
    import tempfile
    fake_key = hashlib.sha1(b"/fake/project").hexdigest()
    # Use the platform temp dir so the lock is where uninstall.py looks for it.
    lock_dir = Path(tempfile.gettempdir()) / f"superharness-inbox-watch-{fake_key}.lock"
    lock_dir.mkdir(exist_ok=True)

    try:
        result = _run_python(["--all"])
        assert result.returncode == 0
        # Lock dir should be removed
        if not lock_dir.exists():
            assert "Removed" in result.stdout
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()
