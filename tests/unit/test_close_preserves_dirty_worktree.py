"""Closing a task must never delete a dispatch worktree that holds unsaved work."""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from superharness.commands.close import close_task
from superharness.engine import tasks_dao
from superharness.engine.db import get_connection, init_db

_TASK_ID = "feat.close-real"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


def _set_profile(project: Path, text: str) -> None:
    (project / ".superharness" / "profile.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def closing(clean_harness: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real git project plus a detached dispatch worktree bound to a task row."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    temp_root = tmp_path / "tmproot"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))

    project = clean_harness
    _git(project, "init", "-q", "-b", "main")
    _git(project, "config", "user.name", "Test")
    _git(project, "config", "user.email", "test@example.invalid")
    _git(project, "config", "commit.gpgsign", "false")
    (project / "a.txt").write_text("one\n")
    _git(project, "add", "a.txt")
    _git(project, "commit", "-q", "-m", "init")

    wt = temp_root / "superharness-worktrees" / "wt-close-real"
    wt.parent.mkdir()
    _git(project, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    os.symlink(project / ".superharness", wt / ".superharness")

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(str(project))
    try:
        init_db(conn)
        tasks_dao.upsert(
            conn,
            tasks_dao.TaskRow(
                id=_TASK_ID,
                title="Close real",
                owner="claude-code",
                status="report_ready",
                effort="low",
                project_path=str(project),
                development_method="tdd",
                acceptance_criteria=[],
                test_types=[],
                out_of_scope=[],
                definition_of_done=[],
                context="",
                tdd=None,
                version=1,
                created_at=now,
                updated_at=now,
                blocked_by=[],
                verified=True,
                worktree_path=str(wt),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return project, wt


def _close(project: Path) -> int:
    return close_task(
        str(project), _TASK_ID, actor="claude-code", summary="done", skip_verify=True
    )


def test_dirty_worktree_survives_close_when_auto_commit_is_off(closing) -> None:
    project, wt = closing
    (wt / "a.txt").write_text("unsaved\n")

    assert _close(project) == 0

    assert wt.is_dir()
    assert (wt / "a.txt").read_text() == "unsaved\n"
    assert _git(project, "branch", "--list", "superharness/task/*") == ""


@pytest.mark.parametrize(
    "profile_text",
    ['auto_commit_tasks: "true"\n', "auto_commit_tasks: 1\n", "autonomy: ai_driven\n"],
)
def test_dirty_worktree_survives_close_when_the_flag_is_refused(
    closing, profile_text: str
) -> None:
    project, wt = closing
    _set_profile(project, profile_text)
    (wt / "a.txt").write_text("unsaved\n")

    assert _close(project) == 0

    assert (wt / "a.txt").read_text() == "unsaved\n"


def test_dirty_worktree_survives_close_when_the_profile_is_unreadable(closing) -> None:
    project, wt = closing
    _set_profile(project, "auto_commit_tasks: [unclosed\n")
    (wt / "a.txt").write_text("unsaved\n")

    _close(project)

    assert (wt / "a.txt").read_text() == "unsaved\n"


def _agent_commits_on_detached_head(wt: Path) -> str:
    (wt / "b.txt").write_text("agent work\n")
    _git(wt, "add", "b.txt")
    _git(wt, "commit", "-q", "-m", "agent commit")
    return _git(wt, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "profile_text", [None, 'auto_commit_tasks: "true"\n', "auto_commit_tasks: false\n"]
)
def test_agent_commit_on_detached_head_survives_close_when_auto_commit_is_off(
    closing, profile_text
) -> None:
    project, wt = closing
    if profile_text is not None:
        _set_profile(project, profile_text)
    sha = _agent_commits_on_detached_head(wt)

    assert _close(project) == 0

    assert wt.is_dir()
    assert _git(wt, "rev-parse", "HEAD") == sha
    assert _git(project, "cat-file", "-t", sha) == "commit"


def test_agent_commit_is_kept_on_a_task_branch_when_the_project_opts_in(
    closing,
) -> None:
    project, wt = closing
    _set_profile(project, "auto_commit_tasks: true\n")
    sha = _agent_commits_on_detached_head(wt)

    assert _close(project) == 0

    assert not wt.exists()
    assert _git(project, "rev-parse", f"superharness/task/{_TASK_ID}") == sha


def test_close_never_advances_an_attached_feature_branch(closing) -> None:
    project, wt = closing
    _set_profile(project, "auto_commit_tasks: true\n")
    _git(wt, "switch", "-q", "-c", "feature/x")
    feature_tip = _git(project, "rev-parse", "feature/x")
    (wt / "a.txt").write_text("saved\n")

    assert _close(project) == 0

    assert not wt.exists()
    assert _git(project, "rev-parse", "feature/x") == feature_tip
    branch = f"superharness/task/{_TASK_ID}"
    assert _git(project, "show", f"{branch}:a.txt") == "saved"
    assert _git(project, "rev-parse", f"{branch}~1") == feature_tip


@pytest.mark.parametrize("profile_text", [None, "auto_commit_tasks: true\n"])
def test_git_ignored_files_are_disposable_at_close(closing, profile_text) -> None:
    """Contract: files git ignores (caches, build output) are neither committed
    nor kept, so a worktree that holds only those is removed."""
    project, wt = closing
    if profile_text is not None:
        _set_profile(project, profile_text)
    with open(project / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("*.log\n")
    (wt / "build.log").write_text("generated\n")
    # Only the ignored file differs from HEAD (the .superharness link is excluded
    # by the code under test, so it is excluded here too).
    assert _git(wt, "status", "--porcelain", "--", ".", ":(exclude).superharness") == ""

    assert _close(project) == 0

    assert not wt.exists()
    assert _git(project, "branch", "--list", "superharness/task/*") == ""


def test_clean_worktree_is_still_removed_when_auto_commit_is_off(closing) -> None:
    project, wt = closing

    assert _close(project) == 0

    assert not wt.exists()


def test_opted_in_project_commits_then_removes_the_worktree(closing) -> None:
    project, wt = closing
    _set_profile(project, "auto_commit_tasks: true\n")
    (wt / "a.txt").write_text("saved\n")

    assert _close(project) == 0

    assert not wt.exists()
    branch = f"superharness/task/{_TASK_ID}"
    assert _git(project, "show", f"{branch}:a.txt") == "saved"
