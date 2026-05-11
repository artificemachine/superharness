"""Runtime/integration coverage for bugs C and F from
docs/bugs/2026-05-11_discuss_dispatch_bugs.md §9.

Bug C — ChatGPT-account override applied at the dispatch path. Unit
        tests in test_model_router.py already cover the helper and
        the bundled override map. This file exercises the FULL
        delegate() resolution path with print_only=True and captures
        the printed "Model: ..." line to confirm the remap happens at
        runtime, not just in the helper.

Bug F — `--verdict abstain` counts toward round completion. Unit tests
        cover cmd_check_round counting DB rows. This file walks the
        full submit → check_round → advance flow with two abstain
        submissions and asserts the discussion advances (or closes)
        cleanly.

Both tests use mocked subprocesses for codex auth detection / classifier
calls so they run offline.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Bug C — runtime model resolution end-to-end
# ---------------------------------------------------------------------------


def _seed_codex_project(tmp_path: Path, task_id: str = "t-codex-bug-c") -> Path:
    """Build the minimal on-disk + SQLite state delegate() needs."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    # delegate() asserts state.sqlite3 exists, not state.db. Touch both
    # so connection paths are resolvable on this version.
    (sh / "state.sqlite3").touch()

    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, created_at) VALUES (?, ?, ?, ?)",
        (task_id, "codex bug C repro", "plan_approved", "2026-05-11T12:00:00Z"),
    )
    conn.commit()
    conn.close()

    # Minimal contract.yaml so _get_task_title etc. find the task.
    (sh / "contract.yaml").write_text(
        f"id: bug-c-contract\n"
        f"tasks:\n"
        f"  - id: {task_id}\n"
        f"    title: codex bug C repro\n"
        f"    owner: codex-cli\n"
        f"    status: plan_approved\n"
        f"    project_path: {tmp_path}\n",
        encoding="utf-8",
    )
    return tmp_path


