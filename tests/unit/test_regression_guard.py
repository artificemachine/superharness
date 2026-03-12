from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "tester"], repo)
    (repo / "app.txt").write_text("base\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "base"], repo)
    return repo


def _commit(repo: Path, msg: str, file_path: str, content: str) -> None:
    p = repo / file_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _run(["git", "add", file_path], repo)
    _run(["git", "commit", "-m", msg], repo)


def _run_guard(repo_root: Path, repo: Path, *args: str) -> dict:
    script = repo_root / "scripts" / "regression-guard.py"
    proc = _run(["python3", str(script), "--json", *args], repo)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_regression_guard_flags_fix_without_nearby_tests(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: update parser", "app.txt", "fix1\n")
    _commit(repo, "chore: docs", "README.md", "docs\n")

    data = _run_guard(repo_root, repo, "--limit", "10", "--scan-depth", "20", "--window", "1")
    assert data["fix_commits"] == 1
    assert data["without_test_changes"] == 1
    assert data["without_test_samples"][0]["sha"]


def test_regression_guard_accepts_nearby_test_commit(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: race guard", "app.txt", "fix2\n")
    _commit(repo, "test: cover race guard", "tests/test_race.py", "def test_ok():\n    assert True\n")

    data = _run_guard(repo_root, repo, "--limit", "10", "--scan-depth", "20", "--window", "1")
    assert data["fix_commits"] == 1
    assert data["without_test_changes"] == 0


def test_regression_guard_window_parameter_changes_result(repo_root, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: parser", "app.txt", "fix3\n")
    _commit(repo, "test: parser", "tests/test_parser.py", "def test_parser():\n    assert True\n")

    strict = _run_guard(repo_root, repo, "--limit", "10", "--scan-depth", "20", "--window", "0")
    assert strict["fix_commits"] == 1
    assert strict["without_test_changes"] == 1

    relaxed = _run_guard(repo_root, repo, "--limit", "10", "--scan-depth", "20", "--window", "1")
    assert relaxed["fix_commits"] == 1
    assert relaxed["without_test_changes"] == 0
