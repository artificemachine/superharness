"""Auto-recover journals an infra escalation in the failures table.

When a task has used every recovery and its last failure looks like an
infrastructure fault (for example "command not found"), auto-recover records
that escalation in the failures ledger. The call used to pass keyword
arguments that ``failures_dao.record`` does not accept, so it raised a
TypeError that was logged and dropped: the escalation was never recorded.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from superharness.commands.inbox_watch import (
    _RECOVERY_MAX,
    _auto_recover_exhausted_failures_sqlite,
)
from superharness.engine.db import get_connection, init_db

NOW = "2026-10-26T00:00:00Z"


def _project_with_exhausted_infra_failure(tmp_path) -> str:
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    try:
        init_db(conn, str(project))
        conn.execute(
            "INSERT INTO tasks (id, title, owner, status, created_at, updated_at) "
            "VALUES ('t1', 't', 'claude-code', 'in_progress', ?, ?)",
            (NOW, NOW),
        )
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, "
            "max_retries, recovery_count, failed_reason, created_at) "
            "VALUES ('i1', 't1', 'claude-code', 'failed', 3, 3, ?, "
            "'bash: claude: command not found', ?)",
            (_RECOVERY_MAX, NOW),
        )
        conn.commit()
    finally:
        conn.close()
    return str(project)


def test_infra_escalation_is_recorded_in_failures(tmp_path, caplog):
    project = _project_with_exhausted_infra_failure(tmp_path)

    with caplog.at_level(logging.WARNING), patch(
        "superharness.commands.inbox_watch._agent_cli_reachable", return_value=True
    ):
        _auto_recover_exhausted_failures_sqlite(project)

    conn = get_connection(project)
    try:
        rows = conn.execute(
            "SELECT task_id, agent, pattern, error_snippet FROM failures "
            "WHERE pattern = 'auto-recovery-infra-escalation'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["task_id"] == "t1"
    assert rows[0]["agent"] == "claude-code"
    assert "command not found" in rows[0]["error_snippet"]
    assert not any("unexpected keyword argument" in r.getMessage() for r in caplog.records)
