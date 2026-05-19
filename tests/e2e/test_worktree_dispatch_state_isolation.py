"""E2E regression tests — worktree dispatch state isolation (v1.62.1).

Bug: when auto-dispatch creates a git worktree (dirty main tree),
inbox_dispatch passed the worktree path to delegate.py via --project.
db.get_connection hashed the worktree path → different XDG directory →
empty database → task not found → status='' → Gate 5 fires exit 2 →
permanent block → task stuck in waiting_input after 3 retries.

Fix: inbox_dispatch._prepare_launch_context sets SUPERHARNESS_STATE_PROJECT
to the original project path in spawn_env whenever ctx.worktree_dir is set.
db.get_connection prefers this env var for XDG hash resolution.

These tests validate the fix end-to-end at the component boundary level:
- E2E-1: spawn_env carries SUPERHARNESS_STATE_PROJECT when worktree active
- E2E-2: spawn_env does NOT carry SUPERHARNESS_STATE_PROJECT without worktree
- E2E-3: delegate can resolve task from original DB via env var (full path)
- E2E-4: get_connection env var takes priority over project_dir for XDG hash
- E2E-5: env var is cleared between dispatches (no cross-task leakage)
"""
from __future__ import annotations

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dispatch_ctx(project_dir: str, worktree_dir: str | None = None):
    """Build a minimal DispatchContext for _prepare_launch_context."""
    from superharness.commands.inbox_dispatch import DispatchContext

    ctx = DispatchContext(
        project_dir=project_dir,
        inbox_file=str(Path(project_dir) / ".superharness" / "inbox.yaml"),
        contract_file=str(Path(project_dir) / ".superharness" / "contract.yaml"),
        print_only=False,
        non_interactive=True,
        codex_bypass=False,
        launcher_timeout=300,
        script_dir="",
        sqlite_primary=True,
        target_filter=None,
    )
    ctx.item_to = "claude-code"
    ctx.item_task = "task-e2e-test"
    ctx.item_id = "inbox-e2e-001"
    ctx.task_log = str(Path(project_dir) / ".superharness" / "launcher-logs" / "test.log")
    ctx.worktree_dir = worktree_dir
    ctx.exec_project = worktree_dir or project_dir
    ctx.launch_args = ["echo", "noop"]
    return ctx


