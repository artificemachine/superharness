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
    """Read contract.yaml + inbox.yaml and seed the SQLite tasks/inbox tables.

    Tests historically write contract.yaml / inbox.yaml fixtures; post
    YAML→SQLite migration the production code reads SQLite, so this
    helper hydrates the DB from the fixture files."""
    import yaml
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao
    project = Path(str(project_path))
    contract = project / '.superharness' / 'contract.yaml'
    inbox = project / '.superharness' / 'inbox.yaml'
    if not contract.exists() and not inbox.exists():
        return 0
    # Pre-touch the legacy db path so get_connection uses it for test isolation.
    # Without this, get_connection creates the db at the XDG path, but test
    # helpers that read the db use the legacy path and find nothing.
    import sqlite3 as _sq
    _legacy = project / '.superharness' / 'state.sqlite3'
    _legacy.parent.mkdir(parents=True, exist_ok=True)
    if not _legacy.exists():
        _sq.connect(str(_legacy)).close()
    conn = get_connection(str(project))
    init_db(conn)
    count = 0

    # Tasks
    if contract.exists():
        with open(contract) as f:
            doc = yaml.safe_load(f) or {}
        # Persist contract-level metadata (id, goal) to project_meta table
        for _key in ("id", "goal"):
            _val = doc.get(_key)
            if _val is not None:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO project_meta (key, value) VALUES (?, ?)",
                        (_key, str(_val)),
                    )
                except Exception:
                    pass
        conn.commit()
        import json as _j
        for t in (doc.get('tasks') or []):
            if not isinstance(t, dict) or not t.get('id'):
                continue
            t.setdefault('project_path', str(project))
            tasks_dao.upsert(conn, _task_row_from_dict(t, str(project), '2026-01-01T00:00:00Z'))
            # Persist soft blocked_by (raw, including refs to non-existent tasks)
            raw = t.get('blocked_by') or t.get('dependency')
            if raw is not None:
                if isinstance(raw, list):
                    items = [str(x).strip() for x in raw
                             if x and str(x).strip()
                             and str(x).strip().lower() not in ('none', 'null', '~')]
                else:
                    s = str(raw).strip()
                    if s.lower() in ('none', 'null', '~', '', '[]'):
                        items = []
                    else:
                        items = [d.strip() for d in s.split(',') if d.strip()
                                 and d.strip().lower() not in ('none', 'null', '~')]
                try:
                    conn.execute(
                        "UPDATE tasks SET blocked_by_raw = ? WHERE id = ?",
                        (_j.dumps(items), t['id']),
                    )
                except Exception:
                    pass
            # Stamped per-task fields (v10): workflow, autonomy, require_tdd
            stamped = {}
            if 'workflow' in t:
                stamped['workflow'] = t['workflow']
            if 'autonomy' in t:
                stamped['autonomy'] = t['autonomy']
            if 'require_tdd' in t:
                stamped['require_tdd'] = 1 if t['require_tdd'] else 0
            for col, val in stamped.items():
                try:
                    conn.execute(
                        f"UPDATE tasks SET {col} = ? WHERE id = ?",
                        (val, t['id']),
                    )
                except Exception:
                    pass
            # v11 extras_json — nested per-task metadata
            extras = {k: t[k] for k in ('subtasks', 'classifier', 'decomposer', 'retry')
                      if k in t and t[k] is not None}
            if extras:
                try:
                    conn.execute(
                        "UPDATE tasks SET extras_json = ? WHERE id = ?",
                        (_j.dumps(extras), t['id']),
                    )
                except Exception:
                    pass
            count += 1
        conn.commit()

    # Decisions
    decisions = project / '.superharness' / 'decisions.yaml'
    if decisions.exists():
        try:
            with open(decisions) as f:
                ddoc = yaml.safe_load(f) or {}
            for entry in (ddoc.get('decisions') or []):
                if not isinstance(entry, dict):
                    continue
                # alternatives must be valid JSON — _row_to_decision calls
                # json.loads on the column.
                import json as _j
                conn.execute(
                    "INSERT INTO decisions (task_id, decision, reason, alternatives, agent, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (entry.get('task'), entry.get('decision', ''),
                     entry.get('reason') or entry.get('rationale'),
                     _j.dumps(entry.get('alternatives', []) or []),
                     entry.get('agent', 'claude-code'),
                     entry.get('date', '2026-01-01T00:00:00Z')),
                )
            conn.commit()
        except Exception:
            pass

    # Failures — task_id is FK'd to tasks(id) since migration v33, so auto-stub
    # any referenced task not already seeded from contract.yaml (test fixtures
    # often reference a task deliberately absent from the contract, e.g. to
    # exercise "unrelated failure" filtering). Mirrors the inbox auto-stub
    # block below.
    failures = project / '.superharness' / 'failures.yaml'
    if failures.exists():
        try:
            from superharness.engine.tasks_dao import TaskRow as _TaskRowF, upsert as _upsertF
            with open(failures) as f:
                fdoc = yaml.safe_load(f) or {}
            for entry in (fdoc.get('failures') or []):
                if not isinstance(entry, dict):
                    continue
                tid = entry.get('task')
                if tid and not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone():
                    try:
                        _upsertF(conn, _TaskRowF(
                            id=str(tid), title=str(tid), owner=None,
                            status='todo', effort=None,
                            project_path=str(project),
                            development_method=None,
                            acceptance_criteria=[], test_types=[],
                            out_of_scope=[], definition_of_done=[],
                            context=None, tdd=None, version=1,
                            created_at='2026-01-01T00:00:00Z',
                        ))
                    except Exception:
                        pass
                conn.execute(
                    "INSERT INTO failures (task_id, agent, pattern, error_snippet, created_at) VALUES (?, ?, ?, ?, ?)",
                    (tid, entry.get('agent', 'claude-code'),
                     entry.get('patterns', 'unknown') if not isinstance(entry.get('patterns'), list)
                       else ','.join(entry.get('patterns', []) or []),
                     entry.get('failure', '') or entry.get('error_snippet', ''),
                     entry.get('date', '2026-01-01T00:00:00Z')),
                )
            conn.commit()
        except Exception:
            pass

    # Inbox — must run after tasks so the FK is satisfied. If a YAML
    # inbox item references a task ID we haven't seeded (test fixtures
    # often skip the contract for brevity), auto-stub the parent task
    # so the FK passes.
    if inbox.exists():
        try:
            from superharness.engine.tasks_dao import TaskRow as _TaskRowAS, upsert as _upsertAS
            with open(inbox) as _f:
                _idoc = yaml.safe_load(_f) or []
            if isinstance(_idoc, dict):
                _idoc = _idoc.get('items') or []
            for it in _idoc:
                if not isinstance(it, dict):
                    continue
                tid = it.get('task') or it.get('task_id')
                if tid and not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone():
                    try:
                        _upsertAS(conn, _TaskRowAS(
                            id=str(tid), title=str(tid), owner=None,
                            status='todo', effort=None,
                            project_path=str(project),
                            development_method=None,
                            acceptance_criteria=[], test_types=[],
                            out_of_scope=[], definition_of_done=[],
                            context=None, tdd=None, version=1,
                            created_at='2026-01-01T00:00:00Z',
                        ))
                    except Exception:
                        pass
            conn.commit()
        except Exception:
            pass

    if inbox.exists():
        with open(inbox) as f:
            inbox_doc = yaml.safe_load(f) or []
        if isinstance(inbox_doc, dict):
            inbox_doc = inbox_doc.get('items') or []
        for it in inbox_doc:
            if not isinstance(it, dict) or not it.get('id') or not it.get('task'):
                continue
            cols = ('id', 'task_id', 'target_agent', 'status', 'priority',
                    'retry_count', 'max_retries', 'pid', 'project_path',
                    'plan_only', 'failed_reason', 'created_at',
                    'launched_at', 'last_heartbeat', 'paused_at',
                    'failed_at', 'done_at')
            row = {c: None for c in cols}
            row['id'] = it['id']
            row['task_id'] = it['task']
            row['target_agent'] = it.get('to') or it.get('target_agent') or 'claude-code'
            row['status'] = it.get('status', 'pending')
            row['priority'] = int(it.get('priority', 2) or 2)
            row['retry_count'] = int(it.get('retry_count', 0) or 0)
            row['max_retries'] = int(it.get('max_retries', 3) or 3)
            row['pid'] = it.get('pid')
            row['project_path'] = it.get('project') or it.get('project_path') or str(project)
            row['plan_only'] = 1 if it.get('plan_only') else 0
            row['failed_reason'] = it.get('failed_reason')
            row['created_at'] = it.get('created_at') or '2026-01-01T00:00:00Z'
            row['launched_at'] = it.get('launched_at')
            row['last_heartbeat'] = it.get('last_heartbeat')
            row['paused_at'] = it.get('paused_at')
            row['failed_at'] = it.get('failed_at')
            row['done_at'] = it.get('done_at')
            placeholders = ','.join('?' * len(cols))
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO inbox ({','.join(cols)}) VALUES ({placeholders})",
                    [row[c] for c in cols],
                )
            except Exception:
                pass  # best-effort hydration
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


