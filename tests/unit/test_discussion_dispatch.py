from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, run_cmd, seed_sqlite_from_yaml, seed_sqlite_heartbeat
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_discuss_py(cwd, args: list[str] | None = None):
    """Run discuss Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.discuss"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_dispatch_py(cwd, args: list[str] | None = None):
    """Run discussion_dispatch Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.discussion_dispatch"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_engine(repo_root: Path, args: list[str]):
    import sys
    return run_cmd([sys.executable, "-m", "superharness.engine.discussion"] + args, cwd=repo_root)


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj-discussion-dispatch"
    harness = project / ".superharness"
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused",
                "",
            ]
        )
        + "\n"
    )
    seed_sqlite_from_yaml(project)
    return project


def _start_discussion(repo_root: Path, project: Path, *, max_rounds: int = 2) -> Path:
    started = _run_engine(
        repo_root,
        [
            "start",
            "--discussions-dir",
            str(project / ".superharness" / "discussions"),
            "--topic",
            "Dispatcher test discussion",
            "--participant",
            "claude-code",
            "--participant",
            "codex-cli",
            "--max-rounds",
            str(max_rounds),
            "--project",
            str(project),
        ],
    )
    assert started.returncode == 0, started.stderr
    return Path(json.loads(started.stdout)["discussion_dir"])


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_discussion_dispatch_advances_and_enqueues_next_round(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    discussion_dir = _start_discussion(repo_root, project, max_rounds=2)

    s1 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "partial",
            "--position",
            "Need changes.",
        ],
    )
    assert s1.returncode == 0, s1.stderr

    s2 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "codex-cli",
            "--verdict",
            "disagree",
            "--position",
            "Not ready.",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "advanced to round 2" in dispatch.stdout
    assert "Enqueued round 2 for claude-code" in dispatch.stdout
    assert "Enqueued round 2 for codex-cli" in dispatch.stdout

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "active"
    assert status_json["current_round"] == 2

    # Inbox is SQLite-backed post-migration.
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    n = db.execute(
        "SELECT COUNT(*) FROM inbox WHERE task_id = ?",
        (status_json["id"] + "/round-2",),
    ).fetchone()[0]
    db.close()
    assert n == 2


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_discussion_dispatch_reenqueues_only_missing_pending_agents(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    discussion_dir = _start_discussion(repo_root, project, max_rounds=3)
    discussion_id = discussion_dir.name
    inbox_file = project / ".superharness" / "inbox.yaml"

    inbox_file.write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused",
                "",
                "- id: existing-claude-r1",
                "  to: claude-code",
                f"  task: {discussion_id}/round-1",
                f"  project: {project}",
                "  status: pending",
                "  priority: 1",
                "  retry_count: 0",
                "  max_retries: 3",
                "  created_at: 2026-03-12T00:00:00Z",
            ]
        )
        + "\n"
    )

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "Enqueued round 1 for codex-cli" in dispatch.stdout
    assert "Enqueued round 1 for claude-code" not in dispatch.stdout

    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    rows = db.execute(
        "SELECT target_agent FROM inbox WHERE task_id = ?",
        (f"{discussion_id}/round-1",),
    ).fetchall()
    db.close()
    targets = [r[0] for r in rows]
    assert len(rows) == 2
    assert targets.count("claude-code") == 1
    assert targets.count("codex-cli") == 1


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_discussion_dispatch_closes_max_rounds_without_enqueuing_next_round(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    discussion_dir = _start_discussion(repo_root, project, max_rounds=1)
    discussion_id = discussion_dir.name

    s1 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "agree",
            "--position",
            "Looks fine.",
        ],
    )
    assert s1.returncode == 0, s1.stderr

    s2 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "codex-cli",
            "--verdict",
            "disagree",
            "--position",
            "Needs rework.",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "closed (reason=max_rounds_reached, round=1)" in dispatch.stdout

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "no_consensus"

    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    n = db.execute(
        "SELECT COUNT(*) FROM inbox WHERE task_id = ?",
        (f"{discussion_id}/round-2",),
    ).fetchone()[0]
    db.close()
    assert n == 0


