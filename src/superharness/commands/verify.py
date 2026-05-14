"""superharness verify — record verification result for a contract task.

Sets verified/verified_at/verified_by on the task in SQLite
and appends a VERIFY entry to ledger.md.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


_JSON_MODE = False
_JSON_CTX: dict = {}


def _abort(msg: str, code: int = 1) -> None:
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

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        task_row = tasks_dao.get(conn, task_id)
        if task_row is None:
            _abort(f"task '{task_id}' not found")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tasks_dao.update(conn, task_id, task_row.version, {
            "verified": result == "pass",
            "verified_at": now,
            "verified_by": actor,
            "updated_at": now,
        })
        conn.commit()
    finally:
        conn.close()

    ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
    verdict = "PASS" if result == "pass" else "FAIL"
    ledger_line = f"- {now} — {actor} — VERIFY {verdict}: {task_id} — {method}\n"
    try:
        with open(ledger_file, "a") as f:
            f.write(ledger_line)
    except OSError as e:
        print(f"Warning: could not append to ledger: {e}", file=sys.stderr)

    print(f"Verified task '{task_id}': {verdict} (method: {method})")
    return 0


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
        from superharness.utils.json_output import emit_json
        emit_json({
            "task_id": opts.task_id,
            "actor": opts.actor,
            "method": opts.method,
            "result": opts.result,
            "verified": (opts.result == "pass"),
        }, ok=(rc == 0), exit_code=rc)

    rc = verify(project_dir, opts.task_id, opts.method, opts.result, opts.actor)
    sys.exit(rc)


if __name__ == "__main__":
    main()
