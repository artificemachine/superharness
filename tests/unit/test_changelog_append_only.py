from __future__ import annotations

import subprocess
from pathlib import Path

from tests.helpers import run_bash


def _init_repo(tmp_path: Path) -> Path:
    """Create a git repo with an initial CHANGELOG.md commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    changelog = repo / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\nInitial entry.\n")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    return repo


def test_append_only_passes(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    changelog = repo / "CHANGELOG.md"
    # Append new content
    with open(changelog, "a") as f:
        f.write("\nNew entry appended.\n")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=repo, capture_output=True, check=True)

    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo, args=["--staged"])
    assert result.returncode == 0


def test_append_only_fails_on_edit(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    changelog = repo / "CHANGELOG.md"
    # Modify existing content (not append-only)
    changelog.write_text("# Changelog\n\nModified entry.\n")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=repo, capture_output=True, check=True)

    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo, args=["--staged"])
    assert result.returncode == 1
    assert "changed existing content" in result.stderr


def test_append_only_fails_on_shrink(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    changelog = repo / "CHANGELOG.md"
    # Shrink file
    changelog.write_text("# Changelog\n")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=repo, capture_output=True, check=True)

    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo, args=["--staged"])
    assert result.returncode == 1
    assert "not append-only" in result.stderr


def test_append_only_skips_unstaged(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    # Don't stage anything
    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo, args=["--staged"])
    assert result.returncode == 0  # nothing staged, passes


def test_append_only_help(repo_root) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo_root, args=["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_append_only_base_ref_mode(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    changelog = repo / "CHANGELOG.md"
    # Make a second commit with appended content
    with open(changelog, "a") as f:
        f.write("\nSecond entry.\n")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=repo, capture_output=True, check=True)

    # Get the first commit hash
    first_commit = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo, args=["--base-ref", first_commit])
    assert result.returncode == 0


def test_append_only_base_ref_with_head_ref(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    changelog = repo / "CHANGELOG.md"
    with open(changelog, "a") as f:
        f.write("\nBranch entry.\n")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "branch update"], cwd=repo, capture_output=True, check=True)

    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD~1"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(
        script,
        cwd=repo,
        args=["--base-ref", base_ref, "--head-ref", head_ref],
    )
    assert result.returncode == 0


def test_append_only_requires_mode(repo_root) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "check-changelog-append-only.sh"
    result = run_bash(script, cwd=repo_root, args=[])
    assert result.returncode == 2
    assert "required" in result.stderr.lower()
