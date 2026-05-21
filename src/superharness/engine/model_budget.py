"""Budget guard — warn or block dispatch when daily/weekly spend exceeds profile limits.

Budget config is stored in .superharness/profile.yaml under the 'budget' key:
  budget:
    daily_limit: 5.00    # USD — warn at 80%, block at 100% (strict mode)
    weekly_limit: 35.00  # USD — optional
    strict: false        # true = hard block; false = warn only

call check_budget(project_dir) before dispatch to get a CheckResult.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import logging
logger = logging.getLogger(__name__)


class BudgetStatus(str, Enum):
    OK = "ok"
    WARN = "warn"      # >= 80% of limit
    BLOCK = "block"    # >= 100% + strict mode


@dataclass
class CheckResult:
    status: BudgetStatus
    used_today: float
    daily_limit: float | None
    pct_used: float        # 0.0–1.0+
    message: str = ""


_WARN_THRESHOLD = 0.80


def _load_budget_config(project_dir: str) -> dict:
    profile = Path(project_dir) / ".superharness" / "profile.yaml"
    if not profile.exists():
        return {}
    try:
        import yaml
        doc = yaml.safe_load(profile.read_text()) or {}
        return doc.get("budget") or {}
    except Exception as e:
        logger.warning("model_budget.py unexpected error: %s", e, exc_info=True)
        return {}


def _today_spend(project_dir: str) -> float:
    """Sum cost_usd from benchmark.jsonl for records dated today (UTC)."""
    from superharness.engine.benchmark import load_records

    today = datetime.date.today().isoformat()  # "YYYY-MM-DD"
    records = load_records(project_dir)
    total = 0.0
    for r in records:
        ts = r.get("timestamp", "")
        if ts.startswith(today):
            total += float(r.get("cost_usd", 0.0))
    return total


def check_budget(project_dir: str) -> CheckResult:
    """Check today's spend against profile budget limits.

    Returns CheckResult with status OK / WARN / BLOCK.
    If no budget config exists, always returns OK.
    """
    cfg = _load_budget_config(project_dir)
    daily_limit = cfg.get("daily_limit")
    strict = bool(cfg.get("strict", False))

    used = _today_spend(project_dir)

    if daily_limit is None:
        return CheckResult(
            status=BudgetStatus.OK,
            used_today=used,
            daily_limit=None,
            pct_used=0.0,
            message="No budget configured.",
        )

    daily_limit = float(daily_limit)
    pct = used / daily_limit if daily_limit > 0 else 0.0

    if pct >= 1.0:
        if strict:
            return CheckResult(
                status=BudgetStatus.BLOCK,
                used_today=used,
                daily_limit=daily_limit,
                pct_used=pct,
                message=(
                    f"BLOCKED: Daily budget exceeded (${used:.2f} / ${daily_limit:.2f}). "
                    f"Override with --force, or switch to a cheaper model."
                ),
            )
        else:
            return CheckResult(
                status=BudgetStatus.WARN,
                used_today=used,
                daily_limit=daily_limit,
                pct_used=pct,
                message=(
                    f"WARN: Daily budget exceeded (${used:.2f} / ${daily_limit:.2f}). "
                    f"Proceeding (strict mode off)."
                ),
            )

    if pct >= _WARN_THRESHOLD:
        return CheckResult(
            status=BudgetStatus.WARN,
            used_today=used,
            daily_limit=daily_limit,
            pct_used=pct,
            message=(
                f"WARN: Daily budget {pct*100:.0f}% used (${used:.2f} / ${daily_limit:.2f})."
            ),
        )

    return CheckResult(
        status=BudgetStatus.OK,
        used_today=used,
        daily_limit=daily_limit,
        pct_used=pct,
        message=f"Budget OK: ${used:.2f} / ${daily_limit:.2f} ({pct*100:.0f}% used).",
    )


def _today_spend_by_agent(project_dir: str) -> dict[str, float]:
    """Return per-agent spend for today from benchmark.jsonl."""
    from superharness.engine.benchmark import load_records
    today = datetime.date.today().isoformat()
    records = load_records(project_dir)
    spend: dict[str, float] = {}
    for r in records:
        ts = r.get("timestamp", "")
        if not ts.startswith(today):
            continue
        agent = r.get("agent", r.get("owner", "unknown"))
        spend[agent] = spend.get(agent, 0.0) + float(r.get("cost_usd", 0.0))
    return spend


def check_agent_budget(project_dir: str, agent: str) -> CheckResult:
    """Check per-agent spend against budget limits.

    Uses per_agent_limit from profile.yaml budget config.
    Falls back to project-wide limit if no per-agent limit is set.
    """
    cfg = _load_budget_config(project_dir)
    per_agent_limit = cfg.get("per_agent_limit", cfg.get("daily_limit"))
    strict = bool(cfg.get("strict", False))

    used = _today_spend_by_agent(project_dir).get(agent, 0.0)

    if per_agent_limit is None:
        return CheckResult(status=BudgetStatus.OK, used_today=used, daily_limit=None, pct_used=0.0,
                          message=f"No per-agent budget for {agent}.")

    limit = float(per_agent_limit)
    pct = used / limit if limit > 0 else 0.0

    if pct >= 1.0:
        if strict:
            return CheckResult(status=BudgetStatus.BLOCK, used_today=used, daily_limit=limit, pct_used=pct,
                              message=f"BLOCKED: {agent} budget exceeded (${used:.2f} / ${limit:.2f}).")
        return CheckResult(status=BudgetStatus.WARN, used_today=used, daily_limit=limit, pct_used=pct,
                          message=f"WARN: {agent} budget exceeded (${used:.2f} / ${limit:.2f}).")
    if pct >= _WARN_THRESHOLD:
        return CheckResult(status=BudgetStatus.WARN, used_today=used, daily_limit=limit, pct_used=pct,
                          message=f"WARN: {agent} budget {pct*100:.0f}% (${used:.2f} / ${limit:.2f}).")
    return CheckResult(status=BudgetStatus.OK, used_today=used, daily_limit=limit, pct_used=pct,
                      message=f"{agent} OK: ${used:.2f} / ${limit:.2f} ({pct*100:.0f}%).")
