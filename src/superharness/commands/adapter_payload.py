"""shux adapter-payload --json

Reads the current project state and emits a single stable JSON payload for
consumption by Morpheme (and any future adapter that reads superharness data).

Schema version: 1.0
Spec: docs/adapter-payload-spec.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from superharness.engine.adapter_registry import resolve_model
from superharness.engine.next_action import next_action as _next_action
from superharness.engine.normalization import normalize_blocked_by

SCHEMA_VERSION = "1.3"

# ---------------------------------------------------------------------------
# Status mapping  (extracted from Morpheme rawParser.js — superharness owns it)
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, tuple[str, str]] = {
    "todo":             ("pending",    "#6b7280"),
    "plan_proposed":    ("pending",    "#c8922a"),
    "plan_approved":    ("generating", "#4e8098"),
    "in_progress":      ("generating", "#4e8098"),
    "report_ready":     ("validating", "#8b5cf6"),
    "review_requested": ("validating", "#8b5cf6"),
    "review_passed":    ("validating", "#10b981"),
    "review_failed":    ("failed",     "#ef4444"),
    "done":             ("done",       "#10b981"),
    "failed":           ("failed",     "#ef4444"),
    "stopped":          ("failed",     "#ef4444"),
    "blocked":          ("pending",    "#6b7280"),
    "waiting_input":    ("paused",     "#f59e0b"),
    "paused":           ("paused",     "#f59e0b"),
}


def _display_status(raw_status: str) -> tuple[str, str]:
    """Return (display_status, color) for a raw task status."""
    return _STATUS_MAP.get(raw_status, ("pending", "#6b7280"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> Any:
    """Load a YAML file, returning {} on any error or missing file."""
    try:
        return yaml.safe_load(path.read_text(errors="replace")) or {}
    except Exception:
        return {}


def _coerce_date(value: Any) -> str:
    """Coerce date / datetime / string to ISO 8601 string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# Handoff loading
# ---------------------------------------------------------------------------

def _load_handoffs(sh_dir: Path) -> dict[str, list[dict]]:
    """Load all handoff YAML files, grouped by task ID, oldest first."""
    handoffs_dir = sh_dir / "handoffs"
    if not handoffs_dir.is_dir():
        return {}

    by_task: dict[str, list[dict]] = {}
    for p in sorted(handoffs_dir.glob("*.yaml")):
        raw = _load_yaml(p)
        if not isinstance(raw, dict):
            continue
        task_id = raw.get("task")
        if not task_id:
            continue
        by_task.setdefault(task_id, []).append(_normalize_handoff(raw))

    return by_task


def _normalize_handoff(raw: dict) -> dict:
    """Normalize a raw handoff dict to the adapter Handoff schema."""
    # Resolve files_touched alias
    files = raw.get("files_changed") or raw.get("files_touched")

    entry: dict = {
        "phase":    raw.get("phase", "report"),
        "from":     raw.get("from", raw.get("from_", "")),
        "to":       raw.get("to", ""),
        "date":     _coerce_date(raw.get("date") or raw.get("closed_at")),
        "status":   raw.get("status", ""),
        "verified": bool(raw.get("verified", False)),
    }

    # Optional fields — only include when present in source
    for key in ("summary", "plan", "tdd", "risks",
                "outcome", "context", "outcomes",
                "tests_passed", "test_types"):
        if key in raw:
            entry[key] = raw[key]

    if files is not None:
        entry["files_changed"] = files if isinstance(files, list) else [files]

    return entry


# ---------------------------------------------------------------------------
# Ledger parsing
# ---------------------------------------------------------------------------

# Format A:  - 2026-03-15T10:08:37Z — claude-code — modified: monitor-ui.py
# Format B:  2026-04-07T13:29:42Z session-stop: snapshot written to ...
_RE_DASH = re.compile(
    r"^-?\s*(?P<ts>\d{4}-\d{2}-\d{2}T[\d:]+Z)\s+—\s+(?P<agent>[^—]+?)\s+—\s+(?P<desc>.+)$"
)
_RE_BARE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T[\d:]+Z)\s+(?P<desc>.+)$"
)


def _classify_ledger(desc: str) -> tuple[str, str | None]:
    """Return (type, task_id_or_None)."""
    if "session-stop" in desc or "session-start" in desc:
        return "session", None
    if "modified:" in desc or "created:" in desc:
        return "file", None
    # Task lifecycle keywords — try to extract task ID
    for kw in ("verified:", "closed:", "delegated:", "report submitted",
               "plan approved", "plan proposed", "status →", "reconciled"):
        if kw in desc.lower():
            for tok in desc.split():
                tok = tok.rstrip(":,")
                if re.match(r"^[\w][\w\.\-]+$", tok) and (
                    "." in tok or tok[:4] in ("feat", "fix/", "mod.", "bug.", "chore")
                ):
                    return "task", tok
            return "task", None
    return "unknown", None


