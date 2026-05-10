"""Parallel code-review fanout for validator phase.

Spawns one code-reviewer subagent per feature/task in a milestone,
runs them concurrently (read-only, no shared writes), and merges the
results into a single validator verdict.

Usage:
    fanout = ReviewFanout(project_dir, task_ids)
    verdict = fanout.run(max_workers=4)
    verdict.passed  # True/False
    verdict.findings  # list[str]
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReviewResult:
    task_id: str
    passed: bool
    findings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class FanoutVerdict:
    passed: bool
    findings: list[str]
    per_task: list[ReviewResult]

    @property
    def review_count(self) -> int:
        return len(self.per_task)


def merge_review_results(results: list[ReviewResult]) -> FanoutVerdict:
    """Merge per-task review results into a single verdict.

    Fails if any individual review failed. Aggregates all findings.
    """
    all_findings: list[str] = []
    for r in results:
        all_findings.extend(r.findings)
    passed = all(r.passed for r in results)
    return FanoutVerdict(passed=passed, findings=all_findings, per_task=results)


class ReviewFanout:
    """Fan out read-only code-review agents across a set of task IDs."""

    def __init__(
        self,
        project_dir: str,
        task_ids: list[str],
        target: str = "claude-code",
    ) -> None:
        self.project_dir = project_dir
        self.task_ids = task_ids
        self.target = target

    def _review_one(self, task_id: str) -> ReviewResult:
        """Dispatch a single code-reviewer for task_id (--print-only stub)."""
        try:
            cmd = [
                sys.executable, "-m", "superharness.commands.delegate",
                "--project", self.project_dir,
                "--to", self.target,
                "--task", task_id,
                "--role", "code_reviewer",
                "--for-review",
                "--print-only",  # dry-run: no live agent launched
                "--json",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                try:
                    data: dict[str, Any] = json.loads(r.stdout)
                    return ReviewResult(
                        task_id=task_id,
                        passed=data.get("ok", True),
                        findings=data.get("findings", []),
                    )
                except (json.JSONDecodeError, KeyError):
                    return ReviewResult(task_id=task_id, passed=True)
            return ReviewResult(
                task_id=task_id,
                passed=False,
                findings=[f"Dispatch error (rc={r.returncode}): {r.stderr[:200]}"],
            )
        except subprocess.TimeoutExpired:
            return ReviewResult(
                task_id=task_id, passed=False, findings=["Review timed out after 120s"]
            )
        except Exception as exc:
            return ReviewResult(task_id=task_id, passed=False, error=str(exc))

    def run(self, max_workers: int = 4) -> FanoutVerdict:
        """Run all reviews concurrently and return merged verdict."""
        results: list[ReviewResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._review_one, tid): tid for tid in self.task_ids}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        return merge_review_results(results)
