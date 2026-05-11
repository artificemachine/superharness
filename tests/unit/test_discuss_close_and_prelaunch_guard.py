"""Regression tests for the §8 follow-up fixes from
docs/bugs/2026-05-11_discuss_dispatch_bugs.md.

Bug G regression (1.56.4): leftover pending inbox items for rounds that
already produced YAMLs get claimed via the normal inbox-dispatch loop
(not via discussion_dispatch), so the discussion_dispatch idempotence
guard never sees them. The fix is a pre-launch guard inside
inbox_dispatch._do_dispatch.

Operator request (§8): `shux discuss close --id <id>` — a first-class
way to terminate an active discussion AND cancel its pending inbox
items in one transaction.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


DISC_ID = "discuss-20260511T120000Z-test"
ROUND_TASK = f"{DISC_ID}/round-1"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _seed_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    return tmp_path


def _seed_task(project: Path, task_id: str) -> None:
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES (?, ?, ?, ?)",
        (task_id, "test", "todo", "2026-05-11T12:00:00Z"),
    )
    conn.commit()
    conn.close()


def _seed_discussion(project: Path, owners: list[str], status: str = "active") -> Path:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao
    conn = get_connection(str(project))
    init_db(conn)
    discussions_dao.create(
        conn,
        id=DISC_ID,
        topic="prelaunch-guard test",
        owners=owners,
        task_id=None,
        now="2026-05-11T12:00:00Z",
    )
    if status != "active":
        conn.execute(
            "UPDATE discussions SET status=? WHERE id=?", (status, DISC_ID),
        )
    conn.commit()
    conn.close()

    disc_dir = project / ".superharness" / "discussions" / DISC_ID
    disc_dir.mkdir(parents=True)
    return disc_dir


def _seed_inbox(project: Path, agent: str, status: str = "launched") -> None:
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        """
        INSERT INTO inbox
        (id, task_id, target_agent, status, priority, retry_count, max_retries,
         project_path, created_at, launched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"item-{agent}", ROUND_TASK, agent, status, 1, 0, 3,
         str(project), "2026-05-11T12:00:00Z",
         "2026-05-11T12:00:01Z" if status != "pending" else None),
    )
    conn.commit()
    conn.close()


def _make_ctx(project: Path, agent: str):
    from superharness.commands.inbox_dispatch import DispatchContext
    ctx = DispatchContext(
        project_dir=str(project),
        inbox_file=str(project / ".superharness" / "inbox.yaml"),
        contract_file=str(project / ".superharness" / "contract.yaml"),
        non_interactive=True,
        codex_bypass=False,
        launcher_timeout=900,
        script_dir="",
        sqlite_primary=True,
        print_only=False,
    )
    ctx.item = {"id": f"item-{agent}", "task_id": ROUND_TASK, "target_agent": agent}
    ctx.item_id = f"item-{agent}"
    ctx.item_to = agent
    ctx.item_task = ROUND_TASK
    ctx.exec_project = str(project)
    ctx.is_discussion = True
    ctx.effective_timeout = 900
    return ctx


# ---------------------------------------------------------------------------
# Pre-launch guard — YAML on disk
# ---------------------------------------------------------------------------


class TestPrelaunchGuardYamlOnDisk:
    def test_yaml_present_skips_launch_and_marks_done(self, tmp_path):
        from superharness.commands.inbox_dispatch import _skip_already_done_discussion_round
        from superharness.engine.db import get_connection

        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        disc_dir = _seed_discussion(project, owners=["claude-code"])
        (disc_dir / "round-1-claude-code.yaml").write_text("verdict: partial\n")
        _seed_inbox(project, "claude-code", status="launched")

        ctx = _make_ctx(project, "claude-code")
        skipped = _skip_already_done_discussion_round(ctx)
        assert skipped is True

        conn = get_connection(str(project))
        row = conn.execute(
            "SELECT status, failed_reason FROM inbox WHERE id=?",
            (f"item-claude-code",),
        ).fetchone()
        conn.close()
        assert row["status"] == "done"
        assert "submission YAML already present" in (row["failed_reason"] or "")

    def test_no_yaml_no_closed_does_not_skip(self, tmp_path):
        from superharness.commands.inbox_dispatch import _skip_already_done_discussion_round
        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        _seed_discussion(project, owners=["claude-code"])
        _seed_inbox(project, "claude-code", status="launched")

        ctx = _make_ctx(project, "claude-code")
        assert _skip_already_done_discussion_round(ctx) is False

    def test_print_only_short_circuits_to_false(self, tmp_path):
        """Print-only never mutates inbox state, so the guard must
        return False and let the print-only path complete normally."""
        from superharness.commands.inbox_dispatch import _skip_already_done_discussion_round
        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        disc_dir = _seed_discussion(project, owners=["claude-code"])
        (disc_dir / "round-1-claude-code.yaml").write_text("verdict: partial\n")
        _seed_inbox(project, "claude-code", status="launched")

        ctx = _make_ctx(project, "claude-code")
        ctx.print_only = True
        assert _skip_already_done_discussion_round(ctx) is False


# ---------------------------------------------------------------------------
# Pre-launch guard — discussion closed
# ---------------------------------------------------------------------------


