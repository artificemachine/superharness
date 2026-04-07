"""status command — show watcher and inbox health summary."""
from __future__ import annotations

import glob
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone

from superharness.engine.yaml_helpers import safe_load


def _watcher_status_darwin(project_dir: str) -> tuple[str, str]:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(project_dir))
    label = f"com.superharness.inbox.{slug}"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    r = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return "bad", "not loaded"
    out = r.stdout
    state = next((line.split("=", 1)[1].strip() for line in out.splitlines() if "state =" in line), "")
    last_exit = next((line.split("=", 1)[1].strip() for line in out.splitlines() if "last exit code =" in line), "")
    run_interval = next((re.search(r"run interval = (\d+)", line) for line in out.splitlines() if "run interval" in line), None)
    interval_s = run_interval.group(1) if run_interval else "unknown"
    if state in ("running", "active"):
        return "ok", f"loaded state={state} interval={interval_s}s exit={last_exit or 'unknown'}"
    if state == "not running" and last_exit in ("0", "(never exited)"):
        return "ok", f"loaded idle interval={interval_s}s"
    return "warn", f"loaded state={state or 'unknown'} exit={last_exit or 'unknown'}"


def _watcher_status_linux(project_dir: str) -> tuple[str, str]:
    if not subprocess.run(["which", "systemctl"], capture_output=True).returncode == 0:
        return "warn", "no launchd/systemd watcher check available on Linux"
    unit = f"superharness-watcher@{os.path.basename(project_dir)}.service"
    r = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
    active = r.stdout.strip()
    if active == "active":
        return "ok", f"systemd unit active ({unit})"
    if active:
        return "warn", f"systemd unit {unit} is {active}"
    return "warn", f"systemd unit {unit} not found"


def _watcher_project(project_dir: str) -> str:
    watcher_cfg = os.path.join(project_dir, ".superharness", "watcher.yaml")
    if not os.path.isfile(watcher_cfg):
        return project_dir
    data = safe_load(watcher_cfg, dict) or {}
    candidate = os.path.realpath(str(data.get("watcher_project", "") or ""))
    if candidate and os.path.isdir(os.path.join(candidate, ".superharness")):
        return candidate
    return project_dir