def _seed_task(project_dir: str, task_id: str) -> None:
    """Insert a todo task directly into the project's SQLite database."""
    from superharness.engine.db import get_connection, init_db

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tasks "
            "(id, title, owner, status, workflow, created_at) VALUES (?,?,?,?,?,?)",
            (task_id, "E2E test task", "claude-code", "todo",
             "implementation", "2026-05-19T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# E2E-1: spawn_env carries SUPERHARNESS_STATE_PROJECT when worktree is set
# ---------------------------------------------------------------------------

def test_spawn_env_contains_state_project_when_worktree_active(tmp_path: Path) -> None:
    """_prepare_launch_context must inject SUPERHARNESS_STATE_PROJECT into
    spawn_env whenever ctx.worktree_dir is set."""
    project = tmp_path / "real_project"
    project.mkdir()
    (project / ".superharness").mkdir()

    worktree = tmp_path / "worktree"
    worktree.mkdir()

    from superharness.commands.inbox_dispatch import _prepare_launch_context

    ctx = _make_dispatch_ctx(str(project), worktree_dir=str(worktree))
    _prepare_launch_context(ctx)

    assert "SUPERHARNESS_STATE_PROJECT" in ctx.spawn_env, (
        "SUPERHARNESS_STATE_PROJECT must be present in spawn_env when "
        "ctx.worktree_dir is set — delegate needs it to hash the correct path"
    )
    assert ctx.spawn_env["SUPERHARNESS_STATE_PROJECT"] == str(project), (
        f"Expected original project path {project}, "
        f"got {ctx.spawn_env['SUPERHARNESS_STATE_PROJECT']!r}"
    )


# ---------------------------------------------------------------------------
# E2E-2: spawn_env does NOT inject SUPERHARNESS_STATE_PROJECT without worktree
# ---------------------------------------------------------------------------

def test_spawn_env_omits_state_project_without_worktree(tmp_path: Path) -> None:
    """Without a worktree, SUPERHARNESS_STATE_PROJECT must not appear in
    spawn_env (don't override normal dispatch that already uses the real path)."""
    project = tmp_path / "real_project"
    project.mkdir()
    (project / ".superharness").mkdir()

    from superharness.commands.inbox_dispatch import _prepare_launch_context

    ctx = _make_dispatch_ctx(str(project), worktree_dir=None)
    _prepare_launch_context(ctx)

    assert "SUPERHARNESS_STATE_PROJECT" not in ctx.spawn_env, (
        "SUPERHARNESS_STATE_PROJECT must NOT appear in spawn_env when "
        "no worktree is active — it would override a valid project path"
    )


# ---------------------------------------------------------------------------
# E2E-3: state_reader.get_task resolves via env var from worktree path
# ---------------------------------------------------------------------------

def test_state_reader_get_task_via_state_project_env(tmp_path: Path) -> None:
    """state_reader.get_task called with a worktree path must still find the
    task when SUPERHARNESS_STATE_PROJECT points at the real project."""
    real_project = tmp_path / "real"
    real_project.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    _seed_task(str(real_project), "task-state-reader-e2e")

    from superharness.engine import state_reader

    # Without env var: task is not found (different XDG hash)
    task_without = state_reader.get_task(str(worktree), "task-state-reader-e2e")
    assert task_without is None, (
        "Without SUPERHARNESS_STATE_PROJECT, the worktree path must NOT "
        "find the task — this proves the hashes differ"
    )

    # With env var: task resolves correctly
    old = os.environ.get("SUPERHARNESS_STATE_PROJECT")
    try:
        os.environ["SUPERHARNESS_STATE_PROJECT"] = str(real_project)
        task_with = state_reader.get_task(str(worktree), "task-state-reader-e2e")
        assert task_with is not None, (
            "With SUPERHARNESS_STATE_PROJECT set, state_reader.get_task must "
            "find the task in the real project's database"
        )
        assert task_with["status"] == "todo"
        assert task_with["owner"] == "claude-code"
    finally:
        if old is None:
            os.environ.pop("SUPERHARNESS_STATE_PROJECT", None)
        else:
            os.environ["SUPERHARNESS_STATE_PROJECT"] = old


# ---------------------------------------------------------------------------
# E2E-4: get_connection prefers env var over project_dir for XDG hash
# ---------------------------------------------------------------------------

def test_get_connection_env_var_takes_priority_over_project_dir(tmp_path: Path) -> None:
    """When SUPERHARNESS_STATE_PROJECT is set, get_connection must open the
    database at the env-var path's XDG location, not the project_dir's."""
    real_project = tmp_path / "real"
    real_project.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    from superharness.engine.db import get_connection, init_db

    # Seed real project DB with a sentinel value
    conn_r = get_connection(str(real_project))
    init_db(conn_r)
    conn_r.execute(
        "INSERT OR IGNORE INTO tasks (id, title, owner, status, workflow, created_at) "
        "VALUES ('sentinel', 'Sentinel', 'x', 'todo', 'implementation', '2026-01-01T00:00:00Z')"
    )
    conn_r.commit()
    conn_r.close()

    old = os.environ.get("SUPERHARNESS_STATE_PROJECT")
    try:
        os.environ["SUPERHARNESS_STATE_PROJECT"] = str(real_project)
        conn_via = get_connection(str(worktree))
        init_db(conn_via)
        row = conn_via.execute(
            "SELECT id FROM tasks WHERE id='sentinel'"
        ).fetchone()
        assert row is not None, (
            "get_connection with SUPERHARNESS_STATE_PROJECT must open the "
            "real project's DB and find the sentinel task"
        )
        conn_via.close()
    finally:
        if old is None:
            os.environ.pop("SUPERHARNESS_STATE_PROJECT", None)
        else:
            os.environ["SUPERHARNESS_STATE_PROJECT"] = old


# ---------------------------------------------------------------------------
# E2E-5: env var isolation — no leakage between consecutive dispatches
# ---------------------------------------------------------------------------

def test_state_project_env_var_not_leaked_between_dispatches(tmp_path: Path) -> None:
    """Two consecutive _prepare_launch_context calls must not cross-contaminate:
    dispatch A (with worktree) injects the var; dispatch B (no worktree) must
    NOT see A's value in its own spawn_env."""
    project_a = tmp_path / "proj_a"
    project_a.mkdir()
    (project_a / ".superharness").mkdir()
    worktree_a = tmp_path / "wt_a"
    worktree_a.mkdir()

    project_b = tmp_path / "proj_b"
    project_b.mkdir()
    (project_b / ".superharness").mkdir()

    from superharness.commands.inbox_dispatch import _prepare_launch_context

    ctx_a = _make_dispatch_ctx(str(project_a), worktree_dir=str(worktree_a))
    _prepare_launch_context(ctx_a)
    assert "SUPERHARNESS_STATE_PROJECT" in ctx_a.spawn_env

    ctx_b = _make_dispatch_ctx(str(project_b), worktree_dir=None)
    _prepare_launch_context(ctx_b)

    assert "SUPERHARNESS_STATE_PROJECT" not in ctx_b.spawn_env, (
        "dispatch B (no worktree) must not inherit SUPERHARNESS_STATE_PROJECT "
        "from dispatch A — spawn_env is built fresh each time"
    )
    # Also verify the process-level env was not mutated
    assert os.environ.get("SUPERHARNESS_STATE_PROJECT") != str(project_a), (
        "_prepare_launch_context must not write to os.environ directly — "
        "only to ctx.spawn_env"
    )
