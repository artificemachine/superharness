#!/usr/bin/env bash
# verify-l5-loop.sh — PLAN-superharness-L5.md iteration 6.
#
# Live G5c verification: injects a real 2-failure cluster through the real
# inbox/failure path in a throwaway sandbox project, clears the reinforce
# cooldown, invokes the real _reinforce_loop() against the real local fleet
# (Ollama), and prints the resulting reinforce_analysis trace event — a real
# fleet classification of a real (injected) fault, not fabricated data.
#
# Usage:
#   bash scripts/verify-l5-loop.sh            # full live run (needs Ollama)
#   bash scripts/verify-l5-loop.sh --dry-run   # build + seed only, no fleet call
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

mkdir -p "$SANDBOX/.superharness"

echo "Sandbox: $SANDBOX"
echo "Seeding a real 2-failure cluster for 'codex-cli'..."

PYTHONPATH="$REPO_ROOT/src" python3 - "$SANDBOX" "$DRY_RUN" <<'PYEOF'
import sys, json
sandbox, dry_run = sys.argv[1], sys.argv[2] == "1"

from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao, tasks_dao
from datetime import datetime, timezone

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
conn = get_connection(sandbox)
init_db(conn)

for i in range(2):
    task_id = f"verify-l5.{i}"
    tasks_dao.upsert(conn, tasks_dao.TaskRow(
        id=task_id, title="verify-l5 seeded task", owner="codex-cli",
        status="in_progress", effort="medium", project_path=sandbox,
        development_method="tdd", acceptance_criteria=["n/a"], test_types=["unit"],
        out_of_scope=[], definition_of_done=[], context="ctx", tdd=None,
        version=1, created_at=now, blocked_by=[], parent_id=None,
    ))
    conn.commit()
    item_id = f"verify-l5-item-{i}"
    inbox_dao.enqueue(
        conn, id=item_id, task_id=task_id, target_agent="codex-cli",
        priority=2, max_retries=3, now=now,
    )
    conn.execute(
        "UPDATE inbox SET status='failed', failed_reason=?, failed_at=? WHERE id=?",
        ("ModuleNotFoundError: No module named 'yaml' (verify-l5 injected fault)", now, item_id),
    )
conn.commit()
conn.close()
print(f"Seeded 2 failed inbox rows for 'codex-cli' at {now}")

if dry_run:
    print("--dry-run: stopping before the fleet call.")
    sys.exit(0)

from superharness.commands import inbox_watch
inbox_watch._reinforce_loop(sandbox)

trace_path = f"{sandbox}/.superharness/trace.jsonl"
events = []
try:
    with open(trace_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            evt = json.loads(line)
            if evt.get("type") == "reinforce_analysis":
                events.append(evt)
except FileNotFoundError:
    pass

if not events:
    print("FAIL: no reinforce_analysis event was written. Fleet may be unreachable — "
          "check `shux doctor` fleet health.", file=sys.stderr)
    sys.exit(1)

print()
print("=== reinforce_analysis event (G5c evidence) ===")
print(json.dumps(events[-1], indent=2))
PYEOF
