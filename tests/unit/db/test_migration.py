from __future__ import annotations

import sqlite3
import os
import yaml
import time
from pathlib import Path

import pytest

def _create_yaml_project(base_path: Path):
    sh_dir = base_path / ".superharness"
    sh_dir.mkdir(parents=True)
    
    # contract.yaml
    contract_data = {
        "id": "test-contract",
        "tasks": [
            {
                "id": "task-1",
                "title": "Task 1",
                "owner": "claude-code",
                "status": "todo",
                "effort": "medium"
            },
            {
                "id": "task-2",
                "title": "Task 2",
                "owner": "codex-cli",
                "status": "in_progress",
                "blocked_by": "task-1"
            }
        ]
    }
    (sh_dir / "contract.yaml").write_text(yaml.dump(contract_data))
    
    # inbox.yaml
    inbox_data = [
        {
            "id": "i1",
            "task": "task-1",
            "to": "claude-code",
            "status": "pending",
            "priority": 2,
            "created_at": "2026-01-01T00:00:00Z"
        },
        {
            "id": "i2",
            "task": "task-2",
            "to": "codex-cli",
            "status": "launched",
            "pid": 1234,
            "created_at": "2026-01-01T00:01:00Z",
            "launched_at": "2026-01-01T00:02:00Z"
        }
    ]
    (sh_dir / "inbox.yaml").write_text(yaml.dump(inbox_data))
    
    # handoffs
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    h1_data = {
        "task_id": "task-2",
        "phase": "plan",
        "status": "plan_approved",
        "from_agent": "codex-cli",
        "content": "some plan content",
        "metadata": {"pr_url": "http://github.com/pr/1"},
        "created_at": "2026-01-01T00:03:00Z"
    }
    (handoffs_dir / "task-2.plan.yaml").write_text(yaml.dump(h1_data))
    
    # failures.yaml
    failures_data = {
        "failures": [
            {
                "task": "task-1",
                "agent": "claude-code",
                "pattern": "timeout",
                "error_snippet": "execution timed out",
                "date": "2026-01-01T00:04:00Z"
            }
        ]
    }
    (sh_dir / "failures.yaml").write_text(yaml.dump(failures_data))
    
    # decisions.yaml
    decisions_data = {
        "decisions": [
            {
                "agent": "codex-cli",
                "task": "task-2",
                "decision": "use-sqlite",
                "reason": "better stability",
                "date": "2026-01-01T00:05:00Z"
            }
        ]
    }
    (sh_dir / "decisions.yaml").write_text(yaml.dump(decisions_data))
    
    return sh_dir

