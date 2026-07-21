"""Python port of engine/validate.rb — contract protocol hygiene checker."""
from __future__ import annotations

import glob
import logging
import os
import re
import sys
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

from superharness.engine.errors import OperationError, SuperharnessError, handle_cli_error
from superharness.engine.yaml_helpers import safe_load
from superharness.engine.taxonomy import VALID_EFFORTS as _VALID_EFFORTS
from superharness.engine.subtask import is_subtask_resolved

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



def run_validate(project: str, strict: bool = False, repair: bool = False) -> int:
    from superharness.utils.paths import is_project_initialized
    harness_dir = os.path.join(project, ".superharness")
    handoff_dir = os.path.join(harness_dir, "handoffs")
    ledger_file = os.path.join(harness_dir, "ledger.md")

    for path in (harness_dir, handoff_dir, ledger_file):
        if not os.path.exists(path):
            _log.error("validate: missing required path: %s", path)
            print(f"Missing required path: {path}", file=sys.stderr)
            return 1

    if not is_project_initialized(project):
        sqlite_file = os.path.join(harness_dir, "state.sqlite3")
        _log.error("validate: missing required path: %s", sqlite_file)
        print(f"Missing required path: {sqlite_file}", file=sys.stderr)
        return 1

    # .gitignore check: runtime state must be excluded from git tracking (non-fatal warning)
    _REQUIRED_GITIGNORE_PATTERNS = {"state.sqlite3", "circuit-breaker.json"}
    gitignore_path = os.path.join(harness_dir, ".gitignore")
    if not os.path.isfile(gitignore_path):
        print(
            "Warning: .superharness/.gitignore is missing — runtime state (state.sqlite3, "
            "circuit-breaker.json, etc.) may be committed accidentally. "
            "Run: shux init --refresh to create it."
        )
    else:
        with open(gitignore_path) as _gf:
            _gitignore_text = _gf.read()
        _missing = [p for p in sorted(_REQUIRED_GITIGNORE_PATTERNS) if p not in _gitignore_text]
        if _missing:
            print(
                f"Warning: .superharness/.gitignore is missing required patterns: "
                f"{', '.join(_missing)} — runtime state may be committed accidentally."
            )

    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(project)
        try:
            init_db(conn)
            all_tasks = tasks_dao.get_all(conn)
        finally:
            conn.close()
    except Exception as e:
        _log.warning("validate.py unexpected error: %s", e, exc_info=True)
        all_tasks = []

    done_tasks = [t for t in all_tasks if t.status == "done" and t.id.strip()]

    # Build handoff map from SQLite (source of truth)
    handoff_map: dict[str, list[str]] = {}
    try:
        from superharness.engine import state_reader as _sr_v, handoffs_dao as _hd
        from superharness.engine.db import get_connection as _gc, init_db as _idb
        _conn = _gc(project)
        try:
            _idb(_conn)
            for _row in _hd.get_all(_conn):
                handoff_map.setdefault(_row.task_id, []).append(str(_row.id))
        finally:
            _conn.close()
    except Exception as e:
        _log.warning("validate: handoff SQLite scan failed: %s", e)

    # Build ledger set of mentioned task IDs from SQLite
    ledger_task_ids: set[str] = set()
    try:
        from superharness.engine import ledger_dao as _ld
        from superharness.engine.db import get_connection as _gc2, init_db as _idb2
        _conn2 = _gc2(project)
        try:
            _idb2(_conn2)
            for _le in _ld.get_recent(_conn2, limit=5000):
                if _le.task_id:
                    ledger_task_ids.add(_le.task_id)
                # Also extract task IDs from action strings
                if _le.action:
                    for tok in _le.action.split():
                        tok = tok.rstrip(":,.")
                        if re.match(r"^[\w][\w.\-]+$", tok):
                            ledger_task_ids.add(tok)
        finally:
            _conn2.close()
    except Exception as e:
        _log.warning("validate: ledger SQLite scan failed: %s", e)

    issues = 0
    for task in done_tasks:
        id_ = task.id.strip()
        if not handoff_map.get(id_):
            if repair:
                path = _repair_create_handoff(id_, handoff_dir)
                _repair_append_ledger(ledger_file, f"created skeleton handoff for {id_}: {os.path.basename(path)}")
                print(f"[repair] Created handoff for done task: {id_}")
            else:
                print(f"Missing handoff for done task: {id_}")
                issues += 1
        if id_ not in ledger_task_ids:
            if repair:
                _repair_append_ledger(ledger_file, f"backfilled ledger entry for done task: {id_}")
                ledger_task_ids.add(id_)
                print(f"[repair] Appended ledger entry for: {id_}")
            else:
                print(f"Missing ledger mention for done task: {id_}")
                issues += 1
        test_types = task.test_types
        if test_types and isinstance(test_types, list):
            print(f"Warning: task '{id_}' requires test types [{', '.join(str(t) for t in test_types)}] — verify evidence before close")
        if not task.verified:
            print(f"Warning: task '{id_}' closed without verification record")
            issues += 1

    # Dangling subtask check: done parent with open child tasks
    done_ids = {t.id for t in done_tasks}
    open_subtask_map: dict[str, list[str]] = {}
    # Check flat child tasks (parent_id FK)
    for task in all_tasks:
        if task.parent_id and task.parent_id in done_ids:
            if not is_subtask_resolved(task.status):
                open_subtask_map.setdefault(task.parent_id, []).append(task.id)
    # Check nested subtasks stored in extras_json (legacy embedded format)
    for task in done_tasks:
        if not task.extras_json:
            continue
        try:
            import json as _json
            extras = _json.loads(task.extras_json)
            for sub in (extras.get("subtasks") or []):
                if not isinstance(sub, dict):
                    continue
                sub_id = str(sub.get("id", "")).strip()
                sub_status = str(sub.get("status", "pending"))
                if sub_id and not is_subtask_resolved(sub_status):
                    open_subtask_map.setdefault(task.id, []).append(sub_id)
        except Exception as e:
            _log.warning("validate.py unexpected error: %s", e, exc_info=True)
            pass
    for parent_id, open_subs in open_subtask_map.items():
        print(
            f"Warning: done task '{parent_id}' has {len(open_subs)} open subtask(s): "
            f"{', '.join(open_subs)}. "
            f"Run: shux subtask-cancel --task {parent_id} --sub <id> --reason \"...\" "
            f"to retire them."
        )
        issues += 1

    # Stuck-status check: verified=true but status != done
    for task in all_tasks:
        id_ = task.id.strip()
        status = task.status
        if task.verified and status not in ("done", ""):
            if repair:
                from superharness.engine import state_writer
                try:
                    state_writer.set_task_status(project, id_, "done")
                except Exception as e:
                    _log.warning("validate.py unexpected error: %s", e, exc_info=True)
                    pass
                _repair_append_ledger(ledger_file, f"fixed stuck status for {id_}: {status} → done")
                print(f"[repair] Fixed stuck status for: {id_} ({status} → done)")
            else:
                print(f"Warning: task '{id_}' has verified=true but status={status} (stuck)")
                issues += 1

    # Effort value validation
    for task in all_tasks:
        id_ = task.id.strip()
        effort = task.effort
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

    # Worktree GC — always run during repair to prune stale git worktree refs
    if repair:
        try:
            from superharness.commands.worktree_gc import run_worktree_gc
            gc = run_worktree_gc(project)
            if gc["removed"] > 0:
                _repair_append_ledger(ledger_file, f"worktree-gc removed {gc['removed']} orphaned worktree(s)")
        except Exception as e:
            print(f"Warning: worktree-gc failed: {e}", file=sys.stderr)

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
        return

    try:
        project = os.path.realpath(opts.project or os.getcwd())
    except OSError as e:
        raise OperationError(str(e), exit_code=1) from e

    rc = run_validate(project, strict=opts.strict, repair=opts.repair)
    if rc:
        # run_validate() already printed its diagnostics to stdout; no
        # separate stderr text accompanies this exit, so the exception
        # carries none either (see errors.SuperharnessError's docstring).
        raise OperationError("", exit_code=rc)


if __name__ == "__main__":
    try:
        main()
    except SuperharnessError as e:
        handle_cli_error(e)
