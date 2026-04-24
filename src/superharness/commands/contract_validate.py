"""shux contract --validate implementation.

Validates .superharness/contract.yaml against the Pydantic Contract schema.
Exits 0 if clean, non-zero with a structured error report on any violation.
"""
from __future__ import annotations

import os
import sys

import yaml
from pydantic import ValidationError

from superharness.engine.schemas import Contract


def validate_contract(project_dir: str | None = None) -> int:
    if project_dir is None:
        project_dir = os.getcwd()

    path = os.path.join(project_dir, ".superharness", "contract.yaml")

    if not os.path.exists(path):
        print(f"[ERROR] contract not found: {path}", file=sys.stderr)
        return 1

    with open(path, encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print(f"[ERROR] YAML parse error in {path}:", file=sys.stderr)
            print(f"  {exc}", file=sys.stderr)
            return 1

    if not isinstance(doc, dict):
        print(f"[ERROR] contract is not a YAML mapping: {path}", file=sys.stderr)
        return 1

    try:
        contract = Contract.model_validate(doc)
        task_count = len(contract.tasks)
        print(f"[OK] {path}: valid ({task_count} task{'s' if task_count != 1 else ''})")
        return 0
    except ValidationError as exc:
        errors = exc.errors()
        print(f"[ERROR] {len(errors)} schema violation(s) in {path}:", file=sys.stderr)
        for err in errors:
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
        return len(errors)


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="contract validate",
        description="Validate .superharness/contract.yaml against the Contract schema.",
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
    path = os.path.join(project_dir, ".superharness", "contract.yaml")

    result: dict = {"path": path, "valid": False, "errors": []}

    if not os.path.exists(path):
        result["errors"].append({"type": "not_found", "msg": f"contract not found: {path}"})
        print(json.dumps(result))
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            result["errors"].append({"type": "yaml_parse", "msg": str(exc)})
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
