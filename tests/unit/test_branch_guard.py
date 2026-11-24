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
        # A destructive operation is refused with its reason, never asked: an agent session has nobody at the
        # terminal, so a confirmation prompt only stalls it (SUPERHARNESS_CONFIRM_MODE, default "deny").
        ("git reset --hard HEAD~1", "deny"),
        ("git clean -f", "deny"),
        ("git clean -xdf", "deny"),
        ("git status", "allow"),
        # `checkout -- .` discards every change in the tree; a single path that starts with a dot does not.
        ("git checkout -- .", "deny"),
        ("git checkout -- ./", "deny"),
        ("cd repo && git checkout -- . && git status", "deny"),
        ("git checkout -- .gitleaks.toml", "allow"),
        ("cd repo && git checkout -- .gitignore && git diff", "allow"),
        # Text is data, not a command: quoted words are never judged as an operation.
        ('echo "undo with git reset --hard"', "allow"),
        ("git commit -m 'note: git checkout -- . discards everything'", "allow"),
        ("printf '%s\\n' 'rm -rf /' > notes.txt", "allow"),
        # rm -rf is refused on the filesystem root, a home or a top-level folder, not on any absolute path.
        ("rm -rf /", "deny"),
        ("rm -rf /*", "deny"),
        ("rm -rf ~", "deny"),
        ("rm -rf $HOME", "deny"),
        ("rm -fr /usr", "deny"),
        ("rm -r -f ..", "deny"),
        ("rm -rf /tmp/demo", "allow"),
        ("rm -rf build/", "allow"),
        # A command that does not parse and names a destructive operation is refused, not guessed.
        ("git reset --hard 'unbalanced", "deny"),
    ],
)
def test_branch_guard_decisions(
    repo_root, tmp_path, command: str, decision: str
) -> None:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    payload = json.dumps({"tool_input": {"command": command}})

    result = run_bash(script, cwd=tmp_path, stdin=payload, env={"SUPERHARNESS_CONFIRM_MODE": None})

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    # New Claude Code PreToolUse schema: hookSpecificOutput.permissionDecision
    assert output["hookSpecificOutput"]["permissionDecision"] == decision


def test_a_refusal_tells_the_agent_what_to_do_instead(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    payload = json.dumps({"tool_input": {"command": "git reset --hard HEAD~1"}})
    out = parse_json_output(run_bash(script, cwd=tmp_path, stdin=payload,
                                     env={"SUPERHARNESS_CONFIRM_MODE": None}).stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "reset --hard" in out["permissionDecisionReason"]
    assert "another way" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", ["git reset --hard HEAD~1", "rm -rf /", "git checkout -- ."])
def test_the_legacy_mode_still_asks(repo_root, tmp_path, command: str) -> None:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    payload = json.dumps({"tool_input": {"command": command}})
    out = run_bash(script, cwd=tmp_path, stdin=payload, env={"SUPERHARNESS_CONFIRM_MODE": "ask"})
    assert parse_json_output(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"


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
