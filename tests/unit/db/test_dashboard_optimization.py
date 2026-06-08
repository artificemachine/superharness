from __future__ import annotations

import time
import yaml

from superharness.engine import tasks_dao, inbox_dao


def _measure_sqlite(db_conn, project_dir) -> float:
    from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
    start = time.perf_counter()
    snap = get_dashboard_status_snapshot(db_conn, str(project_dir))
    elapsed = time.perf_counter() - start
    assert len(snap["inbox_items"]) <= 200, (
        "inbox_items is capped at 200 to keep the payload small; "
        "if this threshold changes, update the cap in dashboard_presenter.py"
    )
    return elapsed


def _measure_yaml(sh_dir) -> float:
    start = time.perf_counter()
    with open(sh_dir / "inbox.yaml", "r") as f:
        yaml.safe_load(f)
    with open(sh_dir / "contract.yaml", "r") as f:
        yaml.safe_load(f)
    return time.perf_counter() - start


def test_dashboard_optimization_perf(db_conn, tmp_path):
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
    inbox_data = [
        {"id": f"i{i}", "task": f"task-{i}", "to": "claude-code", "status": "pending"}
        for i in range(1000)
    ]
    tasks_data = [
        {"id": f"task-{i}", "title": f"Task {i}", "owner": "claude-code", "status": "todo"}
        for i in range(1000)
    ]
    (sh_dir / "inbox.yaml").write_text(yaml.dump(inbox_data))
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": tasks_data}))

    # 3. Measure both paths 3 times each, take the best (min) run.
    # Absolute thresholds are unreliable on shared CI runners (the previous
    # `assert sql_duration < 0.3` flaked on macos-latest at 0.35s). The
    # optimization claim is "SQLite path is faster than re-parsing YAML",
    # so assert the relative comparison and let runner noise affect both
    # measurements equally.
    sql_runs = [_measure_sqlite(db_conn, project_dir) for _ in range(3)]
    yaml_runs = [_measure_yaml(sh_dir) for _ in range(3)]
    sql_duration = min(sql_runs)
    yaml_duration = min(yaml_runs)

    print(f"\nSQLite duration (best of 3): {sql_duration:.4f}s  (runs: {[f'{r:.4f}' for r in sql_runs]})")
    print(f"YAML duration   (best of 3): {yaml_duration:.4f}s  (runs: {[f'{r:.4f}' for r in yaml_runs]})")

    assert sql_duration < yaml_duration, (
        f"Dashboard optimization regressed: SQLite path ({sql_duration:.4f}s) "
        f"was not faster than re-parsing YAML ({yaml_duration:.4f}s)"
    )
