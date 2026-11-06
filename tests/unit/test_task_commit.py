"""commit_task_worktree keeps a finished task's work reachable, locally, off main."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from superharness.engine.task_commit import commit_task_worktree


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Hermetic git: ignore the developer's global config and hooks path.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def detached_wt(repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    # Mirrors dispatch: .superharness in the worktree links to the project state.
    state = tmp_path / "state"
    state.mkdir()
    os.symlink(state, wt / ".superharness")
    return wt


def test_git_ignored_files_are_neither_committed_nor_unsaved_work(
    repo: Path, detached_wt: Path
) -> None:
    """Contract: ignored files (caches, build output) are disposable."""
    from superharness.engine.task_commit import has_unsaved_work

    with open(repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("*.log\n")
    (detached_wt / "build.log").write_text("generated\n")

    assert has_unsaved_work(str(detached_wt)) is False
    result = commit_task_worktree(str(detached_wt), "feat.ign", "noop")
    assert result.outcome == "clean"
    assert _git(repo, "branch", "--list", "superharness/task/*") == ""


def test_dirty_detached_worktree_is_committed_on_a_task_branch(
    repo: Path, detached_wt: Path
) -> None:
    (detached_wt / "a.txt").write_text("two\n")
    main_before = _git(repo, "rev-parse", "main")

    result = commit_task_worktree(str(detached_wt), "feat.one", "Implement one")

    assert result.outcome == "committed"
    assert result.branch == "superharness/task/feat.one"
    assert not result.preserve_worktree
    assert _git(repo, "rev-parse", "main") == main_before
    assert _git(repo, "rev-parse", result.branch) == result.sha
    assert "Implement one" in _git(repo, "log", "-1", "--format=%B", result.branch)
    assert ".superharness" not in _git(
        repo, "ls-tree", "-r", "--name-only", result.branch
    )


def test_clean_detached_worktree_creates_nothing(repo: Path, detached_wt: Path) -> None:
    result = commit_task_worktree(str(detached_wt), "feat.two", "noop")

    assert result.outcome == "clean"
    assert _git(repo, "branch", "--list", "superharness/task/*") == ""


def test_commits_already_made_on_the_detached_head_are_kept(
    repo: Path, detached_wt: Path
) -> None:
    (detached_wt / "b.txt").write_text("b\n")
    _git(detached_wt, "add", "b.txt")
    _git(detached_wt, "commit", "-q", "-m", "agent commit")

    result = commit_task_worktree(str(detached_wt), "feat.three", "done")

    assert result.outcome == "branched"
    assert not result.preserve_worktree
    assert _git(repo, "rev-parse", result.branch) == _git(detached_wt, "rev-parse", "HEAD")


def test_protected_branch_is_never_committed_to(repo: Path) -> None:
    (repo / "a.txt").write_text("changed on main\n")
    head_before = _git(repo, "rev-parse", "HEAD")

    result = commit_task_worktree(str(repo), "feat.four", "no")

    assert result.outcome == "skipped"
    assert result.preserve_worktree
    assert _git(repo, "rev-parse", "HEAD") == head_before


def test_failing_commit_hook_preserves_the_worktree(
    repo: Path, detached_wt: Path
) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho blocked >&2\nexit 1\n")
    hook.chmod(0o755)
    (detached_wt / "a.txt").write_text("three\n")

    result = commit_task_worktree(str(detached_wt), "feat.five", "blocked")

    assert result.outcome == "failed"
    assert result.preserve_worktree
    assert "blocked" in result.message


def test_attached_feature_branch_is_never_committed_to(
    repo: Path, detached_wt: Path
) -> None:
    _git(detached_wt, "switch", "-q", "-c", "feature/x")
    feature_tip = _git(repo, "rev-parse", "feature/x")
    (detached_wt / "a.txt").write_text("two\n")

    result = commit_task_worktree(str(detached_wt), "feat.iso", "Implement iso")

    assert result.outcome == "committed"
    assert result.branch == "superharness/task/feat.iso"
    assert _git(repo, "rev-parse", "feature/x") == feature_tip
    assert _git(repo, "rev-parse", f"{result.branch}~1") == feature_tip
    assert _git(detached_wt, "symbolic-ref", "--short", "HEAD") == result.branch


def test_worktree_already_on_the_dedicated_branch_commits_there(
    repo: Path, detached_wt: Path
) -> None:
    _git(detached_wt, "switch", "-q", "-c", "superharness/task/feat.same")
    (detached_wt / "a.txt").write_text("two\n")

    result = commit_task_worktree(str(detached_wt), "feat.same", "Implement same")

    assert result.outcome == "committed"
    assert result.branch == "superharness/task/feat.same"
    assert _git(repo, "rev-parse", result.branch) == result.sha


def test_clean_attached_feature_branch_is_left_alone(
    repo: Path, detached_wt: Path
) -> None:
    _git(detached_wt, "switch", "-q", "-c", "feature/y")

    result = commit_task_worktree(str(detached_wt), "feat.clean2", "noop")

    assert result.outcome == "clean"
    assert _git(repo, "branch", "--list", "superharness/task/*") == ""


@pytest.mark.parametrize("task_id", ["", "bad id", "x;rm", "../escape", "a b/c"])
def test_unsafe_task_ids_are_refused(detached_wt: Path, task_id: str) -> None:
    (detached_wt / "a.txt").write_text("x\n")

    result = commit_task_worktree(str(detached_wt), task_id, "s")

    assert result.outcome == "skipped"
    assert result.preserve_worktree


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        # Off by default, whatever the autonomy.
        ({}, False),
        (None, False),
        ({"autonomy": "ai_driven"}, False),
        ({"autonomy": "supervised"}, False),
        # Only a real boolean true opts a project in.
        ({"auto_commit_tasks": True}, True),
        ({"autonomy": "supervised", "auto_commit_tasks": True}, True),
        ({"autonomy": "ai_driven", "auto_commit_tasks": False}, False),
        # Mistyped values are refused, never coerced to true.
        ({"auto_commit_tasks": "true"}, False),
        ({"auto_commit_tasks": "false"}, False),
        ({"auto_commit_tasks": "yes"}, False),
        ({"auto_commit_tasks": 1}, False),
        ({"auto_commit_tasks": ["true"]}, False),
    ],
)
def test_task_auto_commit_enabled(profile, expected) -> None:
    from superharness.engine.profile import task_auto_commit_enabled

    assert task_auto_commit_enabled(profile) is expected


def _project_with_profile(tmp_path: Path, profile_text: str | None) -> Path:
    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    if profile_text is not None:
        (project / ".superharness" / "profile.yaml").write_text(profile_text)
    return project


@pytest.mark.parametrize(
    "profile_text",
    ["auto_commit_tasks: true\n", "autonomy: supervised\nauto_commit_tasks: true\n"],
)
def test_close_commits_the_worktree_when_the_project_opts_in(
    repo: Path, detached_wt: Path, tmp_path: Path, profile_text
) -> None:
    from superharness.commands.close import commit_worktree_before_removal

    project = _project_with_profile(tmp_path, profile_text)
    (detached_wt / "a.txt").write_text("two\n")

    preserve = commit_worktree_before_removal(
        str(project), "feat.close", str(detached_wt), "Implement close"
    )

    assert preserve is False
    assert "Implement close" in _git(
        repo, "log", "-1", "--format=%B", "superharness/task/feat.close"
    )


@pytest.mark.parametrize(
    "profile_text",
    [
        None,
        "autonomy: ai_driven\n",
        "autonomy: supervised\n",
        "autonomy: ai_driven\nauto_commit_tasks: false\n",
        'auto_commit_tasks: "true"\n',
    ],
)
def test_close_leaves_the_worktree_alone_when_auto_commit_is_off(
    repo: Path, detached_wt: Path, tmp_path: Path, profile_text
) -> None:
    from superharness.commands.close import commit_worktree_before_removal

    project = _project_with_profile(tmp_path, profile_text)
    (detached_wt / "a.txt").write_text("two\n")

    preserve = commit_worktree_before_removal(
        str(project), "feat.off", str(detached_wt), "s"
    )

    assert preserve is True  # dirty and not committed: the worktree must stay
    assert _git(repo, "branch", "--list", "superharness/task/*") == ""
    assert _git(detached_wt, "status", "--porcelain", "--", "a.txt") != ""


def test_close_lets_a_clean_worktree_go_when_auto_commit_is_off(
    repo: Path, detached_wt: Path, tmp_path: Path
) -> None:
    from superharness.commands.close import commit_worktree_before_removal

    project = _project_with_profile(tmp_path, "autonomy: supervised\n")

    assert (
        commit_worktree_before_removal(str(project), "feat.clean", str(detached_wt), "s")
        is False
    )


def test_mistyped_flag_is_not_logged_verbatim(caplog) -> None:
    from superharness.engine.profile import task_auto_commit_enabled

    with caplog.at_level("WARNING"):
        assert task_auto_commit_enabled({"auto_commit_tasks": "secret-xyz"}) is False

    assert "secret-xyz" not in caplog.text
    assert "auto_commit_tasks" in caplog.text
    assert "str" in caplog.text


def test_close_preserves_the_worktree_when_the_commit_fails(
    repo: Path, detached_wt: Path, tmp_path: Path
) -> None:
    from superharness.commands.close import commit_worktree_before_removal

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    project = _project_with_profile(tmp_path, "auto_commit_tasks: true\n")
    (detached_wt / "a.txt").write_text("two\n")

    assert (
        commit_worktree_before_removal(str(project), "feat.fail", str(detached_wt), "s")
        is True
    )
