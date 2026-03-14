"""Python port of contract-today.sh.

Shows active contract summary with task table, pending approvals,
and delegate suggestion for team projects.
"""
from __future__ import annotations

import os
import sys


def _status_label(s: str) -> str:
    mapping = {
        "done": "✅ done",
        "in_progress": "🟡 in_progress",
        "todo": "🔲 todo",
        "failed": "❌ failed",
        "stale": "⚠️ stale",
    }
    return mapping.get(s, s or "🔲 todo")


def _pad(s: str, width: int) -> str:
    return s + " " * max(width - len(s), 0)


def _hline(left: str, mid: str, right: str, widths: list[int]) -> str:
    return left + mid.join("─" * (w + 2) for w in widths) + right


def _row(cells: list[str], widths: list[int]) -> str:
    return "│ " + " │ ".join(_pad(c, widths[i]) for i, c in enumerate(cells)) + " │"


def _read_team_size(project_dir: str) -> str:
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.isfile(profile_file):
        return "team"  # no profile → default team (matches original Bash behaviour)
    try:
        import yaml
        with open(profile_file) as f:
            doc = yaml.safe_load(f) or {}
        return str(doc.get("team_size") or "team")
    except Exception:
        return "team"


def contract_today(project_dir: str, agent: str = "") -> int:
    import yaml

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.isfile(contract_file):
        print(f"Missing contract file: {contract_file}", file=sys.stderr)
        return 1

    try:
        with open(contract_file) as f:
            doc = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Failed to parse contract: {e}", file=sys.stderr)
        return 1

    tasks = doc.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []

    rows_raw = [
        [
            str(t.get("id", "")) if isinstance(t, dict) else "",
            str(t.get("title", "")) if isinstance(t, dict) else "",
            _status_label(str(t.get("status", "")) if isinstance(t, dict) else ""),
            str(t.get("owner", "")) if isinstance(t, dict) else "",
        ]
        for t in tasks
    ]

    headers = ["ID", "Title", "Status", "Owner"]
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows_raw) if rows_raw else [0])
        for i in range(4)
    ]

    print(f"Contract {doc.get('id') or 'unknown'} — {doc.get('created') or 'unknown'}")
    goal = str(doc.get("goal") or "")
    if goal:
        print(f"Goal: {goal}")

    print(_hline("┌", "┬", "┐", widths))
    print(_row(headers, widths))
    print(_hline("├", "┼", "┤", widths))
    for idx, r in enumerate(rows_raw):
        print(_row(r, widths))
        if idx < len(rows_raw) - 1:
            print(_hline("├", "┼", "┤", widths))
    print(_hline("└", "┴", "┘", widths))

    # Pending user approvals
    handoff_dir = os.path.join(project_dir, ".superharness", "handoffs")
    pending_approvals: list[tuple[str, str]] = []
    if os.path.isdir(handoff_dir):
        for fname in sorted(os.listdir(handoff_dir)):
            if not fname.endswith(".yaml"):
                continue
            fpath = os.path.join(handoff_dir, fname)
            try:
                with open(fpath) as f:
                    hdoc = yaml.safe_load(f) or {}
            except Exception:
                continue
            if not isinstance(hdoc, dict):
                continue
            gate = hdoc.get("approval_gate")
            is_pending = (
                str(hdoc.get("status", "")) == "pending_user_approval"
                or (
                    isinstance(gate, dict)
                    and gate.get("required")
                    and not gate.get("approved_by_user")
                )
            )
            if is_pending:
                pending_approvals.append(
                    (str(hdoc.get("task") or ""), str(hdoc.get("markdown_report") or ""))
                )

    if pending_approvals:
        print()
        print("⚠️  USER APPROVAL REQUIRED")
        for task_id, report in pending_approvals:
            print(f"- task={task_id} report={report}")
            print(f'  approve: superharness discuss approve --task {task_id} --by owner --note "Approved"')

    # Delegate suggestion (team mode only)
    team_size = _read_team_size(project_dir)
    if team_size != "solo":
        candidate = None
        for t in tasks:
            if not isinstance(t, dict):
                continue
            status = str(t.get("status") or "")
            owner = str(t.get("owner") or "")
            if status not in ("todo", "in_progress"):
                continue
            if not owner:
                continue
            if agent and owner == agent:
                continue
            candidate = t
            break

        if candidate:
            print(
                f"I detected owner is {candidate['owner']}. "
                f"Do you want to delegate {candidate['id']} now?"
            )

    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    class _CapUsage(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(usage, actions, groups, "Usage: ")

    parser = argparse.ArgumentParser(
        prog="contract_today",
        description="Show active contract summary and delegate suggestion",
        formatter_class=_CapUsage,
        add_help=True,
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--agent", default="")

    opts = parser.parse_args(argv)
    project_dir = os.path.realpath(opts.project or os.getcwd())

    if not os.path.isdir(project_dir):
        print(f"Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    rc = contract_today(project_dir, agent=opts.agent)
    sys.exit(rc)


if __name__ == "__main__":
    main()