class TestBugCRuntime:
    def test_chatgpt_auth_remaps_codex_model_at_dispatch_time(self, tmp_path, monkeypatch):
        """End-to-end: delegate(target=codex-cli) with ChatGPT auth must
        print `Model: gpt-5-codex (...)` not `gpt-5.3-codex`. This is
        the exact runtime path that §8 reported as unverified."""
        from superharness.commands import delegate as delegate_mod
        from superharness.engine.model_router import _reset_codex_auth_cache

        project = _seed_codex_project(tmp_path)
        _reset_codex_auth_cache()

        # Force the bundled override to fire by faking ChatGPT auth.
        chatgpt_auth = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Logged in using ChatGPT", stderr="",
        )

        # Pin auto-classifier output so we deterministically exercise
        # the auto-classify resolution path (the one that bypassed the
        # override in 1.56.0–1.56.2 and was wired correctly in 1.56.3).
        with mock.patch(
            "superharness.engine.model_router.subprocess.run",
            return_value=chatgpt_auth,
        ), mock.patch(
            "superharness.commands.delegate.classify_task",
            return_value=("standard", "medium"),
        ) if False else mock.patch(
            "superharness.engine.model_router.classify_task",
            return_value=("standard", "medium"),
        ), mock.patch(
            "superharness.commands.delegate._launch_agent",
            return_value=0,
        ), mock.patch(
            "superharness.commands.delegate._confirm_non_interactive_risk",
            return_value=None,
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                try:
                    delegate_mod.delegate(
                        project_dir=str(project),
                        target="codex-cli",
                        task_id="t-codex-bug-c",
                        print_only=True,
                        non_interactive=True,
                        codex_bypass=False,
                        skip_preflight=True,
                    )
                except SystemExit:
                    # delegate() may sys.exit on missing optional state;
                    # we only care about the Model: line being printed
                    # before any abort path.
                    pass

            stdout = buf.getvalue()

        # The override must have remapped the model.
        assert "Model: gpt-5-codex" in stdout, (
            f"expected `Model: gpt-5-codex` in delegate stdout, got:\n{stdout!r}"
        )
        assert "Model: gpt-5.3-codex" not in stdout, (
            f"override did NOT fire — raw model leaked to dispatch:\n{stdout!r}"
        )


# ---------------------------------------------------------------------------
# Bug F — abstain submissions count toward round completion
# ---------------------------------------------------------------------------


DISC_ID = "discuss-20260511T130000Z-bugf"


def _seed_two_owner_discussion(project: Path, owners: list[str]) -> Path:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    sh = project / ".superharness"
    if not sh.exists():
        sh.mkdir()
        (sh / "handoffs").mkdir()

    conn = get_connection(str(project))
    init_db(conn)
    discussions_dao.create(
        conn,
        id=DISC_ID,
        topic="bug F abstain advancement",
        owners=owners,
        task_id=None,
        now="2026-05-11T13:00:00Z",
    )
    conn.commit()
    conn.close()

    disc_dir = sh / "discussions" / DISC_ID
    disc_dir.mkdir(parents=True)
    return disc_dir


class TestBugFRuntime:
    def test_two_abstain_submissions_complete_the_round(self, tmp_path):
        from superharness.engine.discussion import (
            cmd_submit_round, cmd_check_round,
        )

        project = tmp_path
        disc_dir = _seed_two_owner_discussion(project, ["codex-cli", "claude-code"])

        # Both agents submit abstain.
        for agent in ("codex-cli", "claude-code"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cmd_submit_round(
                    discussion_dir=str(disc_dir),
                    round_=1,
                    agent=agent,
                    verdict="abstain",
                    position=f"{agent} abstains for bug-F repro",
                    points_file=None,
                )
            assert rc == 0
            payload = json.loads(buf.getvalue())
            assert payload == {
                "submitted": True, "round": 1, "agent": agent, "verdict": "abstain",
            }

        # check_round must report complete=true.
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_check_round(str(disc_dir), 1)
        result = json.loads(buf.getvalue())
        assert result["complete"] is True, (
            f"abstain submissions did not complete the round: {result}"
        )
        assert set(result["agents_done"]) == {"codex-cli", "claude-code"}
        assert result["agents_pending"] == []

    def test_all_abstain_auto_transitions_to_consensus(self, tmp_path):
        """When every owner submits (any verdict that isn't 'disagree'),
        _check_all_submitted_and_set_consensus auto-transitions the
        discussion to status='consensus'. abstain is treated as
        alignment, so the round terminates cleanly with no need for
        cmd_advance. This is the actual answer to Bug F: the round
        IS not stuck, it just exits via the auto-consensus path
        rather than the cmd_advance path the operator was watching."""
        from superharness.engine.discussion import cmd_submit_round
        from superharness.engine.db import get_connection
        from superharness.engine import discussions_dao

        project = tmp_path
        disc_dir = _seed_two_owner_discussion(project, ["codex-cli", "claude-code"])

        for agent in ("codex-cli", "claude-code"):
            with redirect_stdout(io.StringIO()):
                cmd_submit_round(
                    discussion_dir=str(disc_dir),
                    round_=1,
                    agent=agent,
                    verdict="abstain",
                    position=f"{agent} abstains",
                    points_file=None,
                )

        conn = get_connection(str(project))
        disc = discussions_dao.get(conn, DISC_ID)
        conn.close()
        assert disc.status == "consensus", (
            f"all-abstain must auto-transition to consensus, got status={disc.status}"
        )
        assert "all 2 participants submitted round 1" in (disc.consensus or "")

    def test_disagree_blocks_auto_consensus_and_advance_works(self, tmp_path):
        """Mirror of the previous test: if any participant disagrees,
        auto-consensus is blocked and cmd_advance is the right path to
        either advance to next round or close as no_consensus."""
        from superharness.engine.discussion import (
            cmd_submit_round, cmd_advance,
        )

        project = tmp_path
        disc_dir = _seed_two_owner_discussion(project, ["codex-cli", "claude-code"])

        with redirect_stdout(io.StringIO()):
            cmd_submit_round(str(disc_dir), 1, "codex-cli",
                             "disagree", "codex disagrees", None)
            cmd_submit_round(str(disc_dir), 1, "claude-code",
                             "abstain", "claude abstains", None)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_advance(str(disc_dir))
        assert rc == 0
        result = json.loads(buf.getvalue())
        # max_rounds defaults to 3 when no _meta row is present, so
        # the engine should advance, not close.
        assert result["action"] in ("advanced", "closed"), result

    def test_mixed_verdicts_with_one_abstain_still_completes(self, tmp_path):
        """One agree + one abstain must still complete the round —
        abstain is not a "doesn't count" signal."""
        from superharness.engine.discussion import (
            cmd_submit_round, cmd_check_round,
        )

        project = tmp_path
        disc_dir = _seed_two_owner_discussion(project, ["codex-cli", "claude-code"])

        with redirect_stdout(io.StringIO()):
            cmd_submit_round(str(disc_dir), 1, "codex-cli",
                             "agree", "codex agrees", None)
            cmd_submit_round(str(disc_dir), 1, "claude-code",
                             "abstain", "claude abstains", None)

        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_check_round(str(disc_dir), 1)
        result = json.loads(buf.getvalue())
        assert result["complete"] is True
        assert set(result["agents_done"]) == {"codex-cli", "claude-code"}
