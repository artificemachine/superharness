"""superharness close — mark a task done with verification gate.

Gates on verified: true. If not verified, prints an actionable error
telling the user to run `superharness verify` first.

On success: sets status=done, appends ledger, writes handoff YAML.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from superharness.engine.contract_io import write_contract as _write_contract, read_contract as _read_contract


_JSON_MODE = False
_JSON_CTX: dict = {}


def _abort(msg: str, code: int = 1) -> None:
    if _JSON_MODE:
        from superharness.utils.json_output import emit_error
        emit_error(msg, exit_code=code, **_JSON_CTX)
    print(msg, file=sys.stderr)
    sys.exit(code)




_CLOSE_ALLOWED_STATUSES = {"report_ready", "review_passed"}


def _cancel_open_subtasks(
    task: dict,
    actor: str,
    reason: str,
    now: str,
    ledger_file: str,
) -> None:
    """Cancel every open subtask in-place and write ledger entries."""
    from superharness.engine.subtask import is_subtask_resolved
    task_id = str(task.get("id", ""))
    for sub in (task.get("subtasks") or []):
        if not isinstance(sub, dict):
            continue
        if is_subtask_resolved(str(sub.get("status", "pending"))):
            continue
        sub["status"] = "cancelled"
        sub_id = str(sub.get("id", "?"))
        line = (
            f"- {now} — {actor} — SUBTASK_CANCEL: {sub_id} "
            f"(parent={task_id}) — {reason}\n"
        )
        try:
            with open(ledger_file, "a") as f:
                f.write(line)
        except OSError as e:
            print(f"Warning: could not append to ledger: {e}", file=sys.stderr)


def close_task(
    contract_file: str,
    task_id: str,
    actor: str,
    summary: str,
    skip_verify: bool = False,
    context: str = "",
    force: bool = False,
    cancel_remaining: bool = False,
    cancel_reason: str = "",
) -> int:
    doc, _ = _read_contract(contract_file)
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        _abort("contract tasks must be a sequence")

    task = next(
        (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id),
        None,
    )
    if task is None:
        _abort(f"task '{task_id}' not found")

    owner = str(task.get("owner", ""))
    if owner and actor != owner and actor != "owner":
        _abort(f"forbidden: actor '{actor}' cannot close task '{task_id}' owned by '{owner}'")

    # Status lifecycle gate (bypass with --force for emergencies)
    if not force:
        current_status = str(task.get("status", ""))
        if current_status not in _CLOSE_ALLOWED_STATUSES:
            print(
                f"Cannot close task '{task_id}': status is '{current_status}', "
                f"expected report_ready or review_passed.\n"
                f"Run: superharness task status --id {task_id} --status report_ready --actor <agent> --summary '<summary>'",
                file=sys.stderr,
            )
            return 1

    # Subtask resolution gate
    if not force:
        try:
            from superharness.engine.subtask_gate import (
                evaluate_subtask_gate_from_disk,
                format_gate_error,
            )
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
            gate = evaluate_subtask_gate_from_disk(task, project_dir)
            if gate.enabled and gate.blocking:
                if cancel_remaining:
                    if not cancel_reason:
                        print(
                            "error: --cancel-remaining requires --cancel-reason",
                            file=sys.stderr,
                        )
                        return 1
                    # Will bulk-cancel below, after verification gate
                else:
                    print(format_gate_error(task_id, gate), file=sys.stderr)
                    return 1
        except ImportError:
            pass

    # Verification gate
    if not skip_verify and not task.get("verified"):
        print(
            f"Cannot close task '{task_id}': not verified.\n"
            f"Run: superharness verify --id {task_id} --method '<how you verified>' --result pass",
            file=sys.stderr,
        )
        return 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Bulk-cancel open subtasks when --cancel-remaining was requested
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
    ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
    if cancel_remaining and cancel_reason:
        _cancel_open_subtasks(task, actor, cancel_reason, now, ledger_file)

    # Log force-bypass to ledger when used
    if force:
        try:
            from superharness.engine.subtask_gate import evaluate_subtask_gate_from_disk
            gate = evaluate_subtask_gate_from_disk(task, project_dir)
            if gate.enabled and gate.blocking:
                sub_ids = ", ".join(str(s.get("id", "?")) for s in gate.blocking)
                force_line = (
                    f"- {now} — {actor} — FORCE_CLOSE_WARNING: {task_id} — "
                    f"gate bypassed with open subtasks: {sub_ids}\n"
                )
                try:
                    with open(ledger_file, "a") as f:
                        f.write(force_line)
                except OSError:
                    pass
        except ImportError:
            pass

    task["status"] = "done"
    if summary:
        task["summary"] = summary

    _write_contract(contract_file, doc)

    # Append ledger entry
    ledger_line = f"- {now} — {actor} — CLOSE: {task_id} — {summary}\n"
    try:
        with open(ledger_file, "a") as f:
            f.write(ledger_line)
    except OSError as e:
        print(f"Warning: could not append to ledger: {e}", file=sys.stderr)

    # Write handoff YAML
    handoff_dir = os.path.join(project_dir, ".superharness", "handoffs")
    os.makedirs(handoff_dir, exist_ok=True)
    handoff_file = os.path.join(handoff_dir, f"{task_id}-to-owner.yaml")
    handoff_data = {
        "task": task_id,
        "from": actor,
        "to": "owner",
        "status": "done",
        "summary": summary,
        "closed_at": now,
    }
    if context:
        handoff_data["context"] = context
    try:
        from superharness.commands.rules import all_rules_text
        rules_text = all_rules_text(project_dir)
        if rules_text:
            handoff_data["rules"] = rules_text
    except Exception:
        pass
    try:
        from superharness.engine.state_writer import upsert_handoff
        if not upsert_handoff(project_dir, f"{task_id}-to-owner", handoff_data):
            raise OSError("upsert_handoff returned False")
    except Exception as e:
        print(f"Warning: could not write handoff: {e}", file=sys.stderr)

    # Sync inbox
    try:
        from superharness.commands.task import _sync_inbox_after_status
        _sync_inbox_after_status(project_dir, task_id, "done")
    except Exception:
        pass

    # Vault integration
    try:
        from superharness.commands.task import _vault_write_task_done
        _vault_write_task_done(contract_file, task_id, task, summary)
    except Exception:
        pass

    # Worktree cleanup — remove the dispatch worktree recorded for this task
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        init_db(conn)
        row = conn.execute(
            "SELECT worktree_path FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        wt_path = row["worktree_path"] if row and row["worktree_path"] else None
        conn.close()
        if wt_path:
            import shutil, subprocess
            harness_link = os.path.join(wt_path, ".superharness")
            if os.path.islink(harness_link):
                os.unlink(harness_link)
            rr = subprocess.run(
                ["git", "-C", project_dir, "worktree", "remove", "--force", wt_path],
                capture_output=True, check=False,
            )
            if rr.returncode != 0 and os.path.isdir(wt_path):
                shutil.rmtree(wt_path, ignore_errors=True)
            subprocess.run(
                ["git", "-C", project_dir, "worktree", "prune"],
                capture_output=True, check=False,
            )
    except Exception as e:
        print(f"Warning: failed to clean up worktree for '{task_id}': {e}", file=sys.stderr)

    print(f"Closed task '{task_id}' (actor={actor})")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="close",
        description="Close a verified task: mark done, append ledger, write handoff",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--id", dest="task_id", required=True)
    parser.add_argument("--actor", default="claude-code")
    parser.add_argument("--summary", default="Task completed and verified")
    parser.add_argument(
        "--skip-verify", action="store_true", default=False,
        help="Bypass verification gate (not recommended)",
    )
    parser.add_argument(
        "--force", action="store_true", default=False,
        help="Bypass status lifecycle gate (emergency use only)",
    )
    parser.add_argument(
        "--context", default="",
        help="What the next session needs to know (written to handoff YAML)",
    )
    parser.add_argument(
        "--cancel-remaining", action="store_true", default=False,
        help="Cancel every open subtask with --cancel-reason, then close the task.",
    )
    parser.add_argument(
        "--cancel-reason", default="",
        help="Reason for bulk-cancelling open subtasks (required with --cancel-remaining).",
    )
    parser.add_argument("--json", action="store_true", default=False,
                        help="Emit machine-readable JSON on stdout instead of human text.")

    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")

    global _JSON_MODE, _JSON_CTX
    if opts.json:
        _JSON_MODE = True
        _JSON_CTX = {"task_id": opts.task_id, "actor": opts.actor}

    if not os.path.exists(os.path.join(project_dir, ".superharness", "state.sqlite3")):
        _abort(f"Missing project state: {project_dir}/.superharness/state.sqlite3")

    if _JSON_MODE:
        import io
        _orig_stdout = sys.stdout
        _orig_stderr = sys.stderr
        sys.stdout = io.StringIO()
        _err_buf = io.StringIO()
        sys.stderr = _err_buf
        try:
            rc = close_task(
                contract_file, opts.task_id, opts.actor, opts.summary,
                skip_verify=opts.skip_verify,
                context=opts.context,
                force=opts.force,
                cancel_remaining=opts.cancel_remaining,
                cancel_reason=opts.cancel_reason,
            )
        finally:
            sys.stdout = _orig_stdout
            sys.stderr = _orig_stderr
        payload: dict = {
            "task_id": opts.task_id,
            "actor": opts.actor,
            "closed": (rc == 0),
        }
        if rc != 0:
            payload["error"] = _err_buf.getvalue().strip() or "close failed"
        from superharness.utils.json_output import emit_json
        emit_json(payload, ok=(rc == 0), exit_code=rc)

    rc = close_task(
        contract_file, opts.task_id, opts.actor, opts.summary,
        skip_verify=opts.skip_verify,
        context=opts.context,
        force=opts.force,
        cancel_remaining=opts.cancel_remaining,
        cancel_reason=opts.cancel_reason,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
