"""heartbeat command — run proactive checks for the superharness watcher."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import yaml


def _read_state(state_file: str) -> dict:
    p = Path(state_file)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"heartbeat: could not read state file {state_file}: {e}", file=sys.stderr)
        return {}


def _write_state(state_file: str, state: dict) -> None:
    Path(state_file).write_text(yaml.dump(state, default_flow_style=False), encoding="utf-8")


def _run_idle_warning(project_dir: str, now_epoch: float) -> None:
    ledger = os.path.join(project_dir, ".superharness", "ledger.md")
    if not os.path.isfile(ledger):
        print("heartbeat: idle-warning: no ledger.md found")
        return
    mtime = os.path.getmtime(ledger)
    age = int(now_epoch - mtime)
    threshold = 48 * 3600
    if age > threshold:
        print(f"heartbeat: idle-warning: no ledger activity in {age // 3600}h (threshold: 48h)")


def _run_stale_recovery(project_dir: str) -> None:
    from superharness.commands.inbox_recover import main as recover_main
    recover_main(["--project", project_dir, "--timeout-minutes", "30", "--action", "stale"])


def _run_hygiene_check(project_dir: str) -> None:
    from superharness.engine.validate import run_validate
    run_validate(project_dir)


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="heartbeat",
        description="Run proactive checks defined in .superharness/heartbeat.yaml.")
    p.add_argument("-p", "--project", required=True)
    opts = p.parse_args(argv)

    sh_dir = Path(opts.project) / ".superharness"
    hb_config = sh_dir / "heartbeat.yaml"
    hb_state_file = str(sh_dir / "heartbeat-state.yaml")

    if not hb_config.is_file():
        sys.exit(0)  # optional feature, silently exit

    try:
        cfg = yaml.safe_load(hb_config.read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}

    checks = cfg.get("checks") or []
    now_epoch = time.time()

    state = _read_state(hb_state_file)
    state_updated = False

    for check in checks:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id", ""))
        enabled = check.get("enabled", False)
        interval_minutes = int(check.get("interval_minutes", 0) or 0)

        if not check_id or not enabled:
            continue

        last_run = 0
        if check_id in state and isinstance(state[check_id], dict):
            last_run = int(state[check_id].get("last_run", 0) or 0)

        interval_seconds = interval_minutes * 60
        elapsed = now_epoch - last_run
        if elapsed < interval_seconds:
            continue

        print(f"heartbeat: running check '{check_id}'")

        try:
            if check_id == "stale-recovery":
                _run_stale_recovery(opts.project)
            elif check_id == "idle-warning":
                _run_idle_warning(opts.project, now_epoch)
            elif check_id == "hygiene-check":
                _run_hygiene_check(opts.project)
            else:
                print(f"heartbeat: unknown check id '{check_id}', skipping")
                continue  # do NOT update state for unknown IDs

            # Update state
            if check_id not in state or not isinstance(state[check_id], dict):
                state[check_id] = {}
            state[check_id]["last_run"] = int(now_epoch)
            state_updated = True

        except Exception as e:
            print(f"heartbeat: check '{check_id}' failed: {e}")

    if state_updated:
        _write_state(hb_state_file, state)


if __name__ == "__main__":
    main()
