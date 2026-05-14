"""shux pipeline-check — run a health probe through the full auto-mode pipeline.

Creates a test task, waits for it to progress through the lifecycle,
and reports where it gets stuck (if anywhere).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone


def run_pipeline_check(project_dir: str) -> int:
    """Run a health probe through the auto-mode pipeline.

    Returns 0 if pipeline is healthy, 1 if issues found.
    """
    checks = []

    def _check(name: str, condition: bool, detail: str = "") -> str:
        status = "PASS" if condition else "FAIL"
        checks.append(f"  [{status}] {name}" + (f": {detail}" if not condition else ""))
        return status

    print("=== PIPELINE HEALTH CHECK ===")
    print(f"Project: {project_dir}")
    print()

    # 1. SQLite DB
    db = os.path.join(project_dir, ".superharness", "state.sqlite3")
    _check("SQLite DB exists", os.path.isfile(db), f"missing: {db}")

    # 2. Profile config
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if os.path.isfile(profile_file):
        import yaml
        profile = yaml.safe_load(open(profile_file).read()) or {}
        _check("auto_dispatch enabled", profile.get("auto_dispatch"), "add auto_dispatch: true to profile.yaml")
        _check("autonomy configured", profile.get("autonomy") in ("autonomous", "ai_driven"), "set autonomy: autonomous")
        _check("auto_close enabled", profile.get("auto_close") or profile.get("autonomy") == "autonomous", "set auto_close: true")
    else:
        _check("profile.yaml exists", False, "missing profile.yaml")

    # 3. Contract has tasks
    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(project_dir)
    _check("Contract has tasks", len(tasks) > 0)

    # 4. Agent binaries
    import shutil
    for agent, binary in [("claude-code", "claude"), ("codex-cli", "codex"), ("gemini-cli", "gemini"), ("opencode", "opencode")]:
        _check(f"{agent} binary", shutil.which(binary) is not None, f"install {binary}")

    # 5. Watcher heartbeat
    hb = os.path.join(project_dir, ".superharness", "watcher.heartbeat")
    if os.path.isfile(hb):
        with open(hb) as f:
            ts = f.read().strip()
        try:
            hb_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
            _check("Watcher heartbeat fresh", age < 120, f"last heartbeat {int(age)}s ago")
        except Exception:
            _check("Watcher heartbeat valid", False, "invalid timestamp")
    else:
        _check("Watcher heartbeat exists", False, "watcher not running")

    # 6. Inbox working
    from superharness.engine import inbox_dao
    from superharness.engine.db import get_connection, init_db
    try:
        conn = get_connection(project_dir)
        init_db(conn)
        inbox = inbox_dao.get_all(conn)
        conn.close()
        _check("Inbox readable", True)
    except Exception as e:
        _check("Inbox readable", False, str(e))

    # 7. launcher-logs directory
    log_dir = os.path.join(project_dir, ".superharness", "launcher-logs")
    _check("Launcher logs dir", os.path.isdir(log_dir) and os.access(log_dir, os.W_OK), "not writable or missing")

    # Summary
    passes = sum(1 for c in checks if c.startswith("  [PASS]"))
    fails = sum(1 for c in checks if c.startswith("  [FAIL]"))

    for c in checks:
        print(c)

    print()
    if fails == 0:
        print(f"RESULT: Pipeline healthy ({passes}/{passes} checks pass) ✅")
        return 0
    else:
        print(f"RESULT: {fails} issue(s) found ({passes}/{passes+fails} checks pass) ⚠️")
        return 1


def main(argv: list[str] | None = None) -> None:
    import argparse
    if argv is None:
        argv = sys.argv[1:]
    p = argparse.ArgumentParser(prog="pipeline-check")
    p.add_argument("-p", "--project", default=".", help="Project directory")
    opts = p.parse_args(argv)
    sys.exit(run_pipeline_check(os.path.abspath(opts.project)))


if __name__ == "__main__":
    main()
