"""superharness verify — record verification result for a contract task.

Sets verified/verified_at/verified_by on the task in contract.yaml
and appends a VERIFY entry to ledger.md.
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




def verify(
    contract_file: str,
    task_id: str,
    method: str,
    result: str,
    actor: str,
) -> int:
    if result not in ("pass", "fail"):
        _abort("--result must be 'pass' or 'fail'", 2)

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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if result == "pass":
        task["verified"] = True
        task["verified_at"] = now
        task["verified_by"] = actor
    else:
        task["verified"] = False
        task["verified_at"] = now
        task["verified_by"] = actor

    _write_contract(contract_file, doc)

    # Append VERIFY entry to ledger
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
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
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")

    global _JSON_MODE, _JSON_CTX
    if opts.json:
        _JSON_MODE = True
        _JSON_CTX = {"task_id": opts.task_id, "actor": opts.actor, "result": opts.result}

    if _JSON_MODE:
        import io
        _orig_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = verify(contract_file, opts.task_id, opts.method, opts.result, opts.actor)
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

    rc = verify(contract_file, opts.task_id, opts.method, opts.result, opts.actor)
    sys.exit(rc)


if __name__ == "__main__":
    main()
