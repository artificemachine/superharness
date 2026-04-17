"""Python port of engine/validate.rb — contract protocol hygiene checker."""
from __future__ import annotations

import glob
import os
import re
import sys
from datetime import datetime, timezone

import yaml as _yaml

from superharness.engine.yaml_helpers import safe_load
from superharness.engine.taxonomy import VALID_EFFORTS as _VALID_EFFORTS

HELP_TEXT = """\
Usage:
  hygiene --project DIR [--strict] [--repair]

Validates contract protocol hygiene for a superharness project.

Options:
  -p, --project DIR   Project directory containing .superharness/ (default: cwd)
  --strict            Warn on empty decision/failure stores
  --repair            Auto-fix issues: create missing handoffs, append ledger entries,
                      fix stuck statuses (verified=true but status!=done).
                      Without --repair, the check is read-only.
  -h, --help          Show this help message and exit

Checks:
  - All required protocol files and directories exist
  - Every done task has a matching handoff YAML
  - Every done task appears in ledger.md
  - (strict) Decisions/failures in contract are promoted to store files
"""


def _repair_create_handoff(task_id: str, handoff_dir: str) -> str:
    """Create a skeleton handoff YAML for a done task. Returns the file path."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_id = task_id.replace("/", "_").replace("..", "_")
    filename = f"{safe_id}-repair-{now[:10]}.yaml"
    path = os.path.join(handoff_dir, filename)
    content = (
        f"task: {task_id}\n"
        f"phase: report\n"
        f"status: done\n"
        f"from: repair\n"
        f"to: owner\n"
        f"date: {now}\n"
        f"outcome: |\n"
        f"  Skeleton handoff created by hygiene --repair.\n"
        f"  Original handoff was missing; task was already marked done.\n"
    )
    with open(path, "w") as f:
        f.write(content)
    return path


def _repair_append_ledger(ledger_file: str, message: str) -> None:
    """Append a [repair]-prefixed line with ISO timestamp to ledger.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"- {now} — [repair] — {message}\n"
    with open(ledger_file, "a") as f:
        f.write(line)


