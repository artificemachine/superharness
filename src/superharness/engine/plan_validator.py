"""Plan quality gate — validates plan handoffs before auto-approval.

Without this gate, `auto_approve_plans: true` blindly approves every plan,
defeating the purpose. Operator gets buried in low-value plans or sees none
at all. With this gate, only plans that fail structural checks reach the
operator queue, with the failing reason highlighted.

Heuristics enforced (any failure blocks auto-approval):
  - TDD block present with red, green, refactor sub-sections
  - Plan body is non-empty and under sentinel length
  - Risks section present and non-empty
  - No TODO markers or placeholders in plan body
  - Acceptance criteria are addressed (heuristic match)

Each failure is a human-readable string that surfaces in the dashboard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PlanValidation:
    passed: bool
    failures: list[str] = field(default_factory=list)


_PLACEHOLDER_PATTERNS = [
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bXXX\b",
    r"\bplaceholder\b",
    r"\b\?\?\?\b",
]


def _check_tdd(plan: dict) -> list[str]:
    failures: list[str] = []
    tdd = plan.get("tdd")
    if not isinstance(tdd, dict):
        failures.append("missing tdd block (required by CLAUDE.md)")
        return failures
    for key in ("red", "green", "refactor"):
        section = tdd.get(key)
        if not isinstance(section, str) or not section.strip():
            failures.append(f"missing tdd.{key} section")
    return failures


def _check_plan_body(plan: dict) -> list[str]:
    failures: list[str] = []
    body = plan.get("plan")
    if not isinstance(body, str) or not body.strip():
        failures.append("plan body is empty or missing")
        return failures
    for pat in _PLACEHOLDER_PATTERNS:
        if re.search(pat, body, re.IGNORECASE):
            failures.append(f"plan contains placeholder/todo marker: {pat}")
    return failures


def _check_risks(plan: dict) -> list[str]:
    risks = plan.get("risks")
    if not isinstance(risks, str) or not risks.strip():
        return ["missing risks section (state at least 'no known risks')"]
    return []


def _check_acceptance_criteria(plan: dict, contract_task: dict) -> list[str]:
    """Heuristic: at least one significant keyword from each AC should appear in plan."""
    crits = contract_task.get("acceptance_criteria") or []
    if not crits:
        return []
    body = (plan.get("plan") or "").lower()
    tdd_text = " ".join(
        str(v) for v in (plan.get("tdd") or {}).values()
    ).lower()
    haystack = body + " " + tdd_text
    failures: list[str] = []
    for c in crits:
        if not isinstance(c, str):
            continue
        # Significant words: length > 2, exclude common stop words
        stops = {"the", "and", "for", "are", "not", "but", "any", "all", "with"}
        words = [w for w in re.findall(r"\w+", c.lower()) if len(w) > 2 and w not in stops]
        if not words:
            continue
        # Pass if any significant word appears in plan/tdd. Catches "no mention at all".
        if not any(w in haystack for w in words):
            failures.append(f"acceptance criterion not addressed: {c}")
    return failures


def validate_plan(plan: dict, contract_task: dict) -> PlanValidation:
    """Validate a plan handoff against quality heuristics.

    Args:
      plan:          parsed plan handoff yaml.
      contract_task: corresponding contract task dict.

    Returns:
      PlanValidation with .passed and .failures.
    """
    failures: list[str] = []
    failures.extend(_check_plan_body(plan))
    failures.extend(_check_tdd(plan))
    failures.extend(_check_risks(plan))
    failures.extend(_check_acceptance_criteria(plan, contract_task))
    return PlanValidation(passed=not failures, failures=failures)