def _parse_ledger(sh_dir: Path, limit: int = 200) -> list[dict]:
    """Parse ledger.md → typed LedgerEntry list, newest first."""
    ledger_path = sh_dir / "ledger.md"
    if not ledger_path.exists():
        return []

    entries: list[dict] = []
    for line in ledger_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        m = _RE_DASH.match(line)
        if m:
            agent = m.group("agent").strip()
            desc  = m.group("desc").strip()
            kind, task_id = _classify_ledger(desc)
            entry: dict = {"timestamp": m.group("ts"), "type": kind, "description": desc}
            if agent and agent not in ("[gc]",):
                entry["agent"] = agent
            if task_id:
                entry["task"] = task_id
            entries.append(entry)
            continue

        m = _RE_BARE.match(line)
        if m:
            desc = m.group("desc").strip()
            kind, task_id = _classify_ledger(desc)
            entry = {"timestamp": m.group("ts"), "type": kind, "description": desc}
            if task_id:
                entry["task"] = task_id
            entries.append(entry)

    entries.reverse()  # newest first
    return entries[:limit]


# ---------------------------------------------------------------------------
# Failures / Decisions / Inbox
# ---------------------------------------------------------------------------

def _load_failures(sh_dir: Path) -> list[dict]:
    raw = _load_yaml(sh_dir / "failures.yaml")
    items = (raw.get("failures") or []) if isinstance(raw, dict) else []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append({
            "task":          item.get("task", ""),
            "severity":      item.get("severity", "minor"),
            "error_snippet": item.get("error_snippet", ""),
            "patterns":      item.get("patterns") or [],
            "agent":         item.get("agent", ""),
            "date":          _coerce_date(item.get("date", "")),
        })
    return result


def _load_decisions(sh_dir: Path) -> list[dict]:
    raw = _load_yaml(sh_dir / "decisions.yaml")
    items = (raw.get("decisions") or []) if isinstance(raw, dict) else []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append({
            "id":           item.get("id", ""),
            "what":         item.get("what", ""),
            "why":          item.get("why", ""),
            "alternatives": item.get("alternatives") or [],
            "status":       item.get("status", "accepted"),
            "by":           item.get("by", ""),
            "date":         _coerce_date(item.get("date", "")),
        })
    return result


