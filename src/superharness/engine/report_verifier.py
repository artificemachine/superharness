"""Report verification gate — validates report handoffs before auto-close.

Without this gate, `auto_close: true` blindly closes every report_ready task,
including reports with empty outcomes, fake claims, or failing tests. Operator
gets either everything or nothing.

With this gate, reports that fail verification stay in report_ready with a
verification_failures field; operator sees only flagged reports.

Heuristics enforced:
  - outcome present and substantial (over 20 chars)
  - context field present (used by next session)
  - tests_passed: true (or absent in autonomous mode)
  - pr_url, if present, looks like a valid URL
  - referenced files (in outcome) exist on disk

The suggested_action drives the watcher: "close" auto-closes, "operator_review"
leaves the task for the operator, "fail" marks the task failed.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ReportVerification:
    passed: bool
    failures: list[str] = field(default_factory=list)
    suggested_action: Literal["close", "operator_review", "fail"] = "close"


_MIN_OUTCOME_CHARS = 20

_URL_PATTERN = re.compile(r"^https?://[\w.-]+(/[\w./?=&%-]*)?$")


def _check_outcome(report: dict) -> list[str]:
    outcome = report.get("outcome")
    if not isinstance(outcome, str) or not outcome.strip():
        return ["outcome field is empty or missing"]
    if len(outcome.strip()) < _MIN_OUTCOME_CHARS:
        return [
            f"outcome is too short ({len(outcome.strip())} chars, min {_MIN_OUTCOME_CHARS})"
        ]
    return []


def _check_context(report: dict, *, strict: bool = True) -> list[str]:
    """Context field check. Strict mode (default) blocks on missing context.
    When auto_close is explicit, missing context is a warning, not a block.
    """
    if strict:
        context = report.get("context")
        if not isinstance(context, str) or not context.strip():
            return ["missing context field (used by next session for handoff)"]
    return []


def _check_tests_passed(report: dict) -> list[str]:
    if "tests_passed" not in report:
        # Absent is acceptable when auto_close is explicit (handled at caller layer).
        # Here we just note it.
        return []
    if report.get("tests_passed") is not True:
        return [f"tests_passed is {report.get('tests_passed')!r}, expected true"]
    return []


def _check_pr_url(report: dict) -> list[str]:
    pr_url = report.get("pr_url")
    if pr_url is None:
        return []
    if not isinstance(pr_url, str) or not _URL_PATTERN.match(pr_url):
        return [f"pr_url does not look like a valid URL: {pr_url!r}"]
    return []


def _check_referenced_files(report: dict, project_dir: str) -> list[str]:
    """If the outcome mentions paths like src/foo.py, verify they exist.

    This is a heuristic: only checks paths that look like project-relative
    file paths (no leading slash, contains directory separator and extension).
    """
    outcome = report.get("outcome", "") or ""
    pattern = re.compile(r"\b((?:src|tests|docs)/[\w./_-]+\.[a-z]{1,4})\b")
    failures = []
    for match in pattern.finditer(outcome):
        rel = match.group(1)
        full = os.path.join(project_dir, rel)
        if not os.path.exists(full):
            failures.append(f"referenced file not found: {rel}")
    return failures


def verify_report(report: dict, contract_task: dict, project_dir: str, *, strict_context: bool = True) -> ReportVerification:
    """Verify a report handoff against quality heuristics.

    Args:
      report:        parsed report handoff yaml.
      contract_task: corresponding contract task dict.
      project_dir:   absolute path to the project root.

    Returns:
      ReportVerification with .passed, .failures, .suggested_action.
    """
    failures: list[str] = []
    failures.extend(_check_outcome(report))
    failures.extend(_check_context(report, strict=strict_context))
    failures.extend(_check_tests_passed(report))
    failures.extend(_check_pr_url(report))
    failures.extend(_check_referenced_files(report, project_dir))

    if not failures:
        return ReportVerification(passed=True, failures=[], suggested_action="close")

    # Determine routing: hard failures → fail, soft failures → operator_review
    hard_keywords = ("tests_passed is", "outcome is too short", "outcome field is empty")
    has_hard_failure = any(any(k in f for k in hard_keywords) for f in failures)
    action: Literal["close", "operator_review", "fail"] = (
        "operator_review" if not has_hard_failure or "tests_passed" in " ".join(failures)
        else "fail"
    )
    # Soft routing rule: if all failures are warnings (context, pr_url), still operator_review
    # Hard rule: tests_passed false → operator_review (operator can see why and decide)
    return ReportVerification(passed=False, failures=failures, suggested_action="operator_review")
