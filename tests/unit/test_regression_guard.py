from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Import regression-guard.py directly (hyphenated filename requires importlib)
def _load_guard():
    name = "regression_guard"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name,
        REPO_ROOT / "src" / "superharness" / "scripts" / "regression-guard.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


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
    script = repo_root / "src" / "superharness" / "scripts" / "regression-guard.py"
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


# ---------------------------------------------------------------------------
# Direct import tests — these get instrumented by pytest-cov
# ---------------------------------------------------------------------------

def test_commit_row_dataclass(tmp_path):
    rg = _load_guard()
    row = rg.CommitRow(sha="abc1234", message="fix: something")
    assert row.sha == "abc1234"
    assert row.message == "fix: something"


def test_recent_shas_returns_strings(repo_root):
    rg = _load_guard()
    shas = rg._recent_shas.__wrapped__(5) if hasattr(rg._recent_shas, "__wrapped__") else None
    # Run against the real repo via the function directly
    result = subprocess.run(
        ["git", "log", "--oneline", "-n5"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    expected_shas = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    # Just verify _recent_shas returns the right shape when called in repo context
    import os
    orig = os.getcwd()
    try:
        os.chdir(str(repo_root))
        shas = rg._recent_shas(5)
    finally:
        os.chdir(orig)
    assert isinstance(shas, list)
    assert all(isinstance(s, str) for s in shas)
    assert shas == expected_shas


def test_has_test_changes_true(tmp_path):
    rg = _load_guard()
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: something", "tests/test_x.py", "def test_x(): pass\n")
    sha = _run(["git", "log", "--oneline", "-n1"], repo).stdout.split()[0]
    import os
    orig = os.getcwd()
    try:
        os.chdir(str(repo))
        result = rg._has_test_changes(sha)
    finally:
        os.chdir(orig)
    assert result is True


def test_has_test_changes_false(tmp_path):
    rg = _load_guard()
    repo = _init_repo(tmp_path)
    _commit(repo, "chore: readme", "README.md", "docs\n")
    sha = _run(["git", "log", "--oneline", "-n1"], repo).stdout.split()[0]
    import os
    orig = os.getcwd()
    try:
        os.chdir(str(repo))
        result = rg._has_test_changes(sha)
    finally:
        os.chdir(orig)
    assert result is False


def test_git_log_returns_commit_rows(tmp_path):
    rg = _load_guard()
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: bug one", "app.txt", "v2\n")
    _commit(repo, "chore: docs", "README.md", "docs\n")
    import os
    orig = os.getcwd()
    try:
        os.chdir(str(repo))
        rows = rg._git_log(10, ["fix", "Fix"])
    finally:
        os.chdir(orig)
    assert len(rows) == 1
    assert rows[0].message == "fix: bug one"


def test_main_json_output(tmp_path):
    rg = _load_guard()
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: thing", "app.txt", "v3\n")
    _commit(repo, "test: thing", "tests/test_thing.py", "def test_t(): pass\n")
    import os
    orig = os.getcwd()
    captured = []
    try:
        os.chdir(str(repo))
        with patch("sys.argv", ["rg", "--json", "--limit", "10", "--scan-depth", "20"]):
            with patch("builtins.print", side_effect=lambda x: captured.append(x)):
                rc = rg.main()
    finally:
        os.chdir(orig)
    assert rc == 0
    data = json.loads(captured[0])
    assert data["fix_commits"] == 1
    assert data["without_test_changes"] == 0


def test_main_text_output(tmp_path):
    rg = _load_guard()
    repo = _init_repo(tmp_path)
    _commit(repo, "fix: unfixed", "app.txt", "v4\n")
    import os
    orig = os.getcwd()
    captured = []
    try:
        os.chdir(str(repo))
        with patch("sys.argv", ["rg", "--limit", "10", "--scan-depth", "20", "--window", "0"]):
            with patch("builtins.print", side_effect=lambda x: captured.append(x)):
                rc = rg.main()
    finally:
        os.chdir(orig)
    assert rc == 0
    assert any("fix_commits=1" in str(line) for line in captured)
    assert any("without_test_changes=1" in str(line) for line in captured)


def test_main_invalid_args_exits(tmp_path):
    rg = _load_guard()
    repo = _init_repo(tmp_path)
    import os
    orig = os.getcwd()
    try:
        os.chdir(str(repo))
        with patch("sys.argv", ["rg", "--limit", "0"]):
            with pytest.raises(SystemExit):
                rg.main()
    finally:
        os.chdir(orig)
