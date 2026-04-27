from __future__ import annotations

import yaml
from unittest.mock import patch, MagicMock

from superharness.engine import parity, tasks_dao
from superharness.engine.tasks_dao import TaskRow

T0 = "2026-01-01T00:00:00Z"


def _task(id, status="todo", title="T", owner=None):
    return TaskRow(
        id=id, title=title, owner=owner, status=status, effort=None,
        project_path=None, development_method=None, acceptance_criteria=[],
        test_types=[], out_of_scope=[], definition_of_done=[],
        context=None, tdd=None, version=1, created_at=T0,
        blocked_by=[],
    )


def _setup_sh(tmp_path):
    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    return sh_dir


def test_parity_clean(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.only_in_db == 0
    assert task_drift.only_in_yaml == 0


def test_parity_drift_only_in_db(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    tasks_dao.upsert(db_conn, _task("t2"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.only_in_db == 1
    assert not report.healthy


def test_parity_drift_only_in_yaml(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1"}, {"id": "t2"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.only_in_yaml == 1
    assert not report.healthy


def test_heal_enqueues_ops(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    tasks_dao.upsert(db_conn, _task("t2"))
    # Only t1 in YAML
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    enqueued = parity.heal_parity(db_conn, project_dir, report)
    assert enqueued >= 1


# B1: parity covers handoffs, failures, decisions
def test_parity_covers_handoffs(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()

    # Task must exist in DB (handoffs FK-reference tasks)
    tasks_dao.upsert(db_conn, _task("t1"))
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": [{"id": "t1", "title": "T"}]}))

    # Write a handoff file (YAML-only, no DB row)
    (handoffs_dir / "plan-t1-20260101.yaml").write_text(
        yaml.dump({"task": "t1", "phase": "plan", "status": "plan_proposed", "date": T0})
    )

    report = parity.check_parity(db_conn, project_dir)
    h_drift = next(d for d in report.drifts if d.table == "handoffs")
    assert h_drift.only_in_yaml >= 1
    assert not report.healthy


def test_parity_covers_failures(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    # DB-only failure row
    db_conn.execute(
        "INSERT INTO failures (task_id, agent, pattern, error_snippet, created_at)"
        " VALUES ('t1','claude-code','timeout','err',?)", (T0,)
    )
    db_conn.commit()
    (sh_dir / "failures.yaml").write_text(yaml.dump({"failures": []}))

    report = parity.check_parity(db_conn, project_dir)
    f_drift = next(d for d in report.drifts if d.table == "failures")
    assert f_drift.only_in_db >= 1


def test_parity_covers_decisions(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    (sh_dir / "decisions.yaml").write_text(
        yaml.dump({
            "decisions": [
                {"agent": "claude-code", "task": "t1", "decision": "use sqlite", "date": T0}
            ]
        })
    )

    report = parity.check_parity(db_conn, project_dir)
    d_drift = next(d for d in report.drifts if d.table == "decisions")
    assert d_drift.only_in_yaml >= 1


# B2: subtasks nested under parent in YAML are visible to parity
def test_parity_subtask_nested_in_yaml(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    # Parent in both; subtask only in DB (mirrors what _sqlite_mirror_orchestrate does)
    tasks_dao.upsert(db_conn, _task("parent"))
    tasks_dao.upsert(db_conn, _task("sub1"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({
            "tasks": [
                {"id": "parent", "title": "Parent", "subtasks": [{"id": "sub1", "title": "Sub"}]}
            ]
        })
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    # sub1 is visible in YAML via subtask flattening — no drift
    assert task_drift.only_in_db == 0
    assert task_drift.only_in_yaml == 0
    assert report.healthy or all(
        d.only_in_db == 0 and d.only_in_yaml == 0 for d in report.drifts
    )


def test_parity_subtask_only_in_db_detected(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    # Parent in YAML with NO subtasks listed; subtask upserted to DB only
    tasks_dao.upsert(db_conn, _task("parent"))
    tasks_dao.upsert(db_conn, _task("sub1"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "parent", "title": "Parent"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.only_in_db == 1  # sub1 is in DB but not in YAML or its subtasks


# B3: heal_parity is idempotent — calling twice does not duplicate ops
def test_heal_parity_is_idempotent(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    tasks_dao.upsert(db_conn, _task("t2"))
    # Use explicit title/status matching the DB row to avoid triggering mismatched drift
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": [{"id": "t1", "title": "T", "status": "todo"}]}))

    report = parity.check_parity(db_conn, project_dir)
    first = parity.heal_parity(db_conn, project_dir, report)
    second = parity.heal_parity(db_conn, project_dir, report)

    queue_count = db_conn.execute(
        "SELECT COUNT(*) FROM yaml_sync_queue WHERE status='pending'"
    ).fetchone()[0]
    # Second call should have enqueued 0 new ops
    assert second == 0
    assert queue_count == first


# B4: heal_parity closes only_in_yaml gap by upserting YAML tasks to SQLite
def test_heal_parity_yaml_to_db(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    # YAML has t1 and t2; SQLite only has t1 (simulates crash between YAML write and SQLite write)
    tasks_dao.upsert(db_conn, _task("t1"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1"}, {"id": "t2", "title": "T2"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.only_in_yaml == 1

    healed = parity.heal_parity(db_conn, project_dir, report)
    assert healed >= 1

    # t2 should now be in SQLite
    row = db_conn.execute("SELECT id FROM tasks WHERE id='t2'").fetchone()
    assert row is not None


# F6: mismatched field detection
def test_parity_detects_mismatched_fields(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)

    # DB has status=done; YAML still shows todo
    tasks_dao.upsert(db_conn, _task("t1", status="done", title="T1"))
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": "t1", "status": "todo", "title": "T1"}]})
    )

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.mismatched == 1
    assert not report.healthy


# F7: foreign key check included in report
def test_parity_foreign_key_clean(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": []}))

    report = parity.check_parity(db_conn, project_dir)
    assert report.foreign_key_violations == 0


# Integration: full orchestrator cycle leaves parity clean (no mismatched drift)
def test_parity_clean_after_orchestrator_subtask_normalisation(db_conn, tmp_path):
    """Orchestrator-style subtasks (no explicit status field) must not produce drift.

    Regression guard: ensures _write_subtasks_to_contract and _sqlite_mirror_orchestrate
    both agree on default status='pending' so F6's hash comparison stays clean.
    """
    sh_dir = _setup_sh(tmp_path)
    project_dir = str(tmp_path)
    contract_path = sh_dir / "contract.yaml"

    # Seed a parent task (top-level, status="todo")
    tasks_dao.upsert(db_conn, _task("parent"))
    contract_path.write_text(yaml.dump({"tasks": [{"id": "parent", "title": "T", "status": "todo"}]}))

    # Simulate orchestrator output: subtasks with NO explicit status field
    raw_subtasks = [
        {"id": "parent.0", "title": "Sub 0", "model_tier": "standard", "estimated_tokens": 30000},
        {"id": "parent.1", "title": "Sub 1", "model_tier": "max", "estimated_tokens": 50000},
    ]

    # Mimic _write_subtasks_to_contract normalisation (status="pending", owner="claude-code")
    normalised = []
    for st in raw_subtasks:
        st = dict(st)
        st.setdefault("status", "pending")
        st.setdefault("owner", "claude-code")
        normalised.append(st)

    # Write nested subtasks into contract.yaml
    doc = {"tasks": [{"id": "parent", "title": "T", "status": "todo", "subtasks": normalised}]}
    contract_path.write_text(yaml.dump(doc))

    # Mimic _sqlite_mirror_orchestrate: upsert subtasks with default status="pending"
    for st in raw_subtasks:
        tasks_dao.upsert(db_conn, _task(st["id"], status="pending", title=st["title"], owner="claude-code"))

    report = parity.check_parity(db_conn, project_dir)
    task_drift = next(d for d in report.drifts if d.table == "tasks")
    assert task_drift.only_in_db == 0
    assert task_drift.only_in_yaml == 0
    assert task_drift.mismatched == 0, (
        "Subtask normalisation must keep YAML and SQLite hashes aligned"
    )


# _heal_handoffs_db_to_yaml: DB→YAML direction for handoff drift

def _insert_handoff(conn, task_id, phase="report", status="report_ready",
                    from_agent="claude-code", to_agent="owner", created_at=T0):
    conn.execute(
        "INSERT INTO handoffs (task_id, phase, status, from_agent, to_agent, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (task_id, phase, status, from_agent, to_agent, created_at),
    )
    conn.commit()


def _contract(sh_dir, tasks):
    """Write contract.yaml with tasks matched exactly to _task() defaults (title=T, status=todo)."""
    (sh_dir / "contract.yaml").write_text(
        yaml.dump({"tasks": [{"id": t, "title": "T", "status": "todo"} for t in tasks]})
    )


def test_heal_handoffs_db_to_yaml_writes_missing_file(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    _contract(sh_dir, ["t1"])
    _insert_handoff(db_conn, "t1", created_at=T0)

    report = parity.check_parity(db_conn, project_dir)
    h_drift = next(d for d in report.drifts if d.table == "handoffs")
    assert h_drift.only_in_db == 1

    healed = parity.heal_parity(db_conn, project_dir, report)
    assert healed >= 1

    yaml_files = list(handoffs_dir.glob("*.yaml"))
    assert len(yaml_files) == 1
    doc = yaml.safe_load(yaml_files[0].read_text())
    assert doc["task_id"] == "t1"
    assert doc["phase"] == "report"
    assert doc["date"] == T0


def test_heal_handoffs_db_to_yaml_idempotent(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    _contract(sh_dir, ["t1"])
    _insert_handoff(db_conn, "t1", created_at=T0)

    report = parity.check_parity(db_conn, project_dir)
    parity.heal_parity(db_conn, project_dir, report)

    # Second run: handoff drift is gone, heal writes nothing new
    report2 = parity.check_parity(db_conn, project_dir)
    h_drift2 = next(d for d in report2.drifts if d.table == "handoffs")
    assert h_drift2.only_in_db == 0

    healed2 = parity.heal_parity(db_conn, project_dir, report2)
    assert healed2 == 0
    assert len(list(handoffs_dir.glob("*.yaml"))) == 1


def test_heal_handoffs_db_to_yaml_skips_orphaned_task(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    # Insert handoff for a task that does NOT exist in tasks table
    db_conn.execute("PRAGMA foreign_keys = OFF")
    _insert_handoff(db_conn, "ghost-task", created_at=T0)
    db_conn.execute("PRAGMA foreign_keys = ON")
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": []}))

    report = parity.check_parity(db_conn, project_dir)
    parity.heal_parity(db_conn, project_dir, report)

    # Orphaned handoff must not produce a YAML file
    assert len(list(handoffs_dir.glob("*.yaml"))) == 0


def test_heal_handoffs_db_to_yaml_skips_already_matched(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    _contract(sh_dir, ["t1"])
    _insert_handoff(db_conn, "t1", created_at=T0)

    # Pre-write a YAML file with the same (task_id, date) key — no drift
    (handoffs_dir / "existing.yaml").write_text(
        yaml.dump({"task": "t1", "task_id": "t1", "date": T0, "phase": "report"})
    )

    report = parity.check_parity(db_conn, project_dir)
    h_drift = next(d for d in report.drifts if d.table == "handoffs")
    assert h_drift.only_in_db == 0

    healed = parity.heal_parity(db_conn, project_dir, report)
    assert healed == 0
    assert len(list(handoffs_dir.glob("*.yaml"))) == 1  # no new file written


def test_heal_handoffs_db_to_yaml_empty_created_at(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    _contract(sh_dir, ["t1"])
    _insert_handoff(db_conn, "t1", created_at="")  # empty timestamp edge case

    report = parity.check_parity(db_conn, project_dir)
    h_drift = next(d for d in report.drifts if d.table == "handoffs")
    assert h_drift.only_in_db == 1

    healed = parity.heal_parity(db_conn, project_dir, report)
    assert healed >= 1

    yaml_files = list(handoffs_dir.glob("*.yaml"))
    assert len(yaml_files) == 1
    doc = yaml.safe_load(yaml_files[0].read_text())
    assert "date" not in doc  # empty date omitted from output


def test_heal_handoffs_db_to_yaml_multiple_rows_same_task(db_conn, tmp_path):
    sh_dir = _setup_sh(tmp_path)
    handoffs_dir = sh_dir / "handoffs"
    handoffs_dir.mkdir()
    project_dir = str(tmp_path)

    tasks_dao.upsert(db_conn, _task("t1"))
    _contract(sh_dir, ["t1"])
    _insert_handoff(db_conn, "t1", phase="plan", created_at="2026-01-01T00:00:00Z")
    _insert_handoff(db_conn, "t1", phase="report", created_at="2026-01-02T00:00:00Z")

    report = parity.check_parity(db_conn, project_dir)
    h_drift = next(d for d in report.drifts if d.table == "handoffs")
    assert h_drift.only_in_db == 2

    parity.heal_parity(db_conn, project_dir, report)

    yaml_files = list(handoffs_dir.glob("*.yaml"))
    assert len(yaml_files) == 2  # one file per row, no filename collision


# F9: _sqlite_tick calls heal_parity after drain when drift is present
def test_sqlite_tick_heals_parity_after_drain(tmp_path):
    """_sqlite_tick must call parity.heal_parity when check_parity returns unhealthy."""
    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir()
    (sh_dir / "contract.yaml").write_text(yaml.dump({"tasks": []}))
    (sh_dir / "failures.yaml").write_text(yaml.dump({"failures": []}))
    (sh_dir / "decisions.yaml").write_text(yaml.dump({"decisions": []}))
    (sh_dir / "handoffs").mkdir()

    from superharness.commands.inbox_watch import _sqlite_tick

    unhealthy_report = MagicMock()
    unhealthy_report.healthy = False

    with patch("superharness.engine.parity.check_parity", return_value=unhealthy_report) as mock_check, \
         patch("superharness.engine.parity.heal_parity", return_value=1) as mock_heal:
        _sqlite_tick(str(tmp_path), "2026-01-01T00:00:00Z")

    mock_check.assert_called_once()
    mock_heal.assert_called_once()
