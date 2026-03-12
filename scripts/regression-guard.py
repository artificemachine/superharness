#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass


@dataclass
class CommitRow:
    sha: str
    message: str


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"command failed: {' '.join(args)}")
    return proc.stdout


def _git_log(limit: int, grep_terms: list[str]) -> list[CommitRow]:
    cmd = ["git", "log", "--oneline", f"-n{limit}"]
    for term in grep_terms:
        cmd.extend(["--grep", term])
    rows = []
    for line in _run(cmd).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        rows.append(CommitRow(parts[0], parts[1]))
    return rows


def _recent_shas(limit: int) -> list[str]:
    out = _run(["git", "log", "--oneline", f"-n{limit}"])
    result: list[str] = []
    for line in out.splitlines():
        parts = line.strip().split(" ", 1)
        if parts and parts[0]:
            result.append(parts[0])
    return result


def _has_test_changes(sha: str) -> bool:
    files = _run(["git", "show", "--name-only", "--pretty=format:", "--no-renames", sha]).splitlines()
    for file in files:
        path = file.strip()
        if not path:
            continue
        if path.startswith("tests/") or "/test_" in path:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Regression guard for fix/bug commits.")
    ap.add_argument("--limit", type=int, default=50, help="Number of recent fix/bug commits to inspect.")
    ap.add_argument("--scan-depth", type=int, default=80, help="Number of recent commits to map for nearby checks.")
    ap.add_argument("--window", type=int, default=3, help="Nearby commit window on each side.")
    ap.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = ap.parse_args()

    if args.limit <= 0 or args.scan_depth <= 0 or args.window < 0:
        raise SystemExit("limit/scan-depth must be > 0 and window must be >= 0")

    fix_rows = _git_log(args.limit, ["fix", "Fix", "bug", "Bug"])
    commit_order = _recent_shas(args.scan_depth)
    commit_index = {sha: i for i, sha in enumerate(commit_order)}

    flagged: list[dict] = []
    for row in fix_rows:
        own_test = _has_test_changes(row.sha)
        nearby_test = False
        idx = commit_index.get(row.sha)
        if idx is not None and not own_test:
            start = max(0, idx - args.window)
            end = min(len(commit_order), idx + args.window + 1)
            for i in range(start, end):
                sha = commit_order[i]
                if sha == row.sha:
                    continue
                if _has_test_changes(sha):
                    nearby_test = True
                    break
        if not (own_test or nearby_test):
            flagged.append(
                {
                    "sha": row.sha,
                    "message": row.message,
                    "reason": "no_tests_in_commit_or_nearby_window",
                }
            )

    payload = {
        "fix_commits": len(fix_rows),
        "without_test_changes": len(flagged),
        "window": args.window,
        "limit": args.limit,
        "scan_depth": args.scan_depth,
        "without_test_samples": flagged,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"fix_commits={payload['fix_commits']} "
            f"without_test_changes={payload['without_test_changes']} "
            f"window={payload['window']}"
        )
        for row in flagged:
            print(f"- {row['sha']} {row['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
