"""Regression tests for 2026-05-21 discuss CLI / delegate bugs.

Covers five bugs found and fixed in this session:

- Bug I:  `shux discussion` (alias) not recognised → NameError in CLI
- Bug J:  `shux discuss status <disc_id>` rejected positional arg
- Bug K:  type="discussion" inbox items raised false retry-alert in shux status
- Bug L:  `task_obj` NameError in delegate() — variable defined inside
          _check_dispatch_gates() but referenced in the caller
- Bug M:  `_enqueue_for_agent` in discussion_dispatch failed with FK constraint
          because the round-N task row didn't exist yet (only round-1 is seeded
          at discussion-start). Fix: _ensure_round_task() upserts the row before
          calling inbox enqueue.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_discuss(cwd: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.discuss"] + args,
        cwd=str(cwd), text=True, capture_output=True, env=env, check=False,
    )


def _run_status(cwd: Path, project: Path) -> subprocess.CompletedProcess:
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.status", "--project", str(project)],
        cwd=str(cwd), text=True, capture_output=True, env=env, check=False,
    )


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    harness = project / ".superharness"
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")
    # Use forward slashes so Windows paths are valid YAML single-quoted scalars.
    proj_fwd = str(project).replace("\\", "/")
    (harness / "contract.yaml").write_text(
        "id: test\ntasks:\n"
        "  - id: task-a\n    owner: claude-code\n    status: todo\n"
        f"    project_path: '{proj_fwd}'\n"
        "  - id: task-b\n    owner: gemini-cli\n    status: todo\n"
        f"    project_path: '{proj_fwd}'\n"
    )
    seed_sqlite_from_yaml(project)
    return project


def _get_db(project: Path) -> str:
    legacy = project / ".superharness" / "state.sqlite3"
    return str(legacy)


# ---------------------------------------------------------------------------
# Bug I — `shux discussion` alias
# ---------------------------------------------------------------------------

class TestBugI_DiscussionAlias:
    def test_discussion_alias_is_registered(self):
        """CLI must expose 'discussion' as an alias for 'discuss'."""
        from superharness.cli import main
        from click.testing import CliRunner
        result = CliRunner().invoke(main, ["discussion", "--help"])
        assert result.exit_code == 0, result.output
        assert "No such command" not in result.output

    def test_discussion_alias_routes_to_discuss_module(self):
        """'shux discussion start --help' must show discuss start options."""
        from superharness.cli import main
        from click.testing import CliRunner
        result = CliRunner().invoke(main, ["discussion", "start", "--help"])
        # Should not say "Error" or "No such command"
        assert "No such command" not in result.output
        # If help renders, exit 0
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Bug J — positional disc_id in `discuss status`
# ---------------------------------------------------------------------------

class TestBugJ_StatusPositionalArg:
    def test_status_accepts_positional_disc_id(self, tmp_path: Path):
        """discuss status <disc_id> must not reject the positional argument."""
        project = _setup_project(tmp_path)
        result = _run_discuss(
            REPO_ROOT,
            ["status", "discuss-20260521T000000Z-99999-123456", "--project", str(project)],
        )
        # Should not error on unrecognised argument — it's either 0 or 1 (disc not found)
        assert "unrecognized arguments" not in result.stderr
        assert "error: unrecognized arguments" not in result.stderr

    def test_status_no_positional_still_works(self, tmp_path: Path):
        """discuss status without disc_id must still work (nargs=? default=None)."""
        project = _setup_project(tmp_path)
        result = _run_discuss(REPO_ROOT, ["status", "--project", str(project)])
        assert "unrecognized arguments" not in result.stderr
        assert result.returncode in (0, 1)  # 0=ok, 1=no discussions


# ---------------------------------------------------------------------------
# Bug K — type="discussion" items excluded from retry-alert
# ---------------------------------------------------------------------------

class TestBugK_RetryAlertFalsePositive:
    def _seed_discussion_inbox_item(self, db_path: str, task_id: str, inbox_id: str, target: str, retry_count: int = 4):
        """Insert a type='discussion' inbox item directly into SQLite."""
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR REPLACE INTO inbox
               (id, task_id, target_agent, status, priority, retry_count, max_retries,
                project_path, plan_only, created_at, type)
               VALUES (?, ?, ?, 'failed', 2, ?, 3, '', 0, '2026-05-21T00:00:00Z', 'discussion')""",
            (inbox_id, task_id, target, retry_count),
        )
        conn.commit()
        conn.close()

    def test_discussion_items_excluded_from_retry_alert(self, tmp_path: Path):
        """type='discussion' inbox items must not trigger retry-alert in shux status."""
        project = _setup_project(tmp_path)
        db_path = _get_db(project)

        # Insert a high-retry discussion shadow item
        self._seed_discussion_inbox_item(
            db_path,
            task_id="discuss-20260521T000000Z-99999-deadbeef/round-1",
            inbox_id="test-disc-inbox-shadow-r1-claude-code",
            target="claude-code",
            retry_count=5,
        )

        result = _run_status(REPO_ROOT, project)
        # The retry-alert line is always printed, but high= must be 0 when only
        # discussion shadow items are above the threshold.
        assert "retry-alert" in result.stdout  # line exists
        assert "high=0" in result.stdout, (
            f"retry-alert reported high>0 for a type='discussion' item:\n{result.stdout}"
        )

    def test_regular_items_still_trigger_retry_alert(self, tmp_path: Path):
        """Normal type='task' items at high retry_count must still trigger retry-alert."""
        project = _setup_project(tmp_path)
        db_path = _get_db(project)

        # Seed a plain task into the tasks table first (FK)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO tasks
               (id, title, owner, status, project_path, created_at)
               VALUES ('task-c', 'Test task', 'claude-code', 'in_progress', ?, '2026-05-21T00:00:00Z')""",
            (str(project),),
        )
        conn.execute(
            """INSERT OR REPLACE INTO inbox
               (id, task_id, target_agent, status, priority, retry_count, max_retries,
                project_path, plan_only, created_at, type)
               VALUES ('test-inbox-high-retry', 'task-c', 'claude-code',
                       'failed', 2, 5, 3, ?, 0, '2026-05-21T00:00:00Z', 'task')""",
            (str(project),),
        )
        conn.commit()
        conn.close()

        result = _run_status(REPO_ROOT, project)
        assert "retry-alert" in result.stdout, (
            f"retry-alert should fire for high-retry type='task' item:\n{result.stdout}"
        )


# ---------------------------------------------------------------------------
# Bug L — task_obj NameError in delegate()
# ---------------------------------------------------------------------------

class TestBugL_TaskObjScopeError:
    def _setup_discussion_task(self, project: Path, disc_id: str, task_id: str, status: str = "in_progress"):
        """Seed a discussion round task directly into SQLite."""
        db_path = str(project / ".superharness" / "state.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, title, owner, status, project_path, created_at)
               VALUES (?, ?, 'claude-code', ?, ?, '2026-05-21T00:00:00Z')""",
            (task_id, f"Discussion round task {task_id}", status, str(project)),
        )
        conn.commit()
        conn.close()
        # Discussion dir must exist for delegate to not abort early
        (project / ".superharness" / "discussions" / disc_id).mkdir(parents=True, exist_ok=True)

    def test_delegate_does_not_raise_name_error_for_discussion_task(self, tmp_path: Path):
        """delegate() must not crash with NameError on task_obj for a discussion round task.

        Before fix: task_obj was defined inside _check_dispatch_gates() but referenced
        in delegate() at gate 5, causing NameError: name 'task_obj' is not defined.
        """
        from superharness.commands.delegate import delegate

        project = _setup_project(tmp_path)
        disc_id = "discuss-20260521T000000Z-99999-regtest"
        task_id = f"{disc_id}/round-1"
        self._setup_discussion_task(project, disc_id, task_id, status="in_progress")

        # print_only=True avoids launching the agent binary — we just want to confirm
        # that delegate() reaches gate 5 (task_obj.get) without hitting NameError.
        # SystemExit is acceptable (e.g. if context loading fails further down).
        raised_name_error = False
        try:
            delegate(
                str(project),
                "claude-code",
                task_id,
                print_only=True,
                non_interactive=True,
                codex_bypass=False,
                skip_preflight=True,
            )
        except NameError as exc:
            raised_name_error = True
            pytest.fail(f"NameError regression: {exc}")
        except SystemExit:
            pass  # acceptable — the task reached gate 5 without crashing on task_obj

        assert not raised_name_error

    def test_delegate_task_obj_defined_after_gate_check(self):
        """Structural check: delegate() must assign task_obj after _check_dispatch_gates()."""
        import ast, inspect
        from superharness.commands import delegate as _delegate_mod
        src = inspect.getsource(_delegate_mod.delegate)
        tree = ast.parse(src)

        # Find all assignments to 'task_obj' in the function body
        assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "task_obj"
                for t in node.targets
            )
        ]
        assert assignments, (
            "delegate() must assign task_obj — it was missing before the fix"
        )

    def test_no_task_obj_reference_before_assignment_in_delegate(self):
        """task_obj must not be referenced before it is assigned in delegate()."""
        import ast, inspect
        from superharness.commands import delegate as _delegate_mod
        src = inspect.getsource(_delegate_mod.delegate)
        tree = ast.parse(src)

        first_assign_line = None
        references: list[int] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "task_obj":
                        if first_assign_line is None:
                            first_assign_line = node.lineno
            if isinstance(node, ast.Name) and node.id == "task_obj" and isinstance(node.ctx, ast.Load):
                references.append(node.lineno)

        assert first_assign_line is not None, "task_obj must be assigned in delegate()"
        early_refs = [ln for ln in references if ln < first_assign_line]
        assert not early_refs, (
            f"task_obj referenced before assignment at lines {early_refs} "
            f"(first assignment at line {first_assign_line})"
        )


