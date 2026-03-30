"""Subtask result aggregation — records sub-agent outcomes back to contract.yaml.

After sub-agents complete their subtasks, the orchestrator calls this to:
- Update each subtask's status, actual tokens, actual cost, and model used
- Compute total actual cost vs estimated
- Set parent task status to report_ready (all done) or failed (any failed)
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
    """Records subtask results into contract.yaml and sets parent task status."""

    def __init__(self, contract_file: str) -> None:
        self.contract_file = contract_file

    def record_results(
        self,
        task_id: str,
        results: list[SubtaskResult],
    ) -> AggregationSummary:
        """Write all subtask results to contract.yaml and update parent status.

        Returns an AggregationSummary with cost totals and completion state.
        """
        import yaml

        with open(self.contract_file) as f:
            doc = yaml.safe_load(f) or {}

        tasks = doc.get("tasks") or []
        task = next(
            (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id),
            None,
        )
        if task is None:
            raise ValueError(f"Task {task_id} not found in contract")

        subtasks = task.get("subtasks") or []
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

        # Update parent task
        task["actual_cost_usd"] = round(total_actual_cost, 6)
        if all_done and not any_failed:
            task["status"] = "report_ready"
        elif any_failed:
            task["status"] = "failed"

        with open(self.contract_file, "w") as f:
            yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)

        return AggregationSummary(
            task_id=task_id,
            total_actual_cost_usd=total_actual_cost,
            total_estimated_cost_usd=task.get("estimated_cost_usd") or 0.0,
            all_done=all_done,
            any_failed=any_failed,
            subtask_results=results,
        )


def aggregate_subtask_results(
    contract_file: str,
    task_id: str,
    results: list[SubtaskResult],
) -> AggregationSummary:
    """Convenience wrapper for SubtaskAggregator.record_results."""
    return SubtaskAggregator(contract_file).record_results(task_id, results)
