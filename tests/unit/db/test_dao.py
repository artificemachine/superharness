from __future__ import annotations

import sqlite3
import pytest
import threading
import time
import os
from dataclasses import asdict

from superharness.engine.state_errors import StateError, ConcurrencyError

def test_inbox_dao_enqueue_get(db_conn):
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    # Need a task first for FK
    t = TaskRow(id="t1", title="T1", owner=None, status="todo", effort=None, project_path=None,
        development_method=None, acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1, created_at="now")
    tasks_dao.upsert(db_conn, t)

    row = inbox_dao.enqueue(
        db_conn, 
        id="i1", 
        task_id="t1", 
        target_agent="claude-code",
        priority=1,
        project_path="/tmp/p1",
        now="now"
    )
    assert row.id == "i1"
    assert row.status == "pending"
    
    fetched = inbox_dao.get(db_conn, "i1")
    assert fetched == row

def test_inbox_dao_get_all_ordering(db_conn):
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    for i in (1, 2, 3):
        tasks_dao.upsert(db_conn, TaskRow(id=f"t{i}", title=f"T{i}", owner=None, status="todo", 
            effort=None, project_path=None, development_method=None, acceptance_criteria=[], 
            test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, 
            version=1, created_at="now"))

    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a1", priority=2, now="2026-01-01T00:00:01Z")
    inbox_dao.enqueue(db_conn, id="i2", task_id="t2", target_agent="a1", priority=3, now="2026-01-01T00:00:02Z")
    inbox_dao.enqueue(db_conn, id="i3", task_id="t3", target_agent="a1", priority=2, now="2026-01-01T00:00:03Z")
    
    all_rows = inbox_dao.get_all(db_conn, target_agent="a1")
    # Priority 3 first, then i1 (created first), then i3
    assert [r.id for r in all_rows] == ["i2", "i1", "i3"]

def test_inbox_dao_claim_next_atomic(db_conn):
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    tasks_dao.upsert(db_conn, TaskRow(id="t1", title="T1", owner=None, status="todo", 
        effort=None, project_path=None, development_method=None, acceptance_criteria=[], 
        test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, 
        version=1, created_at="now"))

    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a1", priority=2, now="now")
    
    # Claim it
    row = inbox_dao.claim_next(db_conn, target_agent="a1", pid=100, now="2026-01-01T00:00:00Z")
    assert row is not None
    assert row.id == "i1"
    assert row.status == "launched"
    assert row.pid == 100
    
    # Second claim returns None
    row2 = inbox_dao.claim_next(db_conn, target_agent="a1", pid=101, now="2026-01-01T00:00:01Z")
    assert row2 is None

def test_inbox_dao_claim_concurrency(db_conn, tmp_path):
    from superharness.engine import inbox_dao, tasks_dao, db
    from superharness.engine.tasks_dao import TaskRow
    
    tasks_dao.upsert(db_conn, TaskRow(id="t1", title="T1", owner=None, status="todo", 
        effort=None, project_path=None, development_method=None, acceptance_criteria=[], 
        test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, 
        version=1, created_at="now"))

    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a1", now="2026-01-01T00:00:00Z")
    db_conn.commit()
    
    project_dir = str(tmp_path)
    # Ensure .superharness exists for the new connections
    os.makedirs(os.path.join(project_dir, ".superharness"), exist_ok=True)
    # Use real file for concurrency test if db_conn was in-memory or closed?
    # db_conn fixture uses tmp_path, so it's a real file.
    
    results = []
    errors = []
    def do_claim():
        try:
            # Each thread needs its own connection
            conn = db.get_connection(project_dir)
            try:
                r = inbox_dao.claim_next(conn, target_agent="a1", pid=threading.get_ident(), now="now")
                if r:
                    results.append(r)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_claim) for _ in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    assert not errors, f"Threads hit errors: {errors}"
    assert len(results) == 1

def test_tasks_dao_upsert_get(db_conn):
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    task = TaskRow(
        id="t1", title="Task 1", owner="a1", status="todo",
        effort=None, project_path=None, development_method=None,
        acceptance_criteria=["ac1"], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at="now"
    )
    
    tasks_dao.upsert(db_conn, task)
    fetched = tasks_dao.get(db_conn, "t1")
    assert fetched.title == "Task 1"
    assert fetched.acceptance_criteria == ["ac1"]

def test_tasks_dao_update_optimistic_concurrency(db_conn):
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    task = TaskRow(
        id="t1", title="T1", owner=None, status="todo", effort=None, project_path=None,
        development_method=None, acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at="now"
    )
    tasks_dao.upsert(db_conn, task)
    
    # Success
    updated = tasks_dao.update(db_conn, "t1", version=1, changes={"status": "in_progress"})
    assert updated.status == "in_progress"
    assert updated.version == 2
    
    # Failure (stale version)
    with pytest.raises(ConcurrencyError):
        tasks_dao.update(db_conn, "t1", version=1, changes={"status": "done"})

def test_tasks_dependencies(db_conn):
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    t1 = TaskRow(id="t1", title="T1", owner=None, status="done", effort=None, project_path=None,
        development_method=None, acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at="now", done_at="now")
    t2 = TaskRow(id="t2", title="T2", owner=None, status="todo", effort=None, project_path=None,
        development_method=None, acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at="now")
    
    tasks_dao.upsert(db_conn, t1)
    tasks_dao.upsert(db_conn, t2)
    
    tasks_dao.set_dependencies(db_conn, "t2", ["t1"])
    
    fetched2 = tasks_dao.get(db_conn, "t2")
    assert fetched2.blocked_by == ["t1"]
    
    unblocked = tasks_dao.get_unblocked(db_conn)
    assert any(t.id == "t2" for t in unblocked)

def test_handoffs_dao(db_conn):
    from superharness.engine import handoffs_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    
    tasks_dao.upsert(db_conn, TaskRow(id="t1", title="T1", owner=None, status="todo", 
        effort=None, project_path=None, development_method=None, acceptance_criteria=[], 
        test_types=[], out_of_scope=[], definition_of_done=[], context=None, tdd=None, 
        version=1, created_at="now"))

    handoffs_dao.append(db_conn, task_id="t1", phase="plan", status="proposed", now="2026-01-01T00:00:00Z")
    handoffs_dao.append(db_conn, task_id="t1", phase="plan", status="approved", now="2026-01-01T00:01:00Z")
    
    history = handoffs_dao.get_history(db_conn, "t1")
    assert len(history) == 2
    assert history[0].status == "proposed"
    assert history[1].status == "approved"
    
    latest = handoffs_dao.get_latest(db_conn, "t1", "plan")
    assert latest.status == "approved"