def _heartbeat_status(project_dir: str, harness_dir: str) -> tuple[str, str]:
    watcher_project = _watcher_project(project_dir)
    hb_project = watcher_project if watcher_project != project_dir else project_dir
    via_worker = hb_project != project_dir
    stale_seconds = 120

    # Prefer structured heartbeat contract v1 when available
    try:
        from superharness.engine.heartbeat_contract import (
            heartbeat_path,
            read_heartbeat,
            age_seconds as hb_age_seconds,
        )
        structured_path = heartbeat_path(hb_project, "watcher")
        if os.path.isfile(structured_path):
            hb = read_heartbeat(structured_path)
            if hb is not None:
                age = hb_age_seconds(hb)
                if age < 0:
                    return "missing", "invalid heartbeat timestamp"
                age_min = age // 60
                suffix = " (worker project)" if via_worker else ""
                if age >= stale_seconds:
                    return "stale", f"last heartbeat {age_min}m ago{suffix}"
                return "ok", f"last heartbeat {age}s ago{suffix}"
    except Exception:
        pass

    # Fall back to legacy plain-timestamp file
    hb_file = os.path.join(hb_project, ".superharness", "watcher.heartbeat")
    if not os.path.isfile(hb_file):
        return "missing", "no heartbeat file"
    with open(hb_file) as f:
        hb_ts = f.readline().strip()
    if not hb_ts:
        return "missing", "empty heartbeat file"
    try:
        hb_dt = datetime.fromisoformat(hb_ts.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        age = int((now_dt - hb_dt).total_seconds())
        age_min = age // 60
        suffix = " (worker project)" if via_worker else ""
        if age >= stale_seconds:
            return "stale", f"last heartbeat {age_min}m ago{suffix}"
        return "ok", f"last heartbeat {age}s ago{suffix}"
    except Exception:
        return "missing", "invalid heartbeat timestamp"


def _inbox_stats(inbox_file: str, handoff_dir: str, discussions_dir: str, retry_threshold: int) -> dict:
    active_statuses = {"pending", "launched", "running", "stale", "failed", "paused", "stopped"}
    counts: dict = {}
    retry_high = 0
    retry_high_ids: list = []

    if os.path.isfile(inbox_file):
        items = safe_load(inbox_file, list) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            st = str(item.get("status", ""))
            if st:
                counts[st] = counts.get(st, 0) + 1
            if st in active_statuses:
                rc = int(item.get("retry_count") or 0)
                if rc >= retry_threshold:
                    retry_high += 1
                    iid = str(item.get("id", ""))
                    if iid:
                        retry_high_ids.append(iid)

    approvals_pending = 0
    if os.path.isdir(handoff_dir):
        for path in sorted(glob.glob(os.path.join(handoff_dir, "*.yaml"))):
            try:
                y = safe_load(path, dict)
                status = str(y.get("status", ""))
                gate = y.get("approval_gate")
                required = isinstance(gate, dict) and gate.get("required") is True
                approved = isinstance(gate, dict) and gate.get("approved_by_user") is True
                if status == "pending_user_approval" or (required and not approved):
                    approvals_pending += 1
            except Exception:
                continue

    discussion_counts: dict = {}
    if os.path.isdir(discussions_dir):
        for path in sorted(glob.glob(os.path.join(discussions_dir, "*/state.yaml"))):
            try:
                y = safe_load(path, dict)
                st = str(y.get("status", ""))
                if st:
                    discussion_counts[st] = discussion_counts.get(st, 0) + 1
            except Exception:
                continue

    return {
        "counts": counts,
        "retry_high": retry_high,
        "retry_high_ids": retry_high_ids,
        "approvals_pending": approvals_pending,
        "discussion_counts": discussion_counts,
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="status")
    p.add_argument("-p", "--project", default=os.getcwd())
    p.add_argument("--retry-threshold", type=int, default=3, dest="retry_threshold")
    p.add_argument("--check", action="store_true")
    opts = p.parse_args(argv)

    if opts.retry_threshold <= 0:
        sys.exit("--retry-threshold must be a positive integer")

    project_dir = os.path.realpath(opts.project)
    if not os.path.isdir(project_dir):
        sys.exit(f"Project directory does not exist: {opts.project}")

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        sys.exit(f"Missing .superharness in project: {project_dir}")

    inbox_file = os.path.join(harness_dir, "inbox.yaml")
    handoff_dir = os.path.join(harness_dir, "handoffs")
    discussions_dir = os.path.join(harness_dir, "discussions")

    sys_platform = platform.system()
    if sys_platform == "Darwin":
        watcher_level, watcher_msg = _watcher_status_darwin(project_dir)
    elif sys_platform == "Linux":
        watcher_level, watcher_msg = _watcher_status_linux(project_dir)
    else:
        watcher_level = "warn"
        watcher_msg = f"no watcher check available on {sys_platform}"

    heartbeat_status, heartbeat_detail = _heartbeat_status(project_dir, harness_dir)

    # Heartbeat overrides watcher status: if heartbeat is fresh, watcher is running
    # (foreground or daemon — doesn't matter)
    if watcher_level == "bad" and heartbeat_status == "ok":
        watcher_level = "ok"
        watcher_msg = f"foreground ({heartbeat_detail})"
    elif watcher_level == "bad" and heartbeat_status == "stale":
        watcher_msg = f"not loaded, heartbeat stale ({heartbeat_detail})"
    elif watcher_level == "bad" and heartbeat_status == "missing":
        watcher_msg = "not running (no heartbeat)"

    stats = _inbox_stats(inbox_file, handoff_dir, discussions_dir, opts.retry_threshold)
    counts = stats["counts"]

    def c(k: str) -> int:
        return counts.get(k, 0)

    retry_ids_str = ",".join(stats["retry_high_ids"][:5]) or "none"
    dc = stats["discussion_counts"]

    print("superharness status")
    print(f"project: {project_dir}")
    print(f"watcher: level={watcher_level} {watcher_msg}")
    print(f"heartbeat: {heartbeat_status} ({heartbeat_detail})")
    print(f"inbox: pending={c('pending')} launched={c('launched')} running={c('running')} "
          f"paused={c('paused')} done={c('done')} failed={c('failed')} "
          f"stale={c('stale')} stopped={c('stopped')}")
    print(f"retry-alert: threshold={opts.retry_threshold} high={stats['retry_high']} ids={retry_ids_str}")
    print(f"approvals: pending={stats['approvals_pending']}")
    print(f"discussions: active={dc.get('active', 0)} consensus={dc.get('consensus', 0)} "
          f"failed_participant={dc.get('failed_participant', 0)} "
          f"deadlock={dc.get('deadlock', 0)} closed={dc.get('closed', 0)}")

    issues = 0
    if watcher_level == "bad":
        issues += 1
    if heartbeat_status in ("stale", "missing"):
        issues += 1
    if c("failed") > 0 or c("stale") > 0 or stats["retry_high"] > 0:
        issues += 1

    print(f"summary: issues={issues}")
    if opts.check and issues > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
