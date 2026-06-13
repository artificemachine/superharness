"""superharness verify — record verification result for a contract task.

Sets verified/verified_at/verified_by on the task in SQLite
and appends a VERIFY entry to ledger.md.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import NoReturn


_JSON_MODE = False
_JSON_CTX: dict = {}


def _abort(msg: str, code: int = 1) -> NoReturn:
    if _JSON_MODE:
        from superharness.utils.json_output import emit_error
        emit_error(msg, exit_code=code, **_JSON_CTX)
    print(msg, file=sys.stderr)
    sys.exit(code)


def verify(
    project_dir: str,
    task_id: str,
    method: str,
    result: str,
    actor: str,
) -> int:
    if result not in ("pass", "fail"):
        _abort("--result must be 'pass' or 'fail'", 2)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    requested_pass = result == "pass"

    # Fire on_verify lifecycle hooks (e.g. the security module's SAST scan).
    # A hook that declares block_on and reports a block hard-gates a requested
    # pass: it is recorded as not verified and the command exits non-zero.
    blocked_by = _fire_on_verify(project_dir, task_id, method, result, actor)
    gated_pass = requested_pass and not blocked_by

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        task_row = tasks_dao.get(conn, task_id)
        if task_row is None:
            _abort(f"task '{task_id}' not found")

        tasks_dao.update(conn, task_id, task_row.version, {
            "verified": gated_pass,
            "verified_at": now,
            "verified_by": actor,
            "updated_at": now,
        })
        conn.commit()
    finally:
        conn.close()

    ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
    if requested_pass and blocked_by:
        detail = "; ".join(
            f"{r.get('module', '?')}: {r.get('message') or r.get('error') or 'blocked'}"
            for r in blocked_by
        )
        verdict = "BLOCKED"
    else:
        detail = method
        verdict = "PASS" if gated_pass else "FAIL"

    ledger_line = f"- {now} — {actor} — VERIFY {verdict}: {task_id} — {detail}\n"
    try:
        with open(ledger_file, "a") as f:
            f.write(ledger_line)
    except OSError as e:
        print(f"Warning: could not append to ledger: {e}", file=sys.stderr)

    if verdict == "BLOCKED":
        print(
            f"Verification BLOCKED for '{task_id}' — {detail}. Recorded as not verified.",
            file=sys.stderr,
        )
        return 3

    print(f"Verified task '{task_id}': {verdict} (method: {method})")
    return 0


def _fire_on_verify(
    project_dir: str, task_id: str, method: str, result: str, actor: str
) -> list[dict]:
    """Run on_verify module hooks; return the subset that gate verification.

    A hook error must never mask verification — failures are logged and treated
    as non-blocking.
    """
    try:
        from pathlib import Path
        from superharness.modules.runner import run_hooks

        results = run_hooks(
            "on_verify",
            {
                "task_id": task_id,
                "project_dir": project_dir,
                "actor": actor,
                "result": result,
                "method": method,
            },
            Path(project_dir),
        )
        return [r for r in results if r.get("blocked")]
    except Exception as e:
        print(f"Warning: on_verify hooks failed: {e}", file=sys.stderr)
        return []


def _read_verified(project_dir: str, task_id: str) -> bool:
    """Read the persisted verified flag for a task (authoritative post-gate)."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        row = tasks_dao.get(conn, task_id)
        return bool(row.verified) if row is not None else False
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="verify",
        description="Record verification result for a contract task",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--id", dest="task_id", required=True)
    parser.add_argument("--method", required=True, help="How the task was verified (free text)")
    parser.add_argument("--result", required=True, choices=["pass", "fail"])
    parser.add_argument("--actor", default="claude-code")
    parser.add_argument("--json", action="store_true", default=False,
                        help="Emit machine-readable JSON on stdout instead of human text.")

    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())

    global _JSON_MODE, _JSON_CTX
    if opts.json:
        _JSON_MODE = True
        _JSON_CTX = {"task_id": opts.task_id, "actor": opts.actor, "result": opts.result}

    if _JSON_MODE:
        import io
        _orig_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = verify(project_dir, opts.task_id, opts.method, opts.result, opts.actor)
        finally:
            sys.stdout = _orig_stdout
        # Read the authoritative verified state — a block can downgrade a
        # requested pass, so don't infer it from opts.result.
        actual_verified = _read_verified(project_dir, opts.task_id)
        from superharness.utils.json_output import emit_json
        emit_json({
            "task_id": opts.task_id,
            "actor": opts.actor,
            "method": opts.method,
            "result": opts.result,
            "verified": actual_verified,
            "blocked": (opts.result == "pass" and not actual_verified),
        }, ok=(rc == 0), exit_code=rc)

    rc = verify(project_dir, opts.task_id, opts.method, opts.result, opts.actor)
    sys.exit(rc)


if __name__ == "__main__":
    main()
