"""Regression tests for 2026-07-09: `discussion close` now terminates launched
agent processes instead of leaving them running.

Design decision (docs/AUDIT-2026-07-09-discussion-close-data-loss.md §4
"Suggested action" / this session's follow-up discussion): `close` should stop
live work, not let it finish silently. The read-path fix
(fix/discussion-rounds-reconcile-orphaned-yaml, already merged) makes any
output an agent DID finish writing before being killed visible; this fix stops
the agent from continuing to run at all.

Mechanism, verified against source before writing this fix:

- `inbox_dispatch.py` spawns the `python -m superharness.commands.delegate`
  wrapper with `preexec_fn=os.setsid` (POSIX) — it becomes its own process
  group leader — and records `proc.pid` into `inbox.pid` via `set_field`,
  cleared back to empty on completion. This is the exact same pattern
  `_run_with_timeout`'s SIGALRM handler already uses to kill on timeout
  (`os.killpg(proc.pid, signal.SIGTERM)`), reused here for consistency.
- On Windows, `preexec_fn` is POSIX-only, so there is no process group;
  `taskkill /T /F /PID` is used instead to walk the tree.

`cmd_close` now: SIGTERMs every live pid recorded against the discussion's
round inbox rows, waits a short grace window, SIGKILLs survivors (POSIX only
— Windows' `/F` is already forceful), then reconciles any on-disk YAML the
agent finished writing before dying.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from superharness.engine import discussion as discussion_mod
from superharness.engine.db import get_connection, init_db


NOW = "2026-07-09T00:00:00Z"
DISC_ID = "discuss-close-kill-20260709T000000Z"


def _make_discussion(tmp_path, owners=("claude-code", "opencode")):
    project = tmp_path / "proj"
    disc_dir = project / ".superharness" / "discussions" / DISC_ID
    disc_dir.mkdir(parents=True)

    conn = get_connection(str(project))
    init_db(conn, project_dir=str(project))
    conn.execute(
        "INSERT INTO discussions (id, topic, status, owners, created_at) VALUES (?,?,?,?,?)",
        (DISC_ID, "Close-kill repro", "active", '["' + '","'.join(owners) + '"]', NOW),
    )
    conn.commit()
    conn.close()
    return project, disc_dir


def _seed_launched_inbox(project, task_suffix: str, agent: str, pid: int, status: str = "launched"):
    conn = get_connection(str(project))
    init_db(conn, project_dir=str(project))
    task_id = f"{DISC_ID}/{task_suffix}"
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES (?,?,?,?)",
        (task_id, "round task", "in_progress", NOW),
    )
    inbox_id = f"{DISC_ID[:20]}-{agent}-{task_suffix}"
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, priority, retry_count, "
        "max_retries, pid, created_at) VALUES (?,?,?,?,2,0,3,?,?)",
        (inbox_id, task_id, agent, status, pid, NOW),
    )
    conn.commit()
    conn.close()
    return inbox_id


def _spawn_sleeper(seconds: int = 30, ignore_sigterm: bool = False) -> subprocess.Popen:
    """A real, killable child process — matches what delegate.py actually spawns."""
    code = (
        "import signal, time\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_sigterm else "")
        + f"time.sleep({seconds})\n"
    )
    kwargs = {}
    if sys.platform != "win32":
        kwargs["preexec_fn"] = os.setsid
    return subprocess.Popen([sys.executable, "-c", code], **kwargs)


def _wait_dead(proc: subprocess.Popen, timeout: float = 5.0) -> bool:
    """True if *proc* exits within *timeout*.

    Uses `proc.wait()`, not a `kill(pid, 0)`-based liveness poll. This test
    is the process's real parent (it called Popen directly), so a terminated
    child sits as a zombie — still "alive" to any kill(pid, 0) check — until
    its parent reaps it. Only wait()/poll() both detects AND reaps, so it's
    the only check that converges here. (In production, `cmd_close` runs in
    a different process than the one that spawned the agent, so this
    parent/zombie ambiguity doesn't apply to the real code path — only to
    self-spawned test fixtures like this one.)
    """
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


@pytest.fixture(autouse=True)
def _fast_grace(monkeypatch):
    """Production grace window is a few seconds; tests need it short."""
    monkeypatch.setattr(discussion_mod, "_CLOSE_KILL_GRACE_SECONDS", 1.0)


def test_close_terminates_a_cooperative_launched_process(tmp_path):
    proc = _spawn_sleeper()
    try:
        project, disc_dir = _make_discussion(tmp_path)
        _seed_launched_inbox(project, "round-2", "claude-code", proc.pid)

        rc = discussion_mod.cmd_close(str(disc_dir), "closed")
        assert rc == 0

        assert _wait_dead(proc), f"pid {proc.pid} still alive after close"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM-ignore + SIGKILL escalation is POSIX-only")
def test_close_escalates_to_sigkill_for_a_process_that_ignores_sigterm(tmp_path):
    proc = _spawn_sleeper(ignore_sigterm=True)
    try:
        project, disc_dir = _make_discussion(tmp_path)
        _seed_launched_inbox(project, "round-2", "claude-code", proc.pid)

        rc = discussion_mod.cmd_close(str(disc_dir), "closed")
        assert rc == 0

        assert _wait_dead(proc, timeout=5.0), (
            f"pid {proc.pid} ignored SIGTERM and was not escalated to SIGKILL"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def test_close_does_not_touch_processes_outside_the_discussion(tmp_path):
    """Scope guard: a live process belonging to an unrelated task must survive."""
    unrelated = _spawn_sleeper()
    try:
        project, disc_dir = _make_discussion(tmp_path)
        _seed_launched_inbox(project, "round-1", "claude-code", 999999)  # dead/bogus pid, this discussion

        conn = get_connection(str(project))
        init_db(conn, project_dir=str(project))
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES ('other-task', 'x', 'in_progress', ?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, priority, retry_count, "
            "max_retries, pid, created_at) VALUES ('other-inbox-item', 'other-task', 'claude-code', "
            "'launched', 2, 0, 3, ?, ?)",
            (unrelated.pid, NOW),
        )
        conn.commit()
        conn.close()

        rc = discussion_mod.cmd_close(str(disc_dir), "closed")
        assert rc == 0

        time.sleep(0.5)
        assert discussion_mod._pid_alive(unrelated.pid), (
            "close() killed a process belonging to a different task"
        )
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_close_with_no_live_pids_does_not_raise(tmp_path):
    """Every submitted round already finished (pid cleared to '') — close must
    still succeed cleanly, nothing to terminate."""
    project, disc_dir = _make_discussion(tmp_path)
    _seed_launched_inbox(project, "round-1", "claude-code", None, status="done")

    rc = discussion_mod.cmd_close(str(disc_dir), "closed")
    assert rc == 0


def test_close_reconciles_output_the_agent_finished_before_dying(tmp_path):
    """An agent that finishes writing its YAML in the same window it's killed
    must still have that output surfaced — the read-path fix already merged."""
    proc = _spawn_sleeper()
    try:
        project, disc_dir = _make_discussion(tmp_path)
        _seed_launched_inbox(project, "round-2", "claude-code", proc.pid)
        (disc_dir / "round-2-claude-code.yaml").write_text(
            "verdict: disagree\nposition: finished right before being killed\n"
        )

        rc = discussion_mod.cmd_close(str(disc_dir), "closed")
        assert rc == 0

        conn = get_connection(str(project))
        init_db(conn, project_dir=str(project))
        row = conn.execute(
            "SELECT verdict FROM discussion_rounds WHERE discussion_id=? AND round_number=2 AND agent='claude-code'",
            (DISC_ID,),
        ).fetchone()
        conn.close()
        assert row is not None and row["verdict"] == "disagree", (
            "close() did not reconcile on-disk output written before the kill"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
