from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "src" / "superharness" / "scripts"


def run_bash(script: Path, *, cwd: Path, stdin: str | None = None, env: dict[str, str] | None = None, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        for k, v in env.items():
            if v is None:
                merged_env.pop(k, None)
            else:
                merged_env[k] = v
    command = ["bash", str(script)]
    if args:
        command.extend(args)
    return subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def run_cmd(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def copy_from_repo(rel_path: str, dest_root: Path) -> Path:
    src = REPO_ROOT / rel_path
    dst = dest_root / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(src.stat().st_mode)
    return dst


def shell_guard_list(repo_root: Path, flag: str) -> list[str]:
    result = run_bash(
        SCRIPTS_DIR / "check-shell-entrypoints.sh",
        cwd=repo_root,
        args=[flag],
    )
    if result.returncode != 0:
        raise RuntimeError(f"check-shell-entrypoints {flag} failed: {result.stderr}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_json_output(stdout: str) -> dict[str, object]:
    return json.loads(stdout)


# --- SQLite fixture helpers (added 2026-04-30) ---

def seed_sqlite_from_yaml(project_path):
    """Read contract.yaml and seed SQLite tasks table."""
    import yaml
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao
    project = Path(str(project_path))
    contract = project / '.superharness' / 'contract.yaml'
    if not contract.exists():
        return 0
    with open(contract) as f:
        doc = yaml.safe_load(f) or {}
    tasks = doc.get('tasks') or []
    if not tasks:
        return 0
    conn = get_connection(str(project))
    init_db(conn)
    count = 0
    for t in tasks:
        if not isinstance(t, dict) or not t.get('id'):
            continue
        t.setdefault('project_path', str(project))
        tasks_dao.upsert(conn, _task_row_from_dict(t, str(project), '2026-01-01T00:00:00Z'))
        count += 1
    conn.commit()
    conn.close()
    return count


def get_task_from_sqlite(project_path, task_id):
    """Read a task from SQLite. Returns dict or None."""
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    conn = get_connection(str(Path(project_path)))
    init_db(conn)
    task = tasks_dao.get(conn, task_id)
    conn.close()
    return asdict(task) if task else None
