"""shux handoff write — author a plan or report handoff YAML from the CLI.

This command is the CLI-facing surface for authoring plan and report handoffs,
the same artifacts agents write during the task lifecycle. It exists so that
read-only adapter UIs (e.g. Morpheme) can advance tasks through the lifecycle
without bypassing the superharness data-model boundary.

Usage:

    shux handoff write --task ID --phase plan --from AGENT --to TARGET \\
        [--plan "<text>" | --plan @file] \\
        [--tdd-red "<text>" | --tdd-red @file] \\
        [--tdd-green ...] [--tdd-refactor ...] \\
        [--risks "<text>"] [--status STATE] [--date ISO] \\
        [--json]

    shux handoff write --task ID --phase report --from AGENT --to TARGET \\
        [--outcome "<text>" | --outcome @file] \\
        [--context "<text>" | --context @file] \\
        [--tests-passed/--no-tests-passed] \\
        [--json]

Arguments prefixed with "@" are read from a file. The command refuses to
write if the referenced task id is not in contract.yaml, or if required
fields for the chosen phase are missing.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging
logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


VALID_PHASES = {"plan", "report"}
VALID_FROM = {"claude-code", "codex-cli", "gemini-cli", "opencode", "owner"}
VALID_TO = {"claude-code", "codex-cli", "gemini-cli", "opencode", "owner"}
_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


_JSON_MODE = False
_JSON_CTX: dict = {}


def _abort(msg: str, code: int = 1) -> None:
    if _JSON_MODE:
        from superharness.utils.json_output import emit_error
        emit_error(msg, exit_code=code, **_JSON_CTX)
    print(msg, file=sys.stderr)
    sys.exit(code)


def _read_value(value: str | None) -> str:
    """Resolve a value string: if starts with '@', read the file contents."""
    if value is None:
        return ""
    if value.startswith("@"):
        path = Path(value[1:]).expanduser()
        if not path.is_file():
            _abort(f"file not found: {path}", 2)
        return path.read_text()
    return value


def _validate_id(name: str, value: str) -> None:
    if not value:
        _abort(f"{name} must not be empty", 2)
    if not _ID_RE.match(value):
        _abort(f"{name} must match ^[A-Za-z0-9._-]+$", 2)


_TDD_ENFORCED_WORKFLOWS = {"implementation", "review"}


def _load_contract_doc(contract_file: Path) -> dict:
    """Load contract doc from state_reader (SQLite exclusively)."""
    try:
        from superharness.engine import state_reader as _sr
        project_dir = str(contract_file.parent.parent)
        return _sr.get_contract_doc(project_dir)
    except Exception as e:
        logger.warning("handoff_write.py unexpected error: %s", e, exc_info=True)
        return {}


def _load_task_policy(contract_file: Path, task_id: str) -> tuple[bool, str]:
    """Return (require_tdd, workflow) for the given task. Defaults: (True, 'quick')."""
    doc = _load_contract_doc(contract_file)
    if not doc:
        return (True, "quick")
    task = None
    try:
        from superharness.engine.subtask import find_task_or_subtask
        task, _ = find_task_or_subtask(doc, task_id)
    except Exception as e:
        logger.warning("handoff_write.py unexpected error: %s", e, exc_info=True)
        for t in (doc.get("tasks") or []):
            if isinstance(t, dict) and str(t.get("id", "")) == task_id:
                task = t
                break
    if task is None:
        return (True, "quick")
    require_tdd = task.get("require_tdd")
    if require_tdd is None:
        require_tdd = True
    else:
        require_tdd = bool(require_tdd)
    workflow = str(task.get("workflow") or "quick")
    return (require_tdd, workflow)


def _task_exists(contract_file: Path, task_id: str) -> bool:
    """Return True if task_id resolves in contract (top-level or subtask)."""
    doc = _load_contract_doc(contract_file)
    if not doc:
        return False
    try:
        from superharness.engine.subtask import find_task_or_subtask
        task, _ = find_task_or_subtask(doc, task_id)
        return task is not None
    except Exception as e:
        logger.warning("handoff_write.py unexpected error: %s", e, exc_info=True)
        for t in (doc.get("tasks") or []):
            if isinstance(t, dict) and str(t.get("id", "")) == task_id:
                return True
        return False


def _build_plan_handoff(
    args: argparse.Namespace,
    require_tdd: bool = True,
    workflow: str = "quick",
) -> dict[str, Any]:
    plan_text = _read_value(args.plan).strip()
    tdd_red = _read_value(args.tdd_red).strip()
    tdd_green = _read_value(args.tdd_green).strip()
    tdd_refactor = _read_value(args.tdd_refactor).strip()

    if not plan_text:
        _abort("plan phase requires --plan", 2)

    tdd_enforced = require_tdd and workflow in _TDD_ENFORCED_WORKFLOWS
    if tdd_enforced:
        missing = [f for f, v in [("--tdd-red", tdd_red), ("--tdd-green", tdd_green), ("--tdd-refactor", tdd_refactor)] if not v]
        if missing:
            _abort(
                f"error: {', '.join(missing)} required "
                f"(task.require_tdd=true, workflow={workflow})",
                2,
            )

    payload: dict[str, Any] = {
        "task": args.task_id,
        "phase": "plan",
        "status": args.status or "plan_proposed",
        "from": args.from_agent,
        "to": args.to_agent,
        "date": args.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": plan_text,
    }
    tdd: dict[str, str] = {}
    if tdd_red:
        tdd["red"] = tdd_red
    if tdd_green:
        tdd["green"] = tdd_green
    if tdd_refactor:
        tdd["refactor"] = tdd_refactor
    payload["tdd"] = tdd
    risks = _read_value(args.risks).strip()
    if risks:
        payload["risks"] = risks
    return payload


def _build_report_handoff(args: argparse.Namespace) -> dict[str, Any]:
    outcome = _read_value(args.outcome).strip()
    context = _read_value(args.context).strip()

    if not outcome:
        _abort("report phase requires --outcome", 2)

    payload: dict[str, Any] = {
        "task": args.task_id,
        "phase": "report",
        "status": args.status or "report_ready",
        "from": args.from_agent,
        "to": args.to_agent,
        "date": args.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome,
    }
    if context:
        payload["context"] = context
    else:
        payload["context"] = f"[auto-generated] report from {args.from_agent} for task {args.task_id}"
    if args.tests_passed is not None:
        payload["tests_passed"] = bool(args.tests_passed)
    return payload


def _handoff_filename(task_id: str, phase: str, from_agent: str, date_iso: str) -> str:
    """Build a deterministic, operator-readable handoff filename."""
    date_slug = date_iso[:10]  # YYYY-MM-DD
    return f"{task_id}-{phase}-{date_slug}-{from_agent}.yaml"


def write_handoff(
    project_dir: Path,
    args: argparse.Namespace,
) -> tuple[int, dict[str, Any]]:
    """Build payload, validate, and write to .superharness/handoffs/.

    Returns (exit_code, payload_written).
    """
    if yaml is None:
        _abort("PyYAML not installed — required for handoff write", 1)

    contract_file = project_dir / ".superharness" / "contract.yaml"
    if not contract_file.is_file():
        _abort(f"missing contract file: {contract_file}", 1)

    if not _task_exists(contract_file, args.task_id):
        _abort(f"task '{args.task_id}' not found in contract", 1)

    require_tdd, workflow = _load_task_policy(contract_file, args.task_id)

    if args.phase == "plan":
        payload = _build_plan_handoff(args, require_tdd=require_tdd, workflow=workflow)
    elif args.phase == "report":
        payload = _build_report_handoff(args)
    else:
        _abort(f"invalid --phase: {args.phase} (expected plan or report)", 2)

    handoffs_dir = project_dir / ".superharness" / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)

    fname = args.out or _handoff_filename(
        args.task_id, args.phase, args.from_agent, str(payload["date"]),
    )
    target = handoffs_dir / fname
    if target.exists() and not args.force:
        _abort(f"handoff already exists: {target} (use --force to overwrite)", 1)

    try:
        target.write_text(yaml.safe_dump(
            payload, default_flow_style=False, allow_unicode=True, sort_keys=False,
        ))
    except OSError as e:
        _abort(f"failed to write handoff: {e}", 1)

    return 0, {"path": str(target), **payload}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="handoff write",
        description="Author a plan or report handoff YAML in .superharness/handoffs/.",
    )
    p.add_argument("--project", "-p", default=None, help="Project directory (default: cwd)")
    p.add_argument("--task", required=True, dest="task_id", help="Task ID from contract.yaml")
    p.add_argument(
        "--phase", required=True, choices=sorted(VALID_PHASES),
        help="Handoff phase: plan (plan_proposed) or report (report_ready)",
    )
    p.add_argument(
        "--from", required=True, dest="from_agent", choices=sorted(VALID_FROM),
        help="Authoring agent or 'owner'",
    )
    p.add_argument(
        "--to", required=True, dest="to_agent", choices=sorted(VALID_TO),
        help="Target recipient",
    )
    p.add_argument("--status", default=None,
                   help="Lifecycle status (default: plan_proposed for plan, report_ready for report)")
    p.add_argument("--date", default=None, help="ISO timestamp (default: now UTC)")

    # Plan-specific
    p.add_argument("--plan", default=None, help="Plan text or @path/to/file.md")
    p.add_argument("--tdd-red", dest="tdd_red", default=None, help="TDD red phase or @file")
    p.add_argument("--tdd-green", dest="tdd_green", default=None, help="TDD green phase or @file")
    p.add_argument("--tdd-refactor", dest="tdd_refactor", default=None, help="TDD refactor phase or @file")
    p.add_argument("--risks", default=None, help="Risks/open questions or @file")

    # Report-specific
    p.add_argument("--outcome", default=None, help="Outcome summary or @file")
    p.add_argument("--context", default=None, help="Context for next session or @file")
    p.add_argument(
        "--tests-passed", dest="tests_passed",
        action=argparse.BooleanOptionalAction, default=None,
        help="Set tests_passed: true|false on report handoff",
    )

    p.add_argument("--out", default=None,
                   help="Override output filename (default: <task>-<phase>-<date>-<from>.yaml)")
    p.add_argument("--force", action="store_true", default=False,
                   help="Overwrite existing handoff file")
    p.add_argument("--json", action="store_true", default=False,
                   help="Emit machine-readable JSON result on stdout.")
    return p


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # Allow `shux handoff write ...` and `shux handoff-write ...` both.
    # When first arg is the literal "write", drop it.
    if argv and argv[0] == "write":
        argv = argv[1:]

    parser = _build_parser()
    args = parser.parse_args(argv)

    global _JSON_MODE, _JSON_CTX
    if args.json:
        _JSON_MODE = True
        _JSON_CTX = {"task_id": args.task_id, "phase": args.phase}

    _validate_id("task id", args.task_id)

    project_dir = Path(args.project or os.getcwd()).expanduser().resolve()
    rc, result = write_handoff(project_dir, args)

    if _JSON_MODE:
        from superharness.utils.json_output import emit_json
        emit_json({
            "task_id": args.task_id,
            "phase": args.phase,
            "path": result.get("path"),
        }, ok=(rc == 0), exit_code=rc)

    print(f"Wrote handoff: {result['path']}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
