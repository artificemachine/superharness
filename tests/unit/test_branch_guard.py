from __future__ import annotations

import json

import pytest

from tests.helpers import parse_json_output, run_bash
import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


@pytest.mark.parametrize(
    ("command", "decision"),
    [
        ("git push origin main", "deny"),
        ("git push origin master", "deny"),
        ("git push --force origin feature", "deny"),
        ("git reset --hard HEAD~1", "ask"),
        ("git clean -f", "ask"),
        ("rm -rf /tmp/demo", "ask"),
        ("git status", "allow"),
    ],
)
def test_branch_guard_decisions(
    repo_root, tmp_path, command: str, decision: str
) -> None:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    payload = json.dumps({"tool_input": {"command": command}})

    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    # New Claude Code PreToolUse schema: hookSpecificOutput.permissionDecision
    assert output["hookSpecificOutput"]["permissionDecision"] == decision


def _decide(repo_root, cwd, command: str) -> str:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    result = run_bash(
        script, cwd=cwd, stdin=json.dumps({"tool_input": {"command": command}})
    )
    assert result.returncode == 0, result.stderr
    return parse_json_output(result.stdout)["hookSpecificOutput"]["permissionDecision"]


def _repo_on_branch(tmp_path, branch: str):
    """A real repo whose checked-out branch the guard can resolve."""
    import subprocess

    project = tmp_path / branch.replace("/", "-")
    project.mkdir()

    def run(*args):
        subprocess.run(["git", *args], cwd=project, capture_output=True, check=True)

    run("init", "-q")
    run("config", "user.email", "t@t.com")
    run("config", "user.name", "t")
    run("config", "core.hooksPath", "/dev/null")
    (project / "f.txt").write_text("x\n")
    run("add", "f.txt")
    run("-c", "commit.gpgsign=false", "commit", "-qm", "base", "--no-verify")
    run("checkout", "-q", "-B", branch)
    return project


@pytest.mark.parametrize(
    "command",
    [
        # A push of a feature branch, with the protected name appearing later in an
        # unrelated segment. The old regex spanned shell separators and denied these.
        'git push -u origin docs/notes; echo "release commit on main"',
        'git push -u origin fix/x && gh pr create --body "never push directly to main/master"',
        # Branch whose name merely contains the protected one.
        "git push origin feat/main-entry",
        "git push -u origin fix/some-branch",
    ],
)
def test_feature_branch_pushes_are_not_blocked(
    repo_root, tmp_path, command: str
) -> None:
    """Regression: the guard must judge the push target, not the command string."""
    assert _decide(repo_root, tmp_path, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        # Colon refspecs carry no whitespace before the branch name, so the old
        # `\\s(main|master)\\b` pattern never matched them.
        "git push origin HEAD:main",
        "git push origin +HEAD:master",
        "git push origin HEAD:refs/heads/main",
        # A push hidden behind an earlier command.
        "echo start; git push origin main",
    ],
)
def test_disguised_pushes_to_protected_branches_are_blocked(
    repo_root, tmp_path, command: str
) -> None:
    """Regression: these all reached main under the previous regex."""
    assert _decide(repo_root, tmp_path, command) == "deny"


def test_bare_push_from_protected_branch_is_blocked(repo_root, tmp_path) -> None:
    """The command names no branch at all, so only resolving HEAD catches it."""
    project = _repo_on_branch(tmp_path, "main")
    assert _decide(repo_root, project, "git push") == "deny"


def test_bare_push_from_feature_branch_is_allowed(repo_root, tmp_path) -> None:
    project = _repo_on_branch(tmp_path, "fix/thing")
    assert _decide(repo_root, project, "git push") == "allow"


def test_force_with_lease_is_allowed(repo_root, tmp_path) -> None:
    assert (
        _decide(repo_root, tmp_path, "git push --force-with-lease origin fix/x")
        == "allow"
    )


def test_gitlab_mirror_remote_is_allowed(repo_root, tmp_path) -> None:
    """LAN mirror (gitlab.gs) is private and never internet-facing."""
    assert _decide(repo_root, tmp_path, "git push gitlab main") == "allow"
