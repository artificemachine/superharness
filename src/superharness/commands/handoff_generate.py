"""handoff generate — create a structured handoff from task state."""
from __future__ import annotations

import os
import sys
import yaml


def main(argv: list[str] | None = None) -> None:
    import argparse
    p = argparse.ArgumentParser(prog="handoff-generate", description="Generate a structured handoff from task state")
    p.add_argument("--project", "-p", default=os.getcwd())
    p.add_argument("--task", "-t", required=True, help="Task ID")
    p.add_argument("--output", "-o", help="Output file path (default: .superharness/handoffs/<task-id>-auto.yaml)")
    opts = p.parse_args(argv)

    project_dir = os.path.realpath(opts.project)
    from superharness.engine.handoff_generator import generate_handoff
    handoff = generate_handoff(project_dir, opts.task)

    if "error" in handoff:
        print(handoff["error"], file=sys.stderr)
        sys.exit(1)

    if opts.output:
        path = opts.output
    else:
        handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
        os.makedirs(handoffs_dir, exist_ok=True)
        safe_id = opts.task.replace("/", "-")
        path = os.path.join(handoffs_dir, f"{safe_id}-auto.yaml")

    with open(path, "w") as f:
        yaml.dump(handoff, f, default_flow_style=False, sort_keys=False)

    print(f"Handoff written to {path}")