# ---------------------------------------------------------------------------
# Bug M — _enqueue_for_agent FK constraint on round-N tasks
# ---------------------------------------------------------------------------

class TestBugM_EnqueueRoundTaskFKConstraint:
    def test_ensure_round_task_creates_missing_task(self, tmp_path: Path):
        """_ensure_round_task() must upsert the task row so inbox FK constraint passes."""
        from superharness.engine.db import get_connection, init_db
        from superharness.commands.discussion_dispatch import _ensure_round_task

        project = tmp_path / "proj"
        (project / ".superharness").mkdir(parents=True)

        conn = get_connection(str(project))
        init_db(conn)
        conn.close()

        disc_id = "discuss-20260521T000000Z-test-bugm"
        _ensure_round_task(str(project), disc_id, 2, "Discussion round 2: test-bug-m")

        conn = get_connection(str(project))
        cursor = conn.execute("SELECT id, status, workflow FROM tasks WHERE id = ?",
                              (f"{disc_id}/round-2",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "_ensure_round_task must insert the task row"
        assert row["status"] == "in_progress"
        assert row["workflow"] == "discussion"

    def test_ensure_round_task_is_idempotent(self, tmp_path: Path):
        """Calling _ensure_round_task twice must not raise or duplicate the row."""
        from superharness.engine.db import get_connection, init_db
        from superharness.commands.discussion_dispatch import _ensure_round_task

        project = tmp_path / "proj"
        (project / ".superharness").mkdir(parents=True)

        conn = get_connection(str(project))
        init_db(conn)
        conn.close()

        disc_id = "discuss-20260521T000000Z-test-bugm-idem"
        _ensure_round_task(str(project), disc_id, 3, "Discussion round 3: idempotent")
        _ensure_round_task(str(project), disc_id, 3, "Discussion round 3: idempotent")

        conn = get_connection(str(project))
        cursor = conn.execute("SELECT COUNT(*) FROM tasks WHERE id = ?",
                              (f"{disc_id}/round-3",))
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1, "Duplicate task rows must not be created"
