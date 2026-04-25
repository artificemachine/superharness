from __future__ import annotations

import sqlite3
import time
import os
import yaml
from pathlib import Path

import pytest
from superharness.engine import tasks_dao, inbox_dao, ledger_dao, db

def test_dashboard_optimization_perf(db_conn, tmp_path):
    from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
    
    project_dir = tmp_path
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    
    # 1. Setup 1000 items in SQLite
    for i in range(1000):
        t_id = f"task-{i}"
        tasks_dao.upsert(db_conn, tasks_dao.TaskRow(
            id=t_id, title=f"Task {i}", owner="claude-code", status="todo",
            effort="medium", project_path=str(project_dir),
            development_method=None, acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z"
        ))
        inbox_dao.enqueue(db_conn, id=f"i{i}", task_id=t_id, target_agent="claude-code", now="2026-01-01T00:00:00Z")
    
    db_conn.commit()
    
    # 2. Setup 1000 items in YAML for baseline
    inbox_data = []
    tasks_data = []
    for i in range(1000):
        inbox_data.append({"id": f"i{i}", "task": f"task-{i}", "to": "claude-code", "status": "pending"})
        tasks_data.append({"id": f"task-{i}", "title": f"Task {i}", "owner": "claude-code", "status": "todo"})
    
    (sh_dir / "inbox.yaml").write_text(yaml.dump(inbox_data))
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": tasks_data}))
    
    # 3. Measure SQLite path
    start_sql = time.perf_counter()
    status_sql = get_dashboard_status_snapshot(db_conn, str(project_dir))
    end_sql = time.perf_counter()
    sql_duration = end_sql - start_sql
    
    # 4. Measure YAML path (simulated using old dashboard-ui logic)
    # We don't have the old logic easily available as a module, 
    # but we know it reads files.
    start_yaml = time.perf_counter()
    with open(sh_dir / "inbox.yaml", "r") as f: yaml.safe_load(f)
    with open(sh_dir / "contract.yaml", "r") as f: yaml.safe_load(f)
    end_yaml = time.perf_counter()
    yaml_duration = end_yaml - start_yaml
    
    print(f"\nSQLite duration: {sql_duration:.4f}s")
    print(f"YAML duration:   {yaml_duration:.4f}s")
    
    assert len(status_sql["inbox_items"]) == 1000
    assert sql_duration < 0.3 # Should be fast
