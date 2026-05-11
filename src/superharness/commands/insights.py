"""shux insights — task/dispatch/agent breakdown from SQLite."""
from __future__ import annotations

import json
import os
import sys


def main(argv: list[str] | None = None) -> None:
    import argparse
    p = argparse.ArgumentParser(prog="insights", description="Show task and dispatch analytics")
    p.add_argument("--project", "-p", default=os.getcwd())
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    opts = p.parse_args(argv)

    from superharness.engine.insights import get_insights
    data = get_insights(os.path.realpath(opts.project))

    if opts.json:
        print(json.dumps(data, indent=2))
        return

    _print_insights(data)


def _print_insights(data: dict) -> None:
    tasks = data.get("tasks", {})
    agents = data.get("agents", {})
    dispatch = data.get("dispatch", {})
    failures = data.get("failures", [])

    print("── tasks ──────────────────────────────")
    if tasks:
        for status, count in sorted(tasks.items(), key=lambda x: -x[1]):
            print(f"  {status:<20} {count}")
    else:
        print("  no data")

    print("\n── agents ─────────────────────────────")
    if agents:
        for agent, counts in sorted(agents.items()):
            done = counts.get("done", 0)
            failed = counts.get("failed", 0)
            archived = counts.get("archived", 0)
            print(f"  {agent:<20} done={done}  failed={failed}  archived={archived}")
    else:
        print("  no data")

    print("\n── dispatch ───────────────────────────")
    launched = dispatch.get("launched", 0)
    failed_d = dispatch.get("failed", 0)
    total = launched + failed_d
    rate = f"{launched/total*100:.0f}%" if total else "n/a"
    print(f"  launched  {launched}   failed  {failed_d}   success rate  {rate}")

    print("\n── top failures ───────────────────────")
    if failures:
        for f in failures[:5]:
            tid = f.get("task_id", "?")
            agent = f.get("target_agent", "?")
            retries = f.get("retry_count", 0)
            reason = (f.get("failed_reason") or "")[:50]
            print(f"  {tid:<35} {agent:<12} retries={retries}  {reason}")
    else:
        print("  no failures recorded")

    print("\n── summarizer ─────────────────────────")
    summarizer = data.get("summarizer", [])
    if summarizer:
        for row in summarizer:
            provider = row.get("provider", "?")
            calls = row.get("calls", 0)
            successes = row.get("successes", 0)
            failures = row.get("failures", 0)
            in_tok = row.get("input_tokens", 0)
            out_tok = row.get("output_tokens", 0)
            tok = f"in={in_tok} out={out_tok}" if (in_tok or out_tok) else "tokens=n/a"
            print(f"  {provider:<14} calls={calls}  ok={successes}  fail={failures}  {tok}")
    else:
        print("  no summarizer calls recorded")


if __name__ == "__main__":
    main()
