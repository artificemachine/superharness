"""Subtask result aggregation — records sub-agent outcomes back to SQLite.

After sub-agents complete their subtasks, the orchestrator calls this to:
- Update each subtask's status, actual tokens, actual cost, and model used
- Compute total actual cost vs estimated
- Set parent task status to report_ready (all done) or failed (any failed)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SubtaskResult:
    """Outcome from a single sub-agent execution."""
    subtask_id: str
    status: str               # done | failed
    actual_tokens: int
    actual_cost_usd: float
    model_used: str
    output: str
    error: Optional[str] = None


@dataclass
class AggregationSummary:
    """Summary of all subtask results for a parent task."""
    task_id: str
    total_actual_cost_usd: float
    total_estimated_cost_usd: float
    all_done: bool
    any_failed: bool
    subtask_results: list[SubtaskResult] = field(default_factory=list)


class SubtaskAggregator:
    """Records subtask results into SQLite and sets parent task status."""

    def __init__(self, project_dir: str) -> None:
        self.project_dir = project_dir

    def record_results(
        self,
        task_id: str,
        results: list[SubtaskResult],
    ) -> AggregationSummary:
        """Write all subtask results to SQLite and update parent status."""
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao

        conn = get_connection(self.project_dir)
        try:
            init_db(conn)
            task_row = tasks_dao.get(conn, task_id)
            if task_row is None:
                raise ValueError(f"Task {task_id} not found in SQLite")

            extras = json.loads(task_row.extras_json or "{}")
            subtasks = extras.get("subtasks") or []
            result_map = {r.subtask_id: r for r in results}

            total_actual_cost = 0.0
            matched = 0
            any_failed = False
            any_incomplete = False

            for st in subtasks:
                st_id = str(st.get("id", ""))
                result = result_map.get(st_id)
                if result is None:
                    any_incomplete = True
                    continue

                matched += 1
                st["status"] = result.status
                st["actual_tokens"] = result.actual_tokens
                st["actual_cost_usd"] = round(result.actual_cost_usd, 6)
                st["model_used"] = result.model_used

                total_actual_cost += result.actual_cost_usd

                if result.status == "failed":
                    any_failed = True
                elif result.status != "done":
                    any_incomplete = True

            all_done = matched > 0 and not any_failed and not any_incomplete

            extras["subtasks"] = subtasks
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            changes: dict = {"extras_json": json.dumps(extras), "updated_at": now}

            if all_done and not any_failed:
                changes["status"] = "report_ready"
                changes["report_ready_at"] = now
            elif any_failed:
                changes["status"] = "failed"
                changes["failed_at"] = now

            tasks_dao.update(conn, task_id, task_row.version, changes)
            conn.commit()

            estimated_cost = task_row.extras_json and json.loads(task_row.extras_json or "{}").get("estimated_cost_usd") or 0.0
        finally:
            conn.close()

        return AggregationSummary(
            task_id=task_id,
            total_actual_cost_usd=total_actual_cost,
            total_estimated_cost_usd=estimated_cost,
            all_done=all_done,
            any_failed=any_failed,
            subtask_results=results,
        )


def aggregate_subtask_results(
    project_dir: str,
    task_id: str,
    results: list[SubtaskResult],
) -> AggregationSummary:
    """Convenience wrapper for SubtaskAggregator.record_results."""
    return SubtaskAggregator(project_dir).record_results(task_id, results)