def _repair_fix_stuck_status(task_id: str, contract_file: str) -> None:
    """Set task status to done when verified=true but status is not done."""
    with open(contract_file) as f:
        text = f.read()
    data = _yaml.safe_load(text)
    for task in data.get("tasks") or []:
        if str(task.get("id", "")) == task_id:
            task["status"] = "done"
            break
    with open(contract_file, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def run_validate(project: str, strict: bool = False, repair: bool = False) -> int:
    harness_dir = os.path.join(project, ".superharness")
    contract_file = os.path.join(harness_dir, "contract.yaml")
    handoff_dir = os.path.join(harness_dir, "handoffs")
    ledger_file = os.path.join(harness_dir, "ledger.md")
    decisions_file = os.path.join(harness_dir, "decisions.yaml")
    failures_file = os.path.join(harness_dir, "failures.yaml")

    for path in (harness_dir, contract_file, handoff_dir, ledger_file):
        if not os.path.exists(path):
            print(f"Missing required path: {path}", file=sys.stderr)
            return 1

    if not (os.path.isfile(decisions_file) and os.path.isfile(failures_file)):
        print(f"Missing decisions/failures store under {harness_dir}", file=sys.stderr)
        return 1

    contract = safe_load(contract_file, dict)
    raw_tasks = contract.get("tasks")
    if raw_tasks is None:
        tasks: list = []
    elif not isinstance(raw_tasks, list):
        raise ValueError("tasks must be a sequence")
    else:
        tasks = raw_tasks

    done_tasks = [
        t for t in tasks
        if isinstance(t, dict) and str(t.get("status", "")) == "done" and str(t.get("id", "")).strip()
    ]

    ledger_text = ""
    if os.path.exists(ledger_file):
        with open(ledger_file) as f:
            ledger_text = f.read()

    handoff_files = glob.glob(os.path.join(handoff_dir, "*.yaml"))
    issues = 0
    handoff_map: dict[str, list[str]] = {}
    for hfile in handoff_files:
        try:
            data = safe_load(hfile, dict)
        except Exception as e:
            print(f"Warning: corrupt handoff file {hfile}: {e}")
            issues += 1
            continue
        task_id = str(data.get("task", "")).strip()
        if not task_id:
            continue
        handoff_map.setdefault(task_id, []).append(hfile)

    for task in done_tasks:
        id_ = str(task.get("id", "")).strip()
        if not handoff_map.get(id_):
            if repair:
                path = _repair_create_handoff(id_, handoff_dir)
                _repair_append_ledger(ledger_file, f"created skeleton handoff for {id_}: {os.path.basename(path)}")
                print(f"[repair] Created handoff for done task: {id_}")
            else:
                print(f"Missing handoff file for done task: {id_}")
                issues += 1
        if not re.search(r"\b" + re.escape(id_) + r"\b", ledger_text):
            if repair:
                _repair_append_ledger(ledger_file, f"backfilled ledger entry for done task: {id_}")
                ledger_text += f"\n{id_} done\n"
                print(f"[repair] Appended ledger entry for: {id_}")
            else:
                print(f"Missing ledger mention for done task: {id_}")
                issues += 1
        test_types = task.get("test_types")
        if test_types and isinstance(test_types, list):
            print(f"Warning: task '{id_}' requires test types [{', '.join(str(t) for t in test_types)}] — verify evidence before close")
        if not task.get("verified"):
            print(f"Warning: task '{id_}' closed without verification record")
            issues += 1

    # Stuck-status check: verified=true but status != done
    for task in tasks:
        if not isinstance(task, dict):
            continue
        id_ = str(task.get("id", "")).strip()
        status = str(task.get("status", ""))
        verified = task.get("verified")
        if verified and status not in ("done", ""):
            if repair:
                _repair_fix_stuck_status(id_, contract_file)
                _repair_append_ledger(ledger_file, f"fixed stuck status for {id_}: {status} → done")
                print(f"[repair] Fixed stuck status for: {id_} ({status} → done)")
            else:
                print(f"Warning: task '{id_}' has verified=true but status={status} (stuck)")
                issues += 1

    # Effort value validation
    for task in tasks:
        if not isinstance(task, dict):
            continue
        id_ = str(task.get("id", "")).strip()
        effort = task.get("effort")
        if effort is not None and str(effort) not in _VALID_EFFORTS:
            print(f"Warning: task '{id_}' has invalid effort='{effort}' (expected: {'/'.join(_VALID_EFFORTS)})")
            issues += 1

    # Features.json validation
    features_file = os.path.join(harness_dir, "features.json")
    if os.path.isfile(features_file):
        try:
            import json
            with open(features_file) as f:
                features_doc = json.load(f)
            features = features_doc.get("features", [])
            if not isinstance(features, list):
                print("features.json: 'features' must be an array")
                issues += 1
            else:
                seen_ids: set[str] = set()
                for feat in features:
                    fid = feat.get("id", "")
                    if fid in seen_ids:
                        print(f"features.json: duplicate feature id '{fid}'")
                        issues += 1
                    seen_ids.add(fid)
                    if not isinstance(feat.get("passes"), bool):
                        print(f"features.json: feature '{fid}' missing boolean 'passes' field")
                        issues += 1
        except (json.JSONDecodeError, OSError) as e:
            print(f"features.json: invalid JSON: {e}")
            issues += 1

    contract_decision_count = len(contract.get("decisions") or []) if isinstance(contract.get("decisions"), list) else 0
    contract_failure_count = len(contract.get("failures") or []) if isinstance(contract.get("failures"), list) else 0

    decisions = safe_load(decisions_file, dict)
    failures = safe_load(failures_file, dict)
    decision_store_count = len(decisions.get("decisions") or []) if isinstance(decisions.get("decisions"), list) else 0
    failure_store_count = len(failures.get("failures") or []) if isinstance(failures.get("failures"), list) else 0

    if strict and contract_decision_count > 0 and decision_store_count == 0:
        print("Contract has decisions but decisions.yaml is empty. Promote reusable decisions.")
        issues += 1
    if strict and contract_failure_count > 0 and failure_store_count == 0:
        print("Contract has failures but failures.yaml is empty. Promote reusable failures.")
        issues += 1

    # Vault backlog index check (optional — skipped if vault not configured)
    vault_base = os.environ.get("SUPERHARNESS_VAULT_BASE", "")
    if vault_base:
        backlog_index = os.path.join(vault_base, "notes", "0_meta", "backlog", "_backlog_index.md")
        if os.path.isfile(backlog_index):
            with open(backlog_index) as f:
                backlog_text = f.read()
            unchecked = [line.strip() for line in backlog_text.splitlines() if line.strip().startswith("- [ ]")]
            print(f"Vault backlog: {len(unchecked)} open item(s) in _backlog_index.md")
        else:
            print("Warning: vault backlog index not found (notes/0_meta/backlog/_backlog_index.md)")

    if issues > 0:
        print()
        print(f"Contract hygiene check failed with {issues} issue(s).")
        return 1

    print("Contract hygiene check passed.")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project", "-p")
    parser.add_argument("--strict", action="store_true", default=False)
    parser.add_argument("--repair", action="store_true", default=False)
    parser.add_argument("--help", "-h", action="store_true", default=False)
    opts = parser.parse_args(argv)

    if opts.help:
        print(HELP_TEXT, end="")
        sys.exit(0)

    try:
        project = os.path.realpath(opts.project or os.getcwd())
    except OSError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    rc = run_validate(project, strict=opts.strict, repair=opts.repair)
    sys.exit(rc)


if __name__ == "__main__":
    main()
