"""shux contract --validate implementation.

Validates the contract data from SQLite against the Pydantic Contract schema.
Exits 0 if clean, non-zero with a structured error report on any violation.
"""
from __future__ import annotations

import os
import sys

from pydantic import ValidationError

from superharness.engine.schemas import Contract


def validate_contract(project_dir: str | None = None) -> int:
    if project_dir is None:
        project_dir = os.getcwd()

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        print(f"[ERROR] project state not found: {harness_dir}", file=sys.stderr)
        return 1

    from superharness.engine.state_reader import get_contract_doc
    try:
        doc = get_contract_doc(project_dir)
    except Exception as exc:
        print(f"[ERROR] failed to read contract: {exc}", file=sys.stderr)
        return 1

    if not isinstance(doc, dict):
        print("[ERROR] contract data is not a valid mapping", file=sys.stderr)
        return 1

    try:
        contract = Contract.model_validate(doc)
        task_count = len(contract.tasks)
        print(f"[OK] {project_dir}: valid ({task_count} task{'s' if task_count != 1 else ''})")
        return 0
    except ValidationError as exc:
        errors = exc.errors()
        print(f"[ERROR] {len(errors)} schema violation(s) in contract data:", file=sys.stderr)
        for err in errors:
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
        return len(errors)


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="contract validate",
        description="Validate contract data (from SQLite) against the Contract schema.",
    )
    p.add_argument(
        "--project-dir",
        default=None,
        help="Project root directory (default: cwd)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output errors as JSON for machine consumption",
    )
    opts = p.parse_args(argv if argv is not None else sys.argv[1:])

    if opts.json:
        _main_json(opts.project_dir)
    else:
        sys.exit(validate_contract(opts.project_dir))


def _main_json(project_dir: str | None) -> None:
    import json

    if project_dir is None:
        project_dir = os.getcwd()

    result: dict = {"project_dir": project_dir, "valid": False, "errors": []}

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        result["errors"].append({"type": "not_found", "msg": f"project state not found: {harness_dir}"})
        print(json.dumps(result))
        sys.exit(1)

    from superharness.engine.state_reader import get_contract_doc
    try:
        doc = get_contract_doc(project_dir)
    except Exception as exc:
        result["errors"].append({"type": "read_error", "msg": str(exc)})
        print(json.dumps(result))
        sys.exit(1)

    try:
        Contract.model_validate(doc)
        result["valid"] = True
        print(json.dumps(result))
        sys.exit(0)
    except ValidationError as exc:
        for err in exc.errors():
            result["errors"].append({
                "loc": list(err["loc"]),
                "msg": err["msg"],
                "type": err["type"],
            })
        print(json.dumps(result))
        sys.exit(len(exc.errors()))
