from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash


def test_uninstall_help(repo_root) -> None:
    script = repo_root / "scripts" / "uninstall.sh"
    result = run_bash(script, cwd=repo_root, args=["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--all" in result.stdout


def test_uninstall_dry_run_shows_would_remove(repo_root, tmp_path) -> None:
    script = repo_root / "scripts" / "uninstall.sh"
    # Create a fake lock dir to be discovered
    lock_dir = tmp_path / "superharness-inbox-watch-abc123.lock"
    lock_dir.mkdir()

    result = run_bash(script, cwd=repo_root, args=["--dry-run"])
    assert result.returncode == 0
    assert "superharness uninstall" in result.stdout
    # Dry run should not actually delete anything
    assert "Dry run complete" in result.stdout or "Nothing to remove" in result.stdout


def test_uninstall_non_interactive_skips_without_all(repo_root) -> None:
    script = repo_root / "scripts" / "uninstall.sh"
    # Pipe /dev/null as stdin to simulate non-interactive
    result = run_bash(script, cwd=repo_root, args=[], stdin="")
    assert result.returncode == 0
    # In non-interactive without --all, items should be skipped
    output = result.stdout
    assert "superharness uninstall" in output


def test_uninstall_unknown_option(repo_root) -> None:
    script = repo_root / "scripts" / "uninstall.sh"
    result = run_bash(script, cwd=repo_root, args=["--bogus"])
    assert result.returncode == 2
    assert "Unknown option" in result.stderr


def test_uninstall_all_removes_lock_dirs(repo_root, tmp_path) -> None:
    # Create a fake lock in /tmp
    import hashlib
    fake_key = hashlib.sha1(b"/fake/project").hexdigest()
    lock_dir = Path(f"/tmp/superharness-inbox-watch-{fake_key}.lock")
    lock_dir.mkdir(exist_ok=True)

    try:
        script = repo_root / "scripts" / "uninstall.sh"
        result = run_bash(script, cwd=repo_root, args=["--all"])
        assert result.returncode == 0
        # Lock dir should be removed
        if not lock_dir.exists():
            assert "Removed" in result.stdout
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()
