"""Dynamic model discovery cache.

Iteration 1 of PLAN-dynamic-model-selection.md.

Provides:
- ``DiscoveredModel`` — one discovered model entry for a host/auth mode.
- ``ModelDiscoveryCache`` — SQLite-backed per-project cache keyed by
  ``(project_id, agent, auth_mode)`` so a discovered model survives across
  processes and is invalidated when the agent's auth mode flips.

Table ``model_discovery`` is created by migration v37 in ``engine/db.py``.
This module is storage-only in iteration 1 — no callers yet. The probe and
native discovery implementations arrive in iterations 2-3 and consume this
cache.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_discovery (
    project_id  TEXT NOT NULL,
    agent       TEXT NOT NULL,
    model_id    TEXT NOT NULL,
    label       TEXT,
    source      TEXT NOT NULL DEFAULT 'probe',
    auth_mode   TEXT NOT NULL DEFAULT 'unknown',
    probed_at   TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL DEFAULT 86400,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (project_id, agent, auth_mode)
)
"""

_INSERT = """
INSERT OR REPLACE INTO model_discovery
    (project_id, agent, model_id, label, source, auth_mode, probed_at, ttl_seconds, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT = """
SELECT model_id, label, source, auth_mode, probed_at, ttl_seconds
FROM model_discovery
WHERE project_id = ? AND agent = ? AND auth_mode = ?
"""

_DELETE = """
DELETE FROM model_discovery
WHERE project_id = ? AND agent = ?
"""

_DELETE_ALL = "DELETE FROM model_discovery"

# Row factory for reads: map column name -> value.
_ROW_FACTORY = sqlite3.Row


@dataclass(frozen=True)
class DiscoveredModel:
    """One model discovered on a host for a specific auth mode.

    ``source`` is ``"native"`` when the CLI has a real list-models command
    (e.g. ``opencode models``) and ``"probe"`` when it was found by
    dispatching a one-token probe and observing success/failure.
    """

    id: str
    label: str
    source: str  # "native" | "probe"
    auth_mode: str  # "unknown" | "apikey" | "chatgpt" | ...
    probed_at: datetime


class ModelDiscoveryCache:
    """SQLite-backed cache for discovered models, keyed per project+agent+auth.

    Storage-only in iteration 1. ``set``/``get``/``invalidate``/``clear`` are
    the public surface; every method is exercised by the iteration-1 test
    pyramid (TDD parity).
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        # The resolved state path may live under a not-yet-existing XDG dir
        # (e.g. ~/.local/state/superharness/<hash>/); create parents so the
        # connect below doesn't fail with "unable to open database file".
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        # Each call opens its own connection so the cache survives across
        # processes (SQLite handles concurrent access with busy timeout).
        self._conn = sqlite3.connect(self._db_path, timeout=5)
        self._conn.row_factory = _ROW_FACTORY
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(
        self,
        project_id: str,
        agent: str,
        model: DiscoveredModel,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        """Persist a discovered model for (project, agent, auth_mode).

        Upsert — a newer probe for the same key replaces the older entry.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            _INSERT,
            (
                project_id,
                agent,
                model.id,
                model.label,
                model.source,
                model.auth_mode,
                model.probed_at.isoformat() if isinstance(model.probed_at, datetime) else str(model.probed_at),
                ttl_seconds,
                now,
            ),
        )
        self._conn.commit()

    def get(
        self, project_id: str, agent: str, auth_mode: str
    ) -> DiscoveredModel | None:
        """Return the cached model for (project, agent, auth_mode), or None.

        A row past its TTL reads as a miss (expired entries are lazily
        deleted on read).
        """
        row = self._conn.execute(_SELECT, (project_id, agent, auth_mode)).fetchone()
        if row is None:
            return None

        probed_at = _parse_iso(row["probed_at"])
        ttl = int(row["ttl_seconds"] or _DEFAULT_TTL_SECONDS)
        if probed_at is None or _is_expired(probed_at, ttl):
            self._conn.execute(
                "DELETE FROM model_discovery WHERE project_id = ? AND agent = ? AND auth_mode = ?",
                (project_id, agent, auth_mode),
            )
            self._conn.commit()
            return None

        return DiscoveredModel(
            id=row["model_id"],
            label=row["label"] or row["model_id"],
            source=row["source"] or "probe",
            auth_mode=row["auth_mode"] or "unknown",
            probed_at=probed_at,
        )

    def invalidate(self, project_id: str, agent: str) -> None:
        """Drop every cached entry for (project, agent) across auth modes."""
        self._conn.execute(_DELETE, (project_id, agent))
        self._conn.commit()

    def clear(self) -> None:
        """Drop every entry in the cache."""
        self._conn.execute(_DELETE_ALL)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating 'Z' suffixes and bad input."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _is_expired(probed_at: datetime, ttl_seconds: int) -> bool:
    """True when the probe timestamp is older than the TTL."""
    return datetime.now(timezone.utc) - probed_at > timedelta(seconds=ttl_seconds)