def _ensure_task_stub(conn, task_id: str, project_path: str, now: str = "2026-01-01T00:00:00Z") -> None:
    """Create a minimal stub task row if none exists (satisfies handoffs FK)."""
    if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, status, project_path, created_at, version)"
            " VALUES (?, ?, 'todo', ?, ?, 1)",
            (task_id, task_id, project_path, now),
        )


def seed_sqlite_handoff(
    project_path,
    task_id: str,
    *,
    phase: str = "report",
    status: str = "done",
    content: "str | dict | None" = None,
    from_agent: str | None = "claude-code",
    to_agent: str | None = None,
    now: str = "2026-01-01T00:00:00Z",
) -> None:
    """Insert a handoff record into SQLite. Creates a stub task if needed.

    `content` may be a YAML string, a dict (serialized to YAML + stored as metadata), or None.
    """
    import sqlite3 as _sq
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import handoffs_dao
    project = Path(str(project_path))
    _legacy = project / ".superharness" / "state.sqlite3"
    _legacy.parent.mkdir(parents=True, exist_ok=True)
    if not _legacy.exists():
        _sq.connect(str(_legacy)).close()
    conn = get_connection(str(project))
    init_db(conn)
    _ensure_task_stub(conn, task_id, str(project), now)
    metadata: dict | None = None
    if isinstance(content, dict):
        import yaml as _yaml
        body = _yaml.dump(content, default_flow_style=False, allow_unicode=True)
        metadata = content
    else:
        body = content or f"task: {task_id}\nphase: {phase}\nstatus: {status}\n"
    handoffs_dao.append(
        conn,
        task_id=task_id,
        phase=phase,
        status=status,
        from_agent=from_agent,
        to_agent=to_agent,
        content=body,
        metadata=metadata,
        now=now,
    )
    conn.commit()
    conn.close()


