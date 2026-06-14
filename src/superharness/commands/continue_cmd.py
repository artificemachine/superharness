"""superharness continue — resume the active contract.

Read-only orientation helper: finds the most in-flight resumable task, prints
its recommended next action (from the lifecycle state machine) and latest
handoff, and fires on_continue lifecycle hooks (e.g. the remember module's
refresh_context). It performs no status writes and no dispatch — use
`shux delegate` to dispatch and `shux task status` to advance.
"""
from __future__ import annotations

import os
import sys

# Active statuses in resume priority — most "in flight" first. Terminal
# statuses (done/failed/stopped/cancelled) are intentionally absent: there is
# nothing to resume on a closed task.
_RESUME_PRIORITY = [
    "in_progress",
    "waiting_input",
    "review_failed",
    "plan_approved",
    "report_ready",
    "review_requested",
    "plan_proposed",
    "review_passed",
    "todo",
]


def _pick_resumable(tasks: list[dict]) -> dict | None:
    """Return the most in-flight resumable task, or None if all are terminal.

    Picks by status priority; ties broken by most-recently-updated.
    """
    for status in _RESUME_PRIORITY:
        candidates = [t for t in tasks if (t.get("status") or "") == status]
        if candidates:
            return max(candidates, key=lambda t: str(t.get("updated_at") or ""))
    return None


def _fire_on_continue(project_dir: str, task_id: str) -> None:
    """Fire on_continue lifecycle hooks (remember/refresh_context, …).

    Best-effort: a hook failure must never break the resume helper.
    """
    try:
        from pathlib import Path
        from superharness.modules.runner import run_hooks
        run_hooks(
            "on_continue",
            {"task_id": task_id, "project_dir": project_dir, "event": "on_continue"},
            Path(project_dir),
        )
    except Exception as e:  # noqa: BLE001 — orientation must not fail on a hook
        print(f"Warning: on_continue hooks failed: {e}", file=sys.stderr)


def resume(project_dir: str, json_mode: bool = False) -> int:
    from superharness.engine import state_reader
    from superharness.engine.next_action import next_action

    tasks = state_reader.get_tasks(project_dir)
    task = _pick_resumable(tasks)
    task_id = str(task.get("id")) if task else ""

    if json_mode:
        payload: dict = {"resumable": bool(task)}
        if task:
            na = next_action(str(task.get("status") or ""))
            payload.update({
                "task_id": task_id,
                "status": task.get("status"),
                "recommended": na.recommended,
                "legal": na.legal,
                "reason": na.reason,
            })
        _fire_on_continue(project_dir, task_id)
        from superharness.utils.json_output import emit_json
        emit_json(payload, ok=True, exit_code=0)
        return 0

    if not task:
        print("No resumable task in the active contract — every task is done, failed, or stopped.")
        print("Create one with `shux task create` or see `shux contract`.")
        _fire_on_continue(project_dir, task_id)
        return 0

    status = str(task.get("status") or "")
    na = next_action(status)
    print(f"Resuming task '{task_id}' — {task.get('title') or ''}".rstrip())
    print(f"  status:      {status}")
    if na.recommended:
        print(f"  next action: {na.recommended}  ({na.reason})")
    else:
        print(f"  next action: (none) — {na.reason}")
    if na.legal:
        print(f"  legal:       {', '.join(na.legal)}")

    handoffs = state_reader.get_handoffs(project_dir, task_id)
    if handoffs:
        latest = handoffs[-1]
        body = (latest.get("outcome") or latest.get("context") or latest.get("plan") or "").strip()
        if body:
            snippet = body.splitlines()[0][:200]
            print(f"  latest handoff ({latest.get('phase') or latest.get('status') or '?'}): {snippet}")

    print("  Run `shux context " + task_id + "` for full context.")
    _fire_on_continue(project_dir, task_id)
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="continue",
        description="Resume the active contract: show the next resumable task and its recommended action.",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--json", action="store_true", default=False,
                        help="Emit machine-readable JSON instead of human text.")
    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    rc = resume(project_dir, json_mode=opts.json)
    sys.exit(rc)


if __name__ == "__main__":
    main()
