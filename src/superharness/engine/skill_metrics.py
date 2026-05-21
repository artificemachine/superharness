"""Skill metrics — tracks skill usage and provides insights.

Records which skills are used by which agents, on which tasks, and with
what outcome. Provides aggregated insights for optimization.
"""
from __future__ import annotations

from datetime import datetime, timezone

import logging
logger = logging.getLogger(__name__)


def record_skill_usage(
    project_dir: str,
    skill: str,
    agent: str,
    task_id: str,
    outcome: str = "unknown",
) -> None:
    """Record a skill usage event."""
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skill_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    outcome TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO skill_usage (skill, agent, task_id, outcome, created_at) VALUES (?, ?, ?, ?, ?)",
                (skill, agent, task_id, outcome,
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("skill_metrics.py unexpected error: %s", e, exc_info=True)
        pass  # best-effort — don't crash on metrics failure


def get_skill_insights(project_dir: str) -> list[dict]:
    """Return aggregated skill usage insights.

    Returns one row per skill with: skill, uses, success_rate, top_agent.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            conn.execute("""CREATE TABLE IF NOT EXISTS skill_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill TEXT NOT NULL, agent TEXT NOT NULL,
                task_id TEXT NOT NULL, outcome TEXT, created_at TEXT NOT NULL
            )""")
            rows = conn.execute("""
                SELECT skill,
                       COUNT(*) as uses,
                       CAST(SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS REAL) / COUNT(*) as success_rate
                FROM skill_usage GROUP BY skill ORDER BY uses DESC
            """).fetchall()
            return [
                {"skill": r[0], "uses": r[1], "success_rate": round(r[2], 2)}
                for r in rows
            ]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("skill_metrics.py unexpected error: %s", e, exc_info=True)
        return []
