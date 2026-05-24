"""shux archive-yaml / shux export yaml — YAML archival commands (Iter 10).

archive-yaml: rename YAML state files to .yaml.bak-<ts>, disable dual-write.
export yaml:  generate a snapshot YAML from current SQLite state (compat shim).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


_YAML_STATE_FILES = [
    ".superharness/inbox.yaml",
    ".superharness/contract.yaml",
    ".superharness/failures.yaml",
    ".superharness/decisions.yaml",
]
_YAML_HANDOFF_GLOB = ".superharness/handoffs/*.yaml"


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _inbox_row_to_yaml_shape(row: dict) -> dict:
    """Translate SQLite InboxRow field names to YAML inbox item field names.

    Caller must pass a plain dict (e.g. from dataclasses.asdict()), not a dataclass.
    """
    out = dict(row)
    out["task"] = out.pop("task_id", out.get("task", ""))
    out["to"] = out.pop("target_agent", out.get("to", ""))
    out["project"] = out.pop("project_path", out.get("project"))
    return out


def archive_yaml(project_dir: str, *, dry_run: bool = False) -> int:
    """Rename YAML state files to .bak-<ts>, drain the sync queue.

    After this runs:
    - YAML files are read-only archives named *.yaml.bak-<ts>
    - SQLite is the sole active backend
    - STATE_BACKEND=sqlite_only is written to profile.yaml

    Returns 0 on success, 1 on failure.
    """
    import glob

    tag = _now_tag()
    archived: list[str] = []
    errors: list[str] = []

    # yaml_sync queue removed — no-op stub deleted in Phase 4

    # Archive named state files
    for rel in _YAML_STATE_FILES:
        path = os.path.join(project_dir, rel)
        if not os.path.exists(path):
            continue
        bak = f"{path}.bak-{tag}"
        if dry_run:
            print(f"  [dry-run] would rename {path} → {bak}")
        else:
            try:
                os.rename(path, bak)
                archived.append(rel)
                print(f"  archived {rel} → {os.path.basename(bak)}")
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
                print(f"  error archiving {rel}: {exc}", file=sys.stderr)

    # Archive handoff YAML files
    handoff_pattern = os.path.join(project_dir, _YAML_HANDOFF_GLOB)
    for path in sorted(glob.glob(handoff_pattern)):
        bak = f"{path}.bak-{tag}"
        if dry_run:
            print(f"  [dry-run] would rename {os.path.relpath(path, project_dir)} → {os.path.basename(bak)}")
        else:
            try:
                os.rename(path, bak)
                archived.append(os.path.relpath(path, project_dir))
            except OSError as exc:
                errors.append(f"{path}: {exc}")

    if not dry_run and not errors:
        # Set STATE_BACKEND=sqlite_only in profile.yaml
        _set_profile_backend(project_dir, "sqlite_only")
        print(f"archive-yaml: complete — {len(archived)} file(s) archived, STATE_BACKEND=sqlite_only set")

    if errors:
        print(f"archive-yaml: {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    return 0


def export_yaml(project_dir: str, *, out_dir: str | None = None) -> int:
    """Generate snapshot YAML files from current SQLite state.

    Compatibility shim for external scripts that still read inbox.yaml /
    contract.yaml. Does NOT write the canonical paths — writes to out_dir
    (default: .superharness/export/).

    Returns 0 on success, 1 on failure.
    """
    import yaml

    if out_dir is None:
        out_dir = os.path.join(project_dir, ".superharness", "export")
    os.makedirs(out_dir, exist_ok=True)

    try:
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao, tasks_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            raw_inbox = [asdict(r) for r in inbox_dao.get_all(conn)]
            inbox_rows = [_inbox_row_to_yaml_shape(r) for r in raw_inbox]
            task_rows = [asdict(r) for r in tasks_dao.get_all(conn)]
        finally:
            conn.close()
    except Exception as exc:
        print(f"export yaml: failed to read from SQLite: {exc}", file=sys.stderr)
        return 1

    inbox_path = os.path.join(out_dir, "inbox.yaml")
    contract_path = os.path.join(out_dir, "contract.yaml")

    try:
        with open(inbox_path, "w", encoding="utf-8") as f:
            f.write("# Delegation inbox (exported from SQLite)\n")
            f.write("# status: pending|launched|running|done|failed|stale\n")
            yaml.dump(inbox_rows, f, default_flow_style=False, allow_unicode=True)
        print(f"export yaml: inbox → {inbox_path} ({len(inbox_rows)} items)")
    except OSError as exc:
        print(f"export yaml: failed to write inbox: {exc}", file=sys.stderr)
        return 1

    try:
        with open(contract_path, "w", encoding="utf-8") as f:
            yaml.dump({"tasks": task_rows}, f, default_flow_style=False, allow_unicode=True)
        print(f"export yaml: contract → {contract_path} ({len(task_rows)} tasks)")
    except OSError as exc:
        print(f"export yaml: failed to write contract: {exc}", file=sys.stderr)
        return 1

    return 0


def _set_profile_backend(project_dir: str, backend: str) -> None:
    import yaml
    profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.exists(profile_path):
        return
    try:
        with open(profile_path, encoding="utf-8") as f:
            profile = yaml.safe_load(f) or {}
        profile["state_backend"] = backend
        with open(profile_path, "w", encoding="utf-8") as f:
            yaml.dump(profile, f, default_flow_style=False, allow_unicode=True)
    except Exception as exc:
        print(f"archive-yaml: warning: could not update profile.yaml: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="archive-yaml",
        description="Archive YAML state files or export a compat snapshot from SQLite",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    arc = sub.add_parser("archive", help="Archive YAML state files (one-shot, irreversible without restore)")
    arc.add_argument("--project", "-p", default=".", help="Project directory")
    arc.add_argument("--dry-run", action="store_true", help="Show what would be archived without doing it")

    exp = sub.add_parser("export", help="Export a YAML snapshot from SQLite (compat shim)")
    exp.add_argument("--project", "-p", default=".", help="Project directory")
    exp.add_argument("--out-dir", help="Output directory (default: .superharness/export/)")

    args = parser.parse_args(argv)
    project_dir = os.path.abspath(args.project)

    if args.action == "archive":
        sys.exit(archive_yaml(project_dir, dry_run=args.dry_run))
    elif args.action == "export":
        sys.exit(export_yaml(project_dir, out_dir=getattr(args, "out_dir", None)))


if __name__ == "__main__":
    main()
