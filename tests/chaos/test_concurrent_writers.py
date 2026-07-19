"""Concurrent-WRITER chaos coverage (QA finding, job-ready audit stage 5).

tests/chaos/ previously only exercised concurrent readers
(TestChaosWALContention.test_concurrent_readers_dont_block in
test_edge_cases.py). This file adds real writer-contention coverage
against the actual production API (engine.db.get_connection +
engine.inbox_dao.claim_next / engine.tasks_dao.update), each thread using
its own connection against the same on-disk project — the same shape a
real multi-agent watcher + operator scenario produces.

(a) N threads race claim_next on a single pending inbox item — exactly
    one must win (the atomic UPDATE...RETURNING claim pattern).
(b) N threads write to N distinct tasks concurrently through
    tasks_dao.update — all must succeed under WAL + busy_timeout, with
    no "database is locked" escaping to the caller.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from superharness.engine import db, inbox_dao, tasks_dao
from superharness.engine.tasks_dao import TaskRow


def _make_project(tmp_path: Path) -> str:
    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)
    conn = db.get_connection(project_dir)
    db.init_db(conn, project_dir)
    conn.close()
    return project_dir


def test_claim_next_exactly_one_winner_under_thread_contention(tmp_path):
    """8 threads, each with its own get_connection, race claim_next on the
    same single pending inbox item. Exactly one must claim it; the rest
    must see it already gone (None) — never an error, never a double claim.
    """
    project_dir = _make_project(tmp_path)

    seed_conn = db.get_connection(project_dir)
    tasks_dao.upsert(seed_conn, TaskRow(
        id="t-race", title="Race Task", owner=None, status="todo",
        effort=None, project_path=None, development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at="2026-07-19T00:00:00Z",
    ))
    inbox_dao.enqueue(
        seed_conn, id="i-race", task_id="t-race", target_agent="claude-code",
        now="2026-07-19T00:00:00Z",
    )
    seed_conn.commit()
    seed_conn.close()

    winners: list = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def do_claim():
        try:
            conn = db.get_connection(project_dir)
            try:
                row = inbox_dao.claim_next(
                    conn, target_agent="claude-code", pid=threading.get_ident(), now="now"
                )
                conn.commit()
                if row is not None:
                    with lock:
                        winners.append(row)
            finally:
                conn.close()
        except Exception as e:  # pragma: no cover - failure path asserted below
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=do_claim) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"claim_next raised under contention: {errors}"
    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}: {winners}"
    assert winners[0].id == "i-race"


def test_interleaved_updates_on_distinct_tasks_all_succeed(tmp_path):
    """8 threads, each with its own get_connection, update 8 DISTINCT tasks
    concurrently. No shared row contention, but every writer still shares
    the same SQLite file — this proves WAL + busy_timeout=5000 (arch A3/A6)
    let concurrent writers on different rows all land without a caller ever
    seeing 'database is locked'.
    """
    project_dir = _make_project(tmp_path)
    n = 8

    seed_conn = db.get_connection(project_dir)
    for i in range(n):
        tasks_dao.upsert(seed_conn, TaskRow(
            id=f"t-writer-{i}", title=f"Writer Task {i}", owner=None, status="todo",
            effort=None, project_path=None, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None, version=1,
            created_at="2026-07-19T00:00:00Z",
        ))
    seed_conn.commit()
    seed_conn.close()

    errors: list[Exception] = []
    succeeded: list[str] = []
    lock = threading.Lock()

    def do_update(idx: int):
        try:
            conn = db.get_connection(project_dir)
            try:
                task_id = f"t-writer-{idx}"
                row = tasks_dao.get(conn, task_id)
                tasks_dao.update(conn, task_id, row.version, {"status": "in_progress"})
                conn.commit()
                with lock:
                    succeeded.append(task_id)
            finally:
                conn.close()
        except Exception as e:  # pragma: no cover - failure path asserted below
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=do_update, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent tasks_dao.update raised (e.g. 'database is locked'): {errors}"
    assert sorted(succeeded) == sorted(f"t-writer-{i}" for i in range(n))

    verify_conn = db.get_connection(project_dir)
    for i in range(n):
        row = tasks_dao.get(verify_conn, f"t-writer-{i}")
        assert row.status == "in_progress"
    verify_conn.close()
