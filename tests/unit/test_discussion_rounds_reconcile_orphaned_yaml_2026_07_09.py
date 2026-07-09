"""Regression tests for 2026-07-09: `discussion close` orphans agent output.

Reproduces the data-loss scenario from
docs/AUDIT-2026-07-09-discussion-close-data-loss.md §1.

Mechanism (verified in source):

- `cmd_close` marks the discussion's inbox rows done but never signals the
  launcher PIDs, so already-launched agents run to completion and write
  `round-N-<agent>.yaml` into the discussion directory.
- `register_yaml_submission` — the harness-side half of the two-phase
  submission — is invoked only from `_reconcile_yaml_submissions`
  (called by `cmd_advance`) and from the watcher's
  `_auto_advance_orphaned_rounds`, which filters `status="active"`.
- Closing sets `status != 'active'`, so nothing ever registers those files.
- `cmd_status` (which `discussion rounds` renders) reads `discussion_rounds`
  from SQLite only, so the CLI reports "(no submissions yet)" for a round
  whose 8 KB position files are sitting on disk.

Fix: reconcile on-disk submissions from the read path, so orphaned rounds
become visible regardless of discussion status. Registration is idempotent
and does not mutate discussion status, so a closed discussion stays closed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import yaml

from superharness.engine import discussions_dao
from superharness.engine.db import get_connection, init_db


NOW = "2026-07-09T00:00:00Z"
DISC_ID = "discuss-orphan-20260709T000000Z"
OWNERS = ["claude-code", "opencode"]


def _make_discussion(tmp_path, status: str = "closed"):
    project = tmp_path / "proj"
    disc_dir = project / ".superharness" / "discussions" / DISC_ID
    disc_dir.mkdir(parents=True)

    conn = get_connection(str(project))
    init_db(conn, project_dir=str(project))
    discussions_dao.create(
        conn, id=DISC_ID, topic="Orphaned round repro",
        owners=OWNERS, task_id=None, now=NOW,
    )
    # Round 1 submitted normally, by both agents.
    for agent in OWNERS:
        discussions_dao.add_round(
            conn, discussion_id=DISC_ID, round_number=1,
            agent=agent, content="round 1", verdict="partial", now=NOW,
        )
    # An advance marker to round 2 exists — the round was dispatched.
    conn.execute(
        "INSERT INTO discussion_rounds (discussion_id, round_number, agent, content, verdict, created_at) "
        "VALUES (?, 2, '_advance', NULL, NULL, ?)",
        (DISC_ID, NOW),
    )
    conn.execute("UPDATE discussions SET status=?, closed_at=? WHERE id=?", (status, NOW, DISC_ID))
    conn.commit()
    conn.close()
    return project, disc_dir


def _orphan_yaml(disc_dir, round_: int, agent: str, verdict: str = "disagree"):
    """Write the file an agent produces after close — never registered in SQLite."""
    (disc_dir / f"round-{round_}-{agent}.yaml").write_text(
        yaml.dump({"verdict": verdict, "position": f"{agent} round {round_} position"})
    )


def _engine_status(disc_dir) -> dict:
    """Invoke the same code path `shux discussion rounds` renders."""
    env = {**os.environ, "PYTHONPATH": os.path.join(os.getcwd(), "src")}
    r = subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion", "status",
         "--discussion-dir", str(disc_dir)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _submissions_for(status: dict, round_: int) -> list[dict]:
    for r in status.get("rounds") or []:
        if r["round"] == round_:
            return r.get("submissions") or []
    return []


def test_orphaned_round_yaml_is_surfaced_after_close(tmp_path):
    """The audit's exact scenario: agents finish after close, write YAML, and the
    CLI must not report the round as empty."""
    project, disc_dir = _make_discussion(tmp_path, status="closed")
    for agent in OWNERS:
        _orphan_yaml(disc_dir, 2, agent)

    status = _engine_status(disc_dir)
    agents = sorted(s["agent"] for s in _submissions_for(status, 2))
    assert agents == sorted(OWNERS), (
        f"round 2 submissions exist on disk but CLI reported {agents}"
    )


def test_reconcile_does_not_reopen_a_closed_discussion(tmp_path):
    """Surfacing orphaned output must not resurrect a terminal state."""
    project, disc_dir = _make_discussion(tmp_path, status="closed")
    for agent in OWNERS:
        _orphan_yaml(disc_dir, 2, agent, verdict="agree")

    status = _engine_status(disc_dir)
    assert status["status"] == "closed", (
        f"discussion status changed to {status['status']!r} — close must stay terminal"
    )


def test_reconcile_is_idempotent(tmp_path):
    """Reading twice must not duplicate rows."""
    project, disc_dir = _make_discussion(tmp_path, status="closed")
    for agent in OWNERS:
        _orphan_yaml(disc_dir, 2, agent)

    _engine_status(disc_dir)
    status = _engine_status(disc_dir)
    assert len(_submissions_for(status, 2)) == len(OWNERS), (
        "second read duplicated submissions"
    )


def test_corrupt_orphan_yaml_is_skipped_not_fatal(tmp_path):
    """A truncated file (agent killed mid-write) must not break the read path."""
    project, disc_dir = _make_discussion(tmp_path, status="closed")
    (disc_dir / "round-2-claude-code.yaml").write_text("verdict: partial\nposition: |\n  unterminated")
    (disc_dir / "round-2-opencode.yaml").write_text("{ this is not: valid: yaml: [")

    status = _engine_status(disc_dir)
    assert status["status"] == "closed"
    agents = [s["agent"] for s in _submissions_for(status, 2)]
    assert "opencode" not in agents, "corrupt YAML must not be registered"


def test_active_discussion_still_surfaces_yaml(tmp_path):
    """Reconciliation must not be gated on status — an active discussion whose
    watcher has not yet ticked should also show on-disk submissions."""
    project, disc_dir = _make_discussion(tmp_path, status="active")
    for agent in OWNERS:
        _orphan_yaml(disc_dir, 2, agent)

    status = _engine_status(disc_dir)
    assert len(_submissions_for(status, 2)) == len(OWNERS)