def test_migrate_clean_project(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    project = tmp_path / "project"
    _create_yaml_project(project)
    
    # Pass an empty temp dir for workers to isolate from real HOME
    workers_root = tmp_path / "empty_workers"
    workers_root.mkdir()
    
    report = migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    
    assert report.tasks_imported == 2
    assert report.inbox_imported == 2
    assert report.handoffs_imported == 1
    assert report.failures_imported == 1
    assert report.decisions_imported == 1
    assert len(report.errors) == 0

    # Verify task data
    cursor = db_conn.execute("SELECT id, title, owner, status FROM tasks WHERE id='task-1'")
    row = cursor.fetchone()
    assert row["title"] == "Task 1"
    assert row["owner"] == "claude-code"
    assert row["status"] == "todo"

    # Verify dependencies
    cursor = db_conn.execute("SELECT prerequisite_task_id FROM task_dependencies WHERE dependent_task_id='task-2'")
    assert cursor.fetchone()[0] == "task-1"

    # Verify inbox
    cursor = db_conn.execute("SELECT id, status, pid FROM inbox WHERE id='i2'")
    row = cursor.fetchone()
    assert row["status"] == "launched"
    assert row["pid"] == 1234

def test_migration_idempotency(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    project = tmp_path / "project"
    _create_yaml_project(project)
    
    workers_root = tmp_path / "empty_workers"
    workers_root.mkdir()
    
    migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    
    cursor = db_conn.execute("SELECT count(*) FROM tasks")
    assert cursor.fetchone()[0] == 2
    cursor = db_conn.execute("SELECT count(*) FROM inbox")
    assert cursor.fetchone()[0] == 2

def test_migrate_corrupt_yaml(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    from superharness.engine.ledger_dao import get_recent
    project = tmp_path / "project"
    sh_dir = _create_yaml_project(project)
    
    # Corrupt one file
    (sh_dir / "inbox.yaml").write_text("!!corrupt {")
    
    workers_root = tmp_path / "empty_workers"
    workers_root.mkdir()
    
    report = migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    
    assert report.inbox_imported == 0
    assert report.tasks_imported == 2 # Other files still migrate
    assert len(report.errors) == 1
    assert "inbox.yaml" in report.errors[0]
    
    ledger = get_recent(db_conn, limit=10)
    assert any(l.action == "migration_error" for l in ledger)

def test_migrate_orphaned_handoff(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    project = tmp_path / "project"
    sh_dir = _create_yaml_project(project)
    
    # Handoff for non-existent task
    h_orph = {
        "task_id": "ghost-task",
        "phase": "plan",
        "status": "plan_proposed",
        "created_at": "2026-01-01T00:06:00Z"
    }
    (sh_dir / "handoffs" / "ghost.yaml").write_text(yaml.dump(h_orph))
    
    workers_root = tmp_path / "empty_workers"
    workers_root.mkdir()
    
    report = migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    assert report.handoffs_imported == 1 # only task-2
    assert any("orphaned handoff" in e.lower() for e in report.errors)

def test_migrate_worker_dir(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    project = tmp_path / "project"
    _create_yaml_project(project)
    
    # Setup worker dir
    workers_root = tmp_path / "workers"
    workers_root.mkdir()
    worker_dir = workers_root / "worker-1"
    worker_sh = worker_dir / ".superharness"
    worker_sh.mkdir(parents=True)
    
    # Worker has its own inbox item
    worker_inbox = [
        {
            "id": "iw1",
            "task": "task-1",
            "to": "claude-code",
            "status": "pending",
            "created_at": "2026-01-01T00:10:00Z"
        }
    ]
    (worker_sh / "inbox.yaml").write_text(yaml.dump(worker_inbox))
    
    report = migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    
    assert report.inbox_imported == 3 # 2 from main + 1 from worker
    assert str(worker_dir) in report.worker_dirs_migrated

def test_migrate_reviews_db(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    project = tmp_path / "project"
    sh_dir = _create_yaml_project(project)
    
    # Create old reviews.db
    rev_db_path = sh_dir / "reviews.db"
    src_conn = sqlite3.connect(rev_db_path)
    src_conn.execute("CREATE TABLE review_store (owner TEXT, task_type TEXT, duration_s REAL, score REAL, failed INTEGER)")
    src_conn.execute("INSERT INTO review_store VALUES (?, ?, ?, ?, ?)", ("claude-code", "refactor", 120.5, 0.9, 0))
    src_conn.commit()
    src_conn.close()
    
    workers_root = tmp_path / "empty_workers"
    workers_root.mkdir()
    
    report = migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    assert report.review_imported == 1
    
    cursor = db_conn.execute("SELECT owner, score FROM review_store")
    row = cursor.fetchone()
    assert row["owner"] == "claude-code"
    assert row["score"] == 0.9

def test_large_project_performance(db_conn, tmp_path):
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite
    project = tmp_path / "large_project"
    sh_dir = project / ".superharness"
    sh_dir.mkdir(parents=True)
    
    # 10k tasks
    tasks = []
    for i in range(10000):
        tasks.append({
            "id": f"task-{i}",
            "title": f"Task {i}",
            "status": "todo",
            "created_at": "2026-01-01T00:00:00Z"
        })
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": tasks}))
    
    workers_root = tmp_path / "empty_workers"
    workers_root.mkdir()
    
    start_time = time.time()
    report = migrate_all_to_sqlite(db_conn, str(project), workers_root=str(workers_root))
    duration = time.time() - start_time
    
    assert report.tasks_imported == 10000
    assert duration < 10.0