def _setup_project_with_contract(tmp_path: Path, owners: list[str] | None = None) -> Path:
    """Create a project with contract containing tasks for given owners."""
    if owners is None:
        owners = ["claude-code", "codex-cli"]
    project = tmp_path / "proj-discuss-start"
    harness = project / ".superharness"
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text("# inbox\n")
    tasks = []
    for i, owner in enumerate(owners):
        tasks.append(f"  - id: task-{i}\n    owner: {owner}\n    status: todo\n    project_path: \"{project}\"")
    contract = "id: test\ntasks:\n" + ("\n".join(tasks) if tasks else "") + "\n"
    (harness / "contract.yaml").write_text(contract)
    seed_sqlite_from_yaml(project)

    # Mock heartbeats for participants (v1.69.5 requirement)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    seed_sqlite_heartbeat(project, agent="watcher", status="alive", now=now)
    for owner in owners:
        if owner != "owner":
            seed_sqlite_heartbeat(project, agent=owner, status="alive", now=now)

    return project


def test_discuss_start_creates_contract_task_and_enqueues(repo_root, tmp_path) -> None:
    """discuss start creates a contract task for round-1 and enqueues both agents."""
    project = _setup_project_with_contract(tmp_path)

    result = _run_discuss_py(
        repo_root,
        args=["start", "--project", str(project), "--topic", "Test topic", "--max-rounds", "2"],
    )
    assert result.returncode == 0, result.stderr
    assert "Discussion started:" in result.stdout
    assert "Enqueued round 1 for claude-code" in result.stdout
    assert "Enqueued round 1 for codex-cli" in result.stdout

    # Verify contract task was created in SQLite (post-migration source of truth).
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    round_task = db.execute(
        "SELECT id, status FROM tasks WHERE id LIKE '%/round-1' LIMIT 1"
    ).fetchone()
    assert round_task is not None
    assert round_task[1] == "in_progress"

    # Both agents enqueued
    targets = [r[0] for r in db.execute(
        "SELECT target_agent FROM inbox WHERE task_id LIKE '%/round-1'"
    ).fetchall()]
    db.close()
    assert "claude-code" in targets
    assert "codex-cli" in targets


def test_discuss_start_proceeds_with_watcher_active(repo_root, tmp_path) -> None:
    """With watcher active, start succeeds even when few agent heartbeats are present."""
    project = _setup_project_with_contract(tmp_path, owners=["codex-cli"])

    result = _run_discuss_py(
        repo_root,
        args=["start", "--project", str(project), "--topic", "Watcher bypass test"],
    )
    # Iter 4: watcher active + PRIMARY_AGENTS ≥ 2 → proceed with warning, not 1
    assert result.returncode == 0, result.stderr
    assert "watcher is active" in result.stderr


