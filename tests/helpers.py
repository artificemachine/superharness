"""Shared test helpers for seeding SQLite state."""
from pathlib import Path


def seed_sqlite_from_yaml(project_path: str | Path) -> int:
    """Read contract.yaml and seed SQLite tasks table. Returns count of tasks seeded."""
    import os
    import yaml
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao

    project = Path(project_path)
    contract_path = project / ".superharness" / "contract.yaml"
    if not contract_path.exists():
        return 0

    with open(contract_path) as f:
        doc = yaml.safe_load(f) or {}
    tasks = doc.get("tasks") or []
    if not tasks:
        return 0

    conn = get_connection(str(project))
    init_db(conn)
    count = 0
    for t in tasks:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        t.setdefault("project_path", str(project))
        tasks_dao.upsert(conn, _task_row_from_dict(t, str(project), "2026-01-01T00:00:00Z"))
        count += 1
    conn.commit()
    conn.close()
    return count


def get_task_from_sqlite(project_path: str | Path, task_id: str) -> dict | None:
    """Read a task from SQLite. Returns dict or None."""
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(Path(project_path)))
    init_db(conn)
    task = tasks_dao.get(conn, task_id)
    conn.close()
    return asdict(task) if task else None