def seed_sqlite_ledger(
    project_path,
    *,
    action: str,
    task_id: str | None = None,
    agent: str | None = "claude-code",
    now: str = "2026-01-01T00:00:00Z",
) -> None:
    """Insert a ledger entry into SQLite."""
    import sqlite3 as _sq
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import ledger_dao
    project = Path(str(project_path))
    _legacy = project / ".superharness" / "state.sqlite3"
    _legacy.parent.mkdir(parents=True, exist_ok=True)
    if not _legacy.exists():
        _sq.connect(str(_legacy)).close()
    conn = get_connection(str(project))
    init_db(conn)
    ledger_dao.record(conn, task_id=task_id, agent=agent, action=action, now=now)
    conn.commit()
    conn.close()


def seed_sqlite_heartbeat(
    project_path,
    *,
    agent: str,
    status: str = "ok",
    now: str = "2026-06-01T00:00:00Z",
) -> None:
    """Insert a heartbeat record into SQLite."""
    import sqlite3 as _sq
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import heartbeat_dao
    project = Path(str(project_path))
    _legacy = project / ".superharness" / "state.sqlite3"
    _legacy.parent.mkdir(parents=True, exist_ok=True)
    if not _legacy.exists():
        _sq.connect(str(_legacy)).close()
    conn = get_connection(str(project))
    init_db(conn)
    heartbeat_dao.upsert(conn, agent=agent, status=status, now=now)
    conn.commit()
    conn.close()