def test_discuss_start_allows_explicit_owners_without_contract_owners(repo_root, tmp_path) -> None:
    """Explicit --owners should bypass the need for 2 distinct owners in the contract."""
    project = _setup_project_with_contract(tmp_path, owners=["codex-cli"])

    # Mock heartbeats for explicit participants
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    seed_sqlite_heartbeat(project, agent="claude-code", status="alive", now=now)

    result = _run_discuss_py(
        repo_root,
        args=[
            "start",
            "--project", str(project),
            "--topic", "Explicit owners",
            "--owners", "claude-code,codex-cli",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "Participants: claude-code codex-cli" in result.stdout

    # The round-1 task got created in SQLite (workflow=discussion is
    # inferred from the task id pattern via infer_workflow, not stored
    # as a column). Just check the round task exists.
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    n = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE id LIKE '%/round-1'"
    ).fetchone()[0]
    db.close()
    assert n >= 1


def test_discuss_start_rejects_no_owners_without_watcher(repo_root, tmp_path) -> None:
    """Without watcher, start fails when no agent heartbeats are present."""
    import sqlite3 as _sql
    project = _setup_project_with_contract(tmp_path, owners=[])
    # Nullify the watcher heartbeat so _watcher_is_alive returns False
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    db.execute("DELETE FROM agent_heartbeats WHERE agent = 'watcher'")
    db.commit()
    db.close()

    result = _run_discuss_py(
        repo_root,
        args=["start", "--project", str(project), "--topic", "Should fail"],
    )
    assert result.returncode == 1
    assert "At least 2 running agents are required" in result.stderr


def test_discuss_start_exclude_owner(repo_root, tmp_path) -> None:
    """discuss start --exclude removes an owner from participants."""
    project = _setup_project_with_contract(tmp_path, owners=["claude-code", "codex-cli", "gemini-cli", "opencode"])

    result = _run_discuss_py(
        repo_root,
        args=[
            "start", "--project", str(project), "--topic", "Exclude test",
            "--exclude", "codex-cli", "--max-rounds", "2",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "Discussion started:" in result.stdout
    participants_line = result.stdout.split("Participants:")[1].split("\n")[0]
    assert "claude-code" in participants_line
    assert "opencode" in participants_line
    assert "gemini-cli" in participants_line
    assert "codex-cli" not in participants_line
    assert "Enqueued round 1 for claude-code" in result.stdout
    assert "Enqueued round 1 for opencode" in result.stdout
    assert "Enqueued round 1 for gemini-cli" in result.stdout
    assert "codex-cli" not in result.stdout.split("Participants:")[1]

    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    targets = {r[0] for r in db.execute(
        "SELECT target_agent FROM inbox WHERE task_id LIKE '%/round-1'"
    ).fetchall()}
    db.close()
    assert "claude-code" in targets
    assert "opencode" in targets
    assert "gemini-cli" in targets
    assert "codex-cli" not in targets


def test_discuss_start_exclude_too_many_rejects_without_watcher(repo_root, tmp_path) -> None:
    """Without watcher, --exclude fails if fewer than 2 running agents remain."""
    import sqlite3 as _sql
    project = _setup_project_with_contract(tmp_path, owners=["claude-code", "codex-cli"])
    # Nullify watcher heartbeat so the gate stays hard
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    db.execute("DELETE FROM agent_heartbeats WHERE agent = 'watcher'")
    db.commit()
    db.close()

    result = _run_discuss_py(
        repo_root,
        args=[
            "start", "--project", str(project), "--topic", "Should fail",
            "--exclude", "codex-cli",
        ],
    )
    # watcher dead → hard reject when < 2 heartbeats
    assert result.returncode == 1
    assert "At least 2 running agents are required" in result.stderr


def test_discuss_start_filters_owner_from_participants(repo_root, tmp_path) -> None:
    """discuss start must silently drop 'owner' from participants.
    'owner' is a human role that is never dispatched via inbox and permanently
    blocks verdict collection and auto-consensus when included."""
    project = _setup_project_with_contract(
        tmp_path, owners=["claude-code", "codex-cli", "owner"]
    )
    # opencode is now a PRIMARY_AGENT (always included by default); seed its heartbeat
    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    seed_sqlite_heartbeat(project, agent="opencode", status="alive", now=_now)

    result = _run_discuss_py(
        repo_root,
        args=[
            "start", "--project", str(project),
            "--topic", "Filter owner test",
        ],
    )
    assert result.returncode == 0, result.stderr
    # Note about filtering must appear on stderr
    assert "owner" in result.stderr
    assert "not a registered AI agent" in result.stderr
    # Only AI agents in participants; opencode included as primary reasoner
    participants_line = result.stdout.split("Participants:")[1].split("\n")[0]
    assert "claude-code" in participants_line
    assert "opencode" in participants_line
    assert "codex-cli" in participants_line
    assert "owner" not in participants_line

    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    targets = {r[0] for r in db.execute(
        "SELECT target_agent FROM inbox WHERE task_id LIKE '%/round-1'"
    ).fetchall()}
    db.close()
    assert "claude-code" in targets
    assert "opencode" in targets
    assert "codex-cli" in targets
    assert "owner" not in targets


def test_discuss_start_explicit_owner_only_rejects(repo_root, tmp_path) -> None:
    """If --owners passes only 'owner' and one real agent, the filter leaves <2 AI
    agents and must return an error."""
    project = _setup_project_with_contract(tmp_path, owners=["claude-code"])

    result = _run_discuss_py(
        repo_root,
        args=[
            "start", "--project", str(project),
            "--topic", "Should fail",
            "--owners", "claude-code,owner",
        ],
    )
    # v1.69.5: returns 1 (only 1 running AI participant remains)
    assert result.returncode == 1
    assert "At least 2 running agents are required" in result.stderr


# ---------------------------------------------------------------------------
# _retry_agent — preserves retry_count + failed_reason on re-queue
# ---------------------------------------------------------------------------

class TestRetryAgent:
    """Tests that _retry_agent increments retry_count and preserves failed_reason."""

    def test_retry_increments_count(self, tmp_path):
        """_retry_agent increments retry_count on the existing failed row."""
        import sqlite3
        from superharness.commands.discussion_dispatch import _retry_agent
        from superharness.engine.db import init_db

        harness = tmp_path / ".superharness"
        harness.mkdir()
        db_path = harness / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_db(conn)

        # Seed a failed inbox row
        conn.execute("""
            INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, failed_reason, created_at)
            VALUES ('test-item', 'disc/round-1', 'gemini-cli', 'failed', 0, 3, 'timeout', '2026-01-01T00:00:00Z')
        """)
        conn.execute("INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES ('disc/round-1', 'Round 1', 'in_progress', '2026-01-01T00:00:00Z')")
        conn.commit()

        result = _retry_agent(str(tmp_path), 'gemini-cli', 'disc/round-1', 'disc', 1)
        assert result is True

        row = conn.execute("SELECT retry_count, failed_reason, status FROM inbox WHERE id='test-item'").fetchone()
        assert row["retry_count"] == 1
        assert "timeout" in (row["failed_reason"] or "")
        assert row["status"] == "pending"
        conn.close()

    def test_retry_exhausted_returns_false(self, tmp_path):
        """_retry_agent returns False when retry_count >= max_retries."""
        import sqlite3
        from superharness.commands.discussion_dispatch import _retry_agent
        from superharness.engine.db import init_db

        harness = tmp_path / ".superharness"
        harness.mkdir()
        db_path = harness / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_db(conn)

        conn.execute("""
            INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, failed_reason, created_at)
            VALUES ('exhausted-item', 'disc/round-1', 'gemini-cli', 'failed', 3, 3, 'timeout', '2026-01-01T00:00:00Z')
        """)
        conn.execute("INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES ('disc/round-1', 'Round 1', 'in_progress', '2026-01-01T00:00:00Z')")
        conn.commit()

        result = _retry_agent(str(tmp_path), 'gemini-cli', 'disc/round-1', 'disc', 1)
        assert result is False  # exhausted, can't retry
        conn.close()

    def test_no_failed_row_returns_false(self, tmp_path):
        """_retry_agent returns False when no failed row exists."""
        from superharness.commands.discussion_dispatch import _retry_agent
        result = _retry_agent(str(tmp_path), 'gemini-cli', 'disc/round-1', 'disc', 1)
        assert result is False

    def test_preserves_original_reason(self, tmp_path):
        """_retry_agent preserves the original failed_reason in the retry."""
        import sqlite3
        from superharness.commands.discussion_dispatch import _retry_agent
        from superharness.engine.db import init_db

        harness = tmp_path / ".superharness"
        harness.mkdir()
        db_path = harness / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_db(conn)

        conn.execute("""
            INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, failed_reason, created_at)
            VALUES ('reason-item', 'disc/round-1', 'codex-cli', 'failed', 1, 3, 'permanent block (lifecycle gate)', '2026-01-01T00:00:00Z')
        """)
        conn.execute("INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES ('disc/round-1', 'Round 1', 'in_progress', '2026-01-01T00:00:00Z')")
        conn.commit()

        result = _retry_agent(str(tmp_path), 'codex-cli', 'disc/round-1', 'disc', 1)
        assert result is True

        row = conn.execute("SELECT failed_reason, retry_count FROM inbox WHERE id='reason-item'").fetchone()
        assert "permanent block" in (row["failed_reason"] or "")
        assert row["retry_count"] == 2
        conn.close()


# ---------------------------------------------------------------------------
# Iter 1 — Route discussion rounds through delegate (kill forced session-inject)
# ---------------------------------------------------------------------------

class TestIter1SessionInjectGate:
    """Iter 1 RED tests: discussion rounds must route through _execute_agent,
    not through _write_discussion_prompt_file / _reconcile_session_inject."""

    def _setup_sqlite(self, tmp_path, disc_task: str) -> None:
        """Create minimal SQLite state with a pending discussion round inbox item."""
        from superharness.engine.db import get_connection, init_db

        conn = get_connection(str(tmp_path))
        init_db(conn)
        # Tasks must exist before inbox (FK constraint)
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, status, created_at) "
            "VALUES (?,?,?,?)",
            (disc_task, "Round 1", "in_progress", "2026-06-07T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, priority, "
            "retry_count, max_retries, created_at, project_path) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("item-iter1", disc_task, "claude-code", "pending", 5, 0, 3,
             "2026-06-07T00:00:00Z", str(tmp_path)),
        )
        conn.commit()
        conn.close()

    def test_round_dispatch_spawns_delegate(self, tmp_path, monkeypatch):
        """Dispatching a discussion round must call _execute_agent (delegate path).
        Session-injection path has been removed; _execute_agent is the only path."""
        from unittest.mock import patch

        monkeypatch.delenv("SUPERHARNESS_SESSION_INJECT_ENABLED", raising=False)

        disc_task = "discuss-iter1test20260607T000000Z-1-111111111/round-1"
        sh = tmp_path / ".superharness"
        sh.mkdir()
        self._setup_sqlite(tmp_path, disc_task)

        execute_called = []

        with patch("superharness.commands.inbox_dispatch._execute_agent",
                   side_effect=lambda c: execute_called.append(True)), \
             patch("superharness.commands.inbox_dispatch._prepare_launch_context"), \
             patch("superharness.commands.inbox_dispatch._skip_already_done_discussion_round",
                   return_value=False):
            from superharness.commands.inbox_dispatch import dispatch
            dispatch(
                project_dir=str(tmp_path),
                target_filter="claude-code",
                non_interactive=True,
            )

        assert execute_called, "_execute_agent must be called for discussion round dispatch"

    def test_session_inject_off_by_default(self, tmp_path, monkeypatch):
        """inbox_watch._run_dispatch_cmd must not append --session-inject when
        SUPERHARNESS_SESSION_INJECT_ENABLED is not set."""
        from unittest.mock import patch, MagicMock

        monkeypatch.delenv("SUPERHARNESS_SESSION_INJECT_ENABLED", raising=False)

        captured = []

        def _fake_popen(args, **kwargs):
            captured.extend(args)
            return MagicMock()

        with patch("superharness.commands.inbox_watch.subprocess.Popen",
                   side_effect=_fake_popen):
            from superharness.commands.inbox_watch import _run_dispatch_cmd
            _run_dispatch_cmd(
                project_dir=str(tmp_path),
                target="claude-code",
                print_only=False,
                non_interactive=True,
                codex_bypass=False,
                launcher_timeout=0,
            )

        assert "--session-inject" not in captured, (
            "--session-inject must NOT be in dispatch args by default "
            "(set SUPERHARNESS_SESSION_INJECT_ENABLED to enable)"
        )

    def test_dispatch_argv_shape_no_session_inject(self, tmp_path, monkeypatch):
        """Spawned inbox_dispatch subprocess argv must not contain --session-inject."""
        from unittest.mock import patch, MagicMock

        monkeypatch.delenv("SUPERHARNESS_SESSION_INJECT_ENABLED", raising=False)

        captured = []

        def _fake_popen(args, **kwargs):
            captured.extend(args)
            return MagicMock()

        with patch("superharness.commands.inbox_watch.subprocess.Popen",
                   side_effect=_fake_popen):
            from superharness.commands.inbox_watch import _run_dispatch_cmd
            _run_dispatch_cmd(
                project_dir=str(tmp_path),
                target="gemini-cli",
                print_only=False,
                non_interactive=False,
                codex_bypass=False,
                launcher_timeout=0,
            )

        assert "--session-inject" not in captured
        assert "--project" in captured
        assert "--to" in captured

    def test_is_discussion_routing_skips_session_inject_branch(self, tmp_path, monkeypatch):
        """is_discussion=True items must route directly to _execute_agent.
        Session-injection path has been fully removed."""
        from unittest.mock import patch

        monkeypatch.delenv("SUPERHARNESS_SESSION_INJECT_ENABLED", raising=False)

        disc_task = "discuss-routingtest20260607T000000Z-2-222222222/round-1"
        sh = tmp_path / ".superharness"
        sh.mkdir()
        self._setup_sqlite(tmp_path, disc_task)

        execute_called = []

        with patch("superharness.commands.inbox_dispatch._execute_agent",
                   side_effect=lambda c: execute_called.append(True)), \
             patch("superharness.commands.inbox_dispatch._prepare_launch_context"), \
             patch("superharness.commands.inbox_dispatch._skip_already_done_discussion_round",
                   return_value=False):
            from superharness.commands.inbox_dispatch import dispatch
            dispatch(
                project_dir=str(tmp_path),
                target_filter="claude-code",
                non_interactive=True,
            )

        assert execute_called, "_execute_agent must be called"

    def test_no_silent_dispatched_blackhole(self, tmp_path, monkeypatch):
        """After dispatch, the inbox item must NOT be in 'dispatched' status.
        The old session-inject path silently set items to 'dispatched' — a state
        the watcher treats as active but never completes, creating a blackhole."""
        import sqlite3
        from unittest.mock import patch

        monkeypatch.delenv("SUPERHARNESS_SESSION_INJECT_ENABLED", raising=False)

        disc_task = "discuss-blackhole20260607T000000Z-3-333333333/round-1"
        sh = tmp_path / ".superharness"
        sh.mkdir()
        self._setup_sqlite(tmp_path, disc_task)

        with patch("superharness.commands.inbox_dispatch._execute_agent"), \
             patch("superharness.commands.inbox_dispatch._prepare_launch_context"), \
             patch("superharness.commands.inbox_dispatch._skip_already_done_discussion_round",
                   return_value=False), \
             patch("superharness.commands.inbox_dispatch._reconcile_state",
                   return_value=0):
            from superharness.commands.inbox_dispatch import dispatch
            dispatch(
                project_dir=str(tmp_path),
                target_filter="claude-code",
                non_interactive=True,
            )

        # Verify the item did NOT end up in 'dispatched' status
        conn = sqlite3.connect(str(tmp_path / ".superharness" / "state.sqlite3"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM inbox WHERE id = 'item-iter1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] != "dispatched", (
            "Discussion round item must not end up in 'dispatched' status — "
            "that is the silent blackhole created by the old session-inject path"
        )


# ── Iter 11 RED: session-injection dead code must be removed ──────────────────

def test_no_prompt_md_produced_anywhere():
    """_write_discussion_prompt_file must not exist in inbox_dispatch after removal.

    RED: The function currently exists and produces .prompt.md files.
    After deletion (GREEN), this structural check passes.
    """
    import inspect
    from superharness.commands import inbox_dispatch as m
    src = inspect.getsource(m)
    assert "_write_discussion_prompt_file" not in src, (
        "_write_discussion_prompt_file still exists in inbox_dispatch. "
        "Delete the function and all its call sites as part of the session-injection removal."
    )


# ── Guard: sqlite-only _reconcile_state writes SQLite directly ────────────────

class TestReconcileStateSqliteOnly:
    """Guard: in sqlite-only mode, _reconcile_state must update SQLite even when
    inbox.yaml does not contain the item (i.e. YAML write returns False)."""

    def _setup_db(self, tmp_path, disc_task: str) -> None:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(tmp_path))
        init_db(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES (?,?,?,?)",
            (disc_task, "Round guard", "in_progress", "2026-06-08T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, priority, "
            "retry_count, max_retries, created_at, project_path) VALUES (?,?,?,?,?,?,?,?,?)",
            ("item-guard1", disc_task, "claude-code", "launched", 5, 0, 3,
             "2026-06-08T00:00:00Z", str(tmp_path)),
        )
        conn.commit()
        conn.close()

    def _read_status(self, tmp_path, item_id: str) -> str:
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".superharness" / "state.sqlite3"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM inbox WHERE id=?", (item_id,)).fetchone()
        conn.close()
        return str(row["status"]) if row else ""

    def test_done_written_to_sqlite_when_yaml_absent(self, tmp_path):
        """After agent rc=0 + submission present, item must be 'done' in SQLite
        even when inbox.yaml does not exist (sqlite-only mode)."""
        import os
        from unittest.mock import patch, MagicMock
        from superharness.commands.inbox_dispatch import DispatchContext, _reconcile_state

        disc_task = "discuss-guardtest20260608T000000Z-2-222222222/round-1"
        (tmp_path / ".superharness").mkdir()
        (tmp_path / ".superharness" / "discussions" / "discuss-guardtest20260608T000000Z-2-222222222").mkdir(parents=True)
        submission = (tmp_path / ".superharness" / "discussions" /
                      "discuss-guardtest20260608T000000Z-2-222222222" / "round-1-claude-code.yaml")
        submission.write_text("discussion_id: discuss-guardtest20260608T000000Z-2-222222222\nround: 1\nagent: claude-code\nverdict: consensus\n")

        self._setup_db(tmp_path, disc_task)

        ctx = MagicMock(spec=DispatchContext)
        ctx.non_interactive = True
        ctx.print_only = False
        ctx.sqlite_primary = True
        ctx.is_discussion = True
        ctx.item_id = "item-guard1"
        ctx.item_task = disc_task
        ctx.item_to = "claude-code"
        ctx.project_dir = str(tmp_path)
        ctx.exec_project = str(tmp_path)
        ctx.inbox_file = str(tmp_path / ".superharness" / "inbox.yaml")
        ctx.task_log = None
        ctx.launcher_rc = 0
        ctx.launch_start = 0.0

        rc = _reconcile_state(ctx)

        status = self._read_status(tmp_path, "item-guard1")
        assert status == "done", (
            f"_reconcile_state must write 'done' to SQLite in sqlite-only mode; "
            f"got '{status}'. The YAML gate was blocking the SQLite mirror write."
        )
        assert rc == 0

    def test_failed_written_to_sqlite_when_submission_absent(self, tmp_path):
        """When submission YAML is missing and no dirty worktree, item must be 'failed'
        in SQLite (not stuck in 'launched') in sqlite-only mode."""
        from unittest.mock import patch, MagicMock
        from superharness.commands.inbox_dispatch import DispatchContext, _reconcile_state

        disc_task = "discuss-guardfail20260608T000000Z-2-333333333/round-1"
        (tmp_path / ".superharness").mkdir()
        self._setup_db(tmp_path, disc_task)

        ctx = MagicMock(spec=DispatchContext)
        ctx.non_interactive = True
        ctx.print_only = False
        ctx.sqlite_primary = True
        ctx.is_discussion = True
        ctx.item_id = "item-guard1"
        ctx.item_task = disc_task
        ctx.item_to = "claude-code"
        ctx.project_dir = str(tmp_path)
        ctx.exec_project = str(tmp_path)
        ctx.inbox_file = str(tmp_path / ".superharness" / "inbox.yaml")
        ctx.task_log = None
        ctx.launcher_rc = 0
        ctx.launch_start = 0.0

        with patch("superharness.commands.inbox_dispatch._has_dirty_worktree", return_value=False):
            rc = _reconcile_state(ctx)

        status = self._read_status(tmp_path, "item-guard1")
        assert status == "failed", (
            f"_reconcile_state must write 'failed' to SQLite when submission is absent "
            f"in sqlite-only mode; got '{status}'."
        )
        assert rc == 1

    def test_pending_user_approval_written_as_paused_in_sqlite(self, tmp_path):
        """When final_state is 'pending_user_approval', item must be written as 'paused'
        in SQLite in sqlite-only mode (reconciled=3 path)."""
        from unittest.mock import patch, MagicMock
        from superharness.commands.inbox_dispatch import DispatchContext, _reconcile_state

        disc_task = "discuss-guardpause20260608T000000Z-2-444444444/round-1"
        (tmp_path / ".superharness").mkdir()
        self._setup_db(tmp_path, disc_task)

        ctx = MagicMock(spec=DispatchContext)
        ctx.non_interactive = True
        ctx.print_only = False
        ctx.sqlite_primary = True
        ctx.is_discussion = False
        ctx.item_id = "item-guard1"
        ctx.item_task = disc_task
        ctx.item_to = "claude-code"
        ctx.project_dir = str(tmp_path)
        ctx.exec_project = str(tmp_path)
        ctx.inbox_file = str(tmp_path / ".superharness" / "inbox.yaml")
        ctx.task_log = None
        ctx.launcher_rc = 0
        ctx.launch_start = 0.0

        with patch("superharness.engine.state_reader.get_task",
                   return_value={"status": "pending_user_approval"}):
            rc = _reconcile_state(ctx)

        status = self._read_status(tmp_path, "item-guard1")
        assert status == "paused", (
            f"_reconcile_state must write 'paused' to SQLite when final_state is "
            f"'pending_user_approval' in sqlite-only mode; got '{status}'."
        )
        assert rc == 0
