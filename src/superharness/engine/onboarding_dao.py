"""DAO for onboarding_state table.

Backs `commands/onboard.py` step-completion tracking. The YAML file at
`.superharness/onboarding.yaml` is an export mirror for backwards compat
and external tooling (dual-write when not sqlite_only).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError


# Single-row table — one onboarding state per project. project_key is
# always 'default' for the single-project case. Multi-project tracking
# would extend by setting a real project identifier.
_PROJECT_KEY = "default"


@dataclass(frozen=True)
class OnboardingStateRow:
    project_key: str
    version: int
    config_version: int
    steps: dict[str, str]
    updated_at: str


def upsert(
    conn: sqlite3.Connection,
    *,
    version: int,
    config_version: int,
    steps: dict[str, str],
    updated_at: str,
) -> OnboardingStateRow:
    steps_json = json.dumps(steps)
    try:
        conn.execute(
            """
            INSERT INTO onboarding_state (
                project_key, version, config_version, steps_json, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_key) DO UPDATE SET
                version=excluded.version,
                config_version=excluded.config_version,
                steps_json=excluded.steps_json,
                updated_at=excluded.updated_at
            """,
            (_PROJECT_KEY, version, config_version, steps_json, updated_at),
        )
        row = conn.execute(
            "SELECT * FROM onboarding_state WHERE project_key = ?",
            (_PROJECT_KEY,),
        ).fetchone()
        if not row:
            raise StateError("onboarding_state upsert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"onboarding_state upsert failed: {e}") from e


def get(conn: sqlite3.Connection) -> OnboardingStateRow | None:
    try:
        row = conn.execute(
            "SELECT * FROM onboarding_state WHERE project_key = ?",
            (_PROJECT_KEY,),
        ).fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"onboarding_state get failed: {e}") from e


def _to_row(row: sqlite3.Row) -> OnboardingStateRow:
    try:
        steps = json.loads(row["steps_json"])
        if not isinstance(steps, dict):
            steps = {}
    except (ValueError, TypeError):
        steps = {}
    return OnboardingStateRow(
        project_key=row["project_key"],
        version=int(row["version"]),
        config_version=int(row["config_version"]),
        steps=steps,
        updated_at=row["updated_at"],
    )
