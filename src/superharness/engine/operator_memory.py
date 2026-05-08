"""Operator memory — persistent failure pattern memory for the watcher.

The watcher operator sees the same failure patterns across many tasks.
This module gives it a memory layer so it can:
  - Recognize known failure signatures and skip re-diagnosis
  - Learn which fixes work for which patterns (confidence tracking)
  - Prune stale / low-confidence entries automatically

Schema: a single `operator_memory` table added to the existing
`.superharness/state.sqlite3` database.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS operator_memory (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_signature  TEXT    NOT NULL UNIQUE,
    resolution         TEXT    NOT NULL,
    confidence         REAL    NOT NULL DEFAULT 0.5,
    hit_count          INTEGER NOT NULL DEFAULT 0,
    miss_count         INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT    NOT NULL,
    last_used_at       TEXT    NOT NULL
)
"""


class OperatorMemory:
    """SQLite-backed DAO for operator failure pattern memory."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def ensure_table(self) -> None:
        """Create the operator_memory table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def find_pattern(self, signature: str) -> dict[str, Any] | None:
        """Return the memory entry for a given failure signature, or None.

        The lookup is exact (case-sensitive) on pattern_signature.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM operator_memory WHERE pattern_signature = ?",
            (signature,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def record_new(self, signature: str, resolution: str) -> dict[str, Any]:
        """Create a new pattern memory entry.

        Raises ValueError if a pattern with this signature already exists.
        """
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id FROM operator_memory WHERE pattern_signature = ?",
            (signature,),
        ).fetchone()
        if existing is not None:
            raise ValueError(
                f"Pattern signature '{signature}' already exists (id={existing[0]}). "
                f"Use record_match to update it or forget to remove it first."
            )

        now = _now_utc()
        cursor = conn.execute(
            """INSERT INTO operator_memory
               (pattern_signature, resolution, confidence, hit_count, miss_count,
                created_at, last_used_at)
               VALUES (?, ?, 0.5, 0, 0, ?, ?)""",
            (signature, resolution, now, now),
        )
        conn.commit()
        return self.find_pattern(signature)  # type: ignore[return-value]

    def record_match(self, signature: str, *, success: bool) -> dict[str, Any]:
        """Record a hit or miss for a known pattern and update confidence.

        Raises ValueError if the signature is not found.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, hit_count, miss_count FROM operator_memory WHERE pattern_signature = ?",
            (signature,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown signature: '{signature}'")

        hit_count = row["hit_count"]
        miss_count = row["miss_count"]

        if success:
            hit_count += 1
        else:
            miss_count += 1

        total = hit_count + miss_count
        confidence = hit_count / total if total > 0 else 0.5

        now = _now_utc()
        conn.execute(
            """UPDATE operator_memory
               SET hit_count = ?, miss_count = ?, confidence = ?, last_used_at = ?
               WHERE pattern_signature = ?""",
            (hit_count, miss_count, confidence, now, signature),
        )
        conn.commit()
        return self.find_pattern(signature)  # type: ignore[return-value]

    def forget(self, signature: str) -> None:
        """Remove a pattern from memory. No-op if not found."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM operator_memory WHERE pattern_signature = ?",
            (signature,),
        )
        conn.commit()

    def list_all(self) -> list[dict[str, Any]]:
        """Return all memory entries, ordered by confidence descending."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM operator_memory ORDER BY confidence DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def prune_stale(self, *, threshold: float = 0.3) -> int:
        """Remove entries with confidence below the threshold.

        Returns the number of entries removed.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM operator_memory WHERE confidence < ?",
            (threshold,),
        )
        conn.commit()
        return cursor.rowcount
