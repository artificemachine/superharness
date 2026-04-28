"""yaml_sync — NO-OP stub during YAML→SQLite migration (Phase 3).

Previously managed a dual-write queue for YAML file sync. All YAML writes
are now no-ops; the denque/drain/enqueue_op APIs exist only so importers
don't break during the transition. Will be deleted entirely in Phase 4.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DrainResult:
    applied: int = 0
    failed: int = 0


def enqueue_op(conn: Any, *, op_type: str, payload: dict, now: str) -> None:
    """No-op: YAML sync queue is deprecated."""
    pass


def drain(conn: Any, project_dir: str, *, max_ops: int = 500) -> DrainResult:
    """No-op: YAML sync queue is deprecated."""
    return DrainResult(applied=0, failed=0)