class TestPrelaunchGuardClosedDiscussion:
    def test_closed_discussion_skips_launch(self, tmp_path):
        from superharness.commands.inbox_dispatch import _skip_already_done_discussion_round
        from superharness.engine.db import get_connection

        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        _seed_discussion(project, owners=["claude-code"], status="closed")
        _seed_inbox(project, "claude-code", status="launched")

        ctx = _make_ctx(project, "claude-code")
        assert _skip_already_done_discussion_round(ctx) is True

        conn = get_connection(str(project))
        row = conn.execute(
            "SELECT status FROM inbox WHERE id=?", (f"item-claude-code",),
        ).fetchone()
        conn.close()
        assert row["status"] == "done"

    def test_cancelled_discussion_also_skips(self, tmp_path):
        from superharness.commands.inbox_dispatch import _skip_already_done_discussion_round
        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        _seed_discussion(project, owners=["claude-code"], status="cancelled")
        _seed_inbox(project, "claude-code", status="launched")

        ctx = _make_ctx(project, "claude-code")
        assert _skip_already_done_discussion_round(ctx) is True


# ---------------------------------------------------------------------------
# shux discuss close — engine cmd_close
# ---------------------------------------------------------------------------


class TestDiscussCloseCmd:
    def test_close_sets_status_and_cancels_pending_inbox(self, tmp_path, capsys):
        from superharness.engine.discussion import cmd_close
        from superharness.engine.db import get_connection
        from superharness.engine import discussions_dao

        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        disc_dir = _seed_discussion(project, owners=["claude-code", "codex-cli"])
        _seed_inbox(project, "claude-code", status="pending")
        _seed_inbox(project, "codex-cli", status="launched")

        rc = cmd_close(str(disc_dir), outcome="closed", reason="operator stop")
        assert rc == 0

        out = capsys.readouterr().out
        assert '"closed": true' in out
        assert '"cancelled_inbox_items": 2' in out

        conn = get_connection(str(project))
        try:
            disc = discussions_dao.get(conn, DISC_ID)
            assert disc.status == "closed"
            assert disc.closed_at is not None

            inbox_rows = conn.execute(
                "SELECT id, status, failed_reason FROM inbox WHERE task_id=?",
                (ROUND_TASK,),
            ).fetchall()
            statuses = {r["id"]: r["status"] for r in inbox_rows}
            assert statuses == {"item-claude-code": "done", "item-codex-cli": "done"}
            for r in inbox_rows:
                assert "discussion closed (closed)" in (r["failed_reason"] or "")
                assert "operator stop" in (r["failed_reason"] or "")
        finally:
            conn.close()

    def test_close_leaves_terminal_inbox_items_alone(self, tmp_path):
        """An inbox item already in 'done' or 'failed' must not be
        touched (don't rewrite history)."""
        from superharness.engine.discussion import cmd_close
        from superharness.engine.db import get_connection

        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        disc_dir = _seed_discussion(project, owners=["claude-code"])

        # Pre-existing terminal row
        conn = get_connection(str(project))
        conn.execute(
            """
            INSERT INTO inbox
            (id, task_id, target_agent, status, priority, retry_count, max_retries,
             project_path, created_at, done_at, failed_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("item-old", ROUND_TASK, "claude-code", "done", 1, 0, 3,
             str(project), "2026-05-11T11:00:00Z", "2026-05-11T11:05:00Z", "original"),
        )
        conn.commit()
        conn.close()

        cmd_close(str(disc_dir), outcome="closed")

        conn = get_connection(str(project))
        row = conn.execute(
            "SELECT failed_reason FROM inbox WHERE id=?", ("item-old",),
        ).fetchone()
        conn.close()
        assert row["failed_reason"] == "original", "terminal item must not be rewritten"

    def test_close_with_no_inbox_items_still_succeeds(self, tmp_path, capsys):
        """A discussion with no inbox rows must still close cleanly."""
        from superharness.engine.discussion import cmd_close
        from superharness.engine.db import get_connection
        from superharness.engine import discussions_dao

        project = _seed_project(tmp_path)
        _seed_task(project, ROUND_TASK)
        disc_dir = _seed_discussion(project, owners=["claude-code"])

        rc = cmd_close(str(disc_dir), outcome="closed")
        assert rc == 0
        assert '"cancelled_inbox_items": 0' in capsys.readouterr().out

        conn = get_connection(str(project))
        disc = discussions_dao.get(conn, DISC_ID)
        conn.close()
        assert disc.status == "closed"

    def test_close_unknown_discussion_exits_nonzero(self, tmp_path):
        from superharness.engine.discussion import cmd_close
        project = _seed_project(tmp_path)
        # No discussion seeded — should sys.exit with a message.
        disc_dir = project / ".superharness" / "discussions" / DISC_ID
        disc_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            cmd_close(str(disc_dir), outcome="closed")


# ---------------------------------------------------------------------------
# CLI plumbing — shux discuss close
# ---------------------------------------------------------------------------


class TestDiscussCloseCli:
    def test_cli_parser_accepts_close_subcommand(self):
        """Smoke check: argparse must recognise the close subparser
        with --id/--outcome/--reason."""
        from superharness.commands.discuss import main
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with pytest.raises(SystemExit):
                main(["close", "--help"])
        help_text = buf.getvalue() + ""
        # --help exits cleanly, so just verify no parse error path was
        # taken (no 'invalid choice' message in stderr).
        assert "invalid choice" not in help_text.lower()
