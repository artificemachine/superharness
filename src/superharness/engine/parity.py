"""parity — NO-OP stub, post YAML→SQLite migration.

Previously checked and healed drift between YAML files and SQLite state.
With the migration to SQLite-only, parity checking is no longer needed.
Zero production importers remain (grep `superharness.engine.parity` under
src/); only tests/unit/db/test_parity.py and test_sqlite_only_cutover.py
still call it, asserting the no-op contract holds. No scheduled deletion —
removing this module means retiring or rewriting those tests first, which
is a separate decision, not a docs fix.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TableDrift:
    table: str = ""
    only_in_db: int = 0
    only_in_yaml: int = 0
    mismatched: int = 0


@dataclass(frozen=True)
class ParityReport:
    checked_at: str = ""
    healthy: bool = True
    drifts: list[TableDrift] = None  # type: ignore
    yaml_sync_lag: int = 0
    foreign_key_violations: int = 0

    def __post_init__(self):
        if self.drifts is None:
            object.__setattr__(self, 'drifts', [])


def check_parity(conn: Any, project_dir: str) -> ParityReport:
    """No-op: parity checking is deprecated. Always returns healthy."""
    return ParityReport(healthy=True, drifts=[], yaml_sync_lag=0, foreign_key_violations=0)


def heal_parity(conn: Any, project_dir: str, report: ParityReport) -> int:
    """No-op: parity healing is deprecated. Always returns 0."""
    return 0
