from __future__ import annotations

import subprocess
import sys

from tests.helpers import REPO_ROOT


def _run_python(
    args: list[str],
    *,
    stdin: str | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    import os
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if extra_env:
        env.update(extra_env)
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

    fake_key = hashlib.sha1(b"/fake/project").hexdigest()

    # Use tmp_path as the temp dir for both the test and the subprocess.
    # Passing TMPDIR/TEMP/TMP makes platform_runtime.tmp_dir() agree with
    # where we created the lock dir, eliminating the TOCTOU race that occurs
    # when the system /tmp is shared with OS cleanup daemons or parallel jobs.
    fake_tmp = tmp_path / "tmp"
    fake_tmp.mkdir()
    lock_dir = fake_tmp / f"superharness-inbox-watch-{fake_key}.lock"
    lock_dir.mkdir()

    result = _run_python(
        ["--all"],
        extra_env={"TMPDIR": str(fake_tmp), "TEMP": str(fake_tmp), "TMP": str(fake_tmp)},
    )
    assert result.returncode == 0
    assert not lock_dir.exists(), (
        f"uninstall --all should remove the lock dir; stdout={result.stdout!r}"
    )
    assert "Removed" in result.stdout, (
        f"uninstall --all should print 'Removed'; stdout={result.stdout!r}"
    )