def _load_inbox(sh_dir: Path) -> list[dict]:
    """Load inbox.yaml — active items only (pending / launched / running)."""
    path = sh_dir / "inbox.yaml"
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(errors="replace"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []

    active = {"pending", "launched", "running"}
    result = []
    for item in raw:
        if not isinstance(item, dict) or item.get("status") not in active:
            continue
        result.append({
            "id":          item.get("id", ""),
            "task":        item.get("task", ""),
            "status":      item.get("status", "pending"),
            "to":          item.get("to", ""),
            "priority":    item.get("priority", 2),
            "retry_count": item.get("retry_count", 0),
            "max_retries": item.get("max_retries", 3),
            "created_at":  _coerce_date(item.get("created_at", "")),
        })
    return result


# ---------------------------------------------------------------------------
# Agent pulse
# ---------------------------------------------------------------------------

def _load_agent_pulse(sh_dir: Path) -> dict | None:
    """Load .superharness/agent-pulse.yaml, returning None when absent or corrupt."""
    path = sh_dir / "agent-pulse.yaml"
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(errors="replace"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "task_id":   raw.get("task_id"),
        "agent":     raw.get("agent"),
        "status":    raw.get("status"),
        "last_seen": _coerce_date(raw.get("last_seen")),
        "message":   raw.get("message"),
        "pid":       raw.get("pid"),
    }


# ---------------------------------------------------------------------------
# Task + Edge building
# ---------------------------------------------------------------------------

def _blockers(task: dict) -> list[str]:
    """Return normalized blocked_by / dependency list for a task."""
    raw = task.get("blocked_by")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = task.get("dependency")
    return normalize_blocked_by(raw)


def _resolved_model_for(owner: Any, tier: Any) -> dict[str, str] | None:
    """Resolve {id, label} for an (owner, tier) pair, or None when no tier set.

    Empty / missing tier → None so the payload field can be omitted entirely
    rather than carrying a meaningless `{id: "", label: ""}`.
    """
    tier_str = str(tier or "").strip()
    if not tier_str:
        return None
    return resolve_model(str(owner or ""), tier_str)


def _build_classifier_block(task: dict) -> dict:
    """Build the v1.2 classifier block for a task."""
    raw = task.get("classifier")
    if isinstance(raw, dict):
        return {
            "invoked":          bool(raw.get("invoked", False)),
            "decided_by":       raw.get("decided_by"),
            "heuristic_reason": raw.get("heuristic_reason"),
            "cost_usd":         raw.get("cost_usd"),
            "duration_ms":      raw.get("duration_ms"),
        }
    return {"invoked": False, "decided_by": None, "heuristic_reason": None,
            "cost_usd": None, "duration_ms": None}


def _build_decomposer_block(task: dict) -> dict:
    """Build the v1.2 decomposer block for a task."""
    raw = task.get("decomposer")
    if isinstance(raw, dict):
        return {
            "invoked":       bool(raw.get("invoked", False)),
            "model":         raw.get("model"),
            "rationale":     raw.get("rationale"),
            "cost_usd":      raw.get("cost_usd"),
            "duration_ms":   raw.get("duration_ms"),
            "subtask_count": int(raw.get("subtask_count") or 0),
        }
    return {"invoked": False, "model": None, "rationale": None,
            "cost_usd": None, "duration_ms": None, "subtask_count": 0}


def _build_retry_block(task: dict) -> dict:
    """Build the v1.2 retry block for a task."""
    raw = task.get("retry")
    if isinstance(raw, dict):
        return {
            "count":               int(raw.get("count") or 0),
            "escalation_history":  list(raw.get("escalation_history") or []),
        }
    return {"count": 0, "escalation_history": []}


def _build_tasks(raw_tasks: list, handoffs_by_task: dict) -> list[dict]:
    result = []
    for t in raw_tasks:
        if not isinstance(t, dict):
            continue
        task_id    = t.get("id", "")
        raw_status = str(t.get("status", "todo"))
        display, color = _display_status(raw_status)
        from superharness.engine.subtask import resolve_subtask_status
        raw_subtasks = t.get("subtasks") or []
        subtasks = []
        for s in raw_subtasks:
            if not isinstance(s, dict):
                continue
            sub_owner = s.get("owner", "")
            sub_tier  = s.get("model_tier")
            sub_entry = {
                "id":                  s.get("id", ""),
                "title":               s.get("title", ""),
                "status":              resolve_subtask_status(s, raw_status),
                "model_tier":          sub_tier,
                "owner":               sub_owner,
                "estimated_tokens":    s.get("estimated_tokens"),
                "estimated_cost_usd":  s.get("estimated_cost_usd"),
                "rationale":           s.get("rationale"),
            }
            sub_resolved = _resolved_model_for(sub_owner, sub_tier)
            if sub_resolved is not None:
                sub_entry["resolved_model"] = sub_resolved
            subtasks.append(sub_entry)

        owner = t.get("owner", "")
        tier  = t.get("model_tier")
        entry: dict = {
            "id":                  task_id,
            "title":               t.get("title", ""),
            "status":              raw_status,
            "display_status":      display,
            "color":               color,
            "owner":               owner,
            "cost":                t.get("estimated_cost_usd"),
            "blocked_by":          _blockers(t),
            "effort":              t.get("effort"),
            "acceptance_criteria": t.get("acceptance_criteria") or [],
            "handoffs":            handoffs_by_task.get(task_id, []),
            "subtasks":            subtasks,
            # Backwards compat: keep `model_tier` string for clients on schema
            # 1.0 (e.g. Morpheme falling back to its rawParser path).
            "model_tier":          tier,
        }
        resolved = _resolved_model_for(owner, tier)
        if resolved is not None:
            entry["resolved_model"] = resolved
        entry["classifier"]  = _build_classifier_block(t)
        entry["decomposer"]  = _build_decomposer_block(t)
        entry["retry"]       = _build_retry_block(t)
        entry["next_action"] = _next_action(raw_status).as_dict()
        result.append(entry)
    return result


def _build_edges(tasks: list[dict]) -> list[dict]:
    edges = []
    for t in tasks:
        blockers = t["blocked_by"]
        if not blockers:
            edges.append({"source": "__contract__", "target": t["id"], "type": "contract"})
        else:
            for b in blockers:
                edges.append({"source": b, "target": t["id"], "type": "dependency"})
    return edges


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def build_payload(project_path: str) -> dict:
    """Build and return the full adapter payload for a project."""
    sh_dir        = Path(project_path).resolve() / ".superharness"
    contract_path = sh_dir / "contract.yaml"

    if not contract_path.exists():
        raise FileNotFoundError(
            f"No .superharness/contract.yaml found at {project_path!r}"
        )

    raw_contract = _load_yaml(contract_path)
    if not isinstance(raw_contract, dict):
        raise ValueError("contract.yaml is not a YAML mapping")

    raw_tasks         = raw_contract.get("tasks") or []
    handoffs_by_task  = _load_handoffs(sh_dir)
    tasks             = _build_tasks(raw_tasks, handoffs_by_task)

    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id":    raw_contract.get("id", ""),
        "goal":           raw_contract.get("goal") or "",
        "tasks":          tasks,
        "edges":          _build_edges(tasks),
        "ledger":         _parse_ledger(sh_dir),
        "failures":       _load_failures(sh_dir),
        "decisions":      _load_decisions(sh_dir),
        "inbox":          _load_inbox(sh_dir),
        "agent_pulse":    _load_agent_pulse(sh_dir),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="superharness adapter-payload",
        description=(
            "Output superharness project state as a stable JSON payload "
            "(schema v1.0) for consumption by Morpheme and other adapters."
        ),
    )
    parser.add_argument(
        "--json", dest="as_json", action="store_true", default=True,
        help="Output as JSON (default; included for explicitness)",
    )
    parser.add_argument(
        "--project", "-p", default=".",
        metavar="PATH",
        help="Path to the project root containing .superharness/ (default: .)",
    )
    opts = parser.parse_args(argv)

    try:
        payload = build_payload(opts.project)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"error: failed to build adapter payload — {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(payload, default=str))


if __name__ == "__main__":
    main()
