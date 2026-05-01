#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-deadline-check.sh --project DIR

Options:
  -p, --project DIR   Project directory containing .superharness/ (required)
  -h, --help          Show this help message and exit

For each launched inbox item whose contract task has deadline_minutes set:
  - if elapsed time since launched_at exceeds deadline_minutes:
    - mark the inbox item failed (deadline_exceeded)
    - write a handoff documenting why it was stopped
    - re-enqueue for the other owner (claude-code <-> codex-cli)
    - append to ledger
USAGE
}

PROJECT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }

INBOX_FILE="$PROJECT_DIR/.superharness/inbox.yaml"
CONTRACT_FILE="$PROJECT_DIR/.superharness/contract.yaml"
LEDGER_FILE="$PROJECT_DIR/.superharness/ledger.md"
HANDOFFS_DIR="$PROJECT_DIR/.superharness/handoffs"

[ -f "$INBOX_FILE" ]    || { echo "result=ok exceeded=0 (no inbox)"; exit 0; }
[ -f "$CONTRACT_FILE" ] || { echo "result=ok exceeded=0 (no contract)"; exit 0; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON3="${SUPERHARNESS_PYTHON:-python3}"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Set PYTHONPATH so Python modules can be found
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

NOW="$(date -u +%FT%TZ)"
NOW_EPOCH="$(date -u +%s)"

PY_HELPER="$(mktemp "${TMPDIR:-/tmp}/superharness-deadline-XXXXXX")"
trap 'rm -f "$PY_HELPER"' EXIT

cat > "$PY_HELPER" << 'PYTHON'
import json, sys
from datetime import datetime, timezone

json_file  = sys.argv[1]
now_epoch  = int(sys.argv[2])

with open(json_file) as f:
    items = json.load(f)
for item in items:
    launched_at = str(item.get("launched_at") or "")
    if not launched_at:
        continue
    try:
        ts = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
        elapsed = (now_epoch - int(ts.timestamp())) // 60
    except (ValueError, OSError):
        continue
    print("\t".join([
        item["id"], item["task"], item["to"], item["project"],
        str(item.get("priority", "")), str(elapsed), launched_at
    ]))
PYTHON

JSON_TMP="$(mktemp "${TMPDIR:-/tmp}/superharness-launched-XXXXXX")"
trap 'rm -f "$PY_HELPER" "$JSON_TMP"' EXIT

"$PYTHON3" -m superharness.engine.inbox list_launched --file "$INBOX_FILE" > "$JSON_TMP"

# Handle empty output — inbox.yaml may be stale/empty in sqlite_only mode (v1.43+)
if [ ! -s "$JSON_TMP" ]; then
  echo "result=ok exceeded=0 (no launched items)"
  exit 0
fi

LAUNCHED_LINES="$("$PYTHON3" "$PY_HELPER" "$JSON_TMP" "$NOW_EPOCH")"

exceeded_count=0

while IFS=$'\t' read -r item_id task_id owner project priority elapsed_minutes launched_at; do
  [ -n "$item_id" ] || continue

  # Look up deadline_minutes from contract.
  deadline_minutes="$("$PYTHON3" -m superharness.engine.contract task_deadline_minutes \
    --file "$CONTRACT_FILE" --task "$task_id" 2>/dev/null || true)"

  [ -n "$deadline_minutes" ] || continue

  # Skip if deadline not yet exceeded.
  if [ "$elapsed_minutes" -lt "$deadline_minutes" ] 2>/dev/null; then
    continue
  fi

  # Determine the other owner.
  case "$owner" in
    claude-code) new_owner="codex-cli" ;;
    codex-cli)   new_owner="claude-code" ;;
    *)
      echo "deadline-check: unknown owner '$owner' for task $task_id, skipping" >&2
      continue
      ;;
  esac

  echo "Deadline exceeded: task=$task_id owner=$owner elapsed=${elapsed_minutes}m deadline=${deadline_minutes}m -> reassigning to $new_owner"

  "$PYTHON3" -m superharness.engine.inbox deadline_fail \
    --file "$INBOX_FILE" \
    --id "$item_id" \
    --now "$NOW" \
    --reason "deadline_exceeded_after_${elapsed_minutes}m"

  bash "$SCRIPT_DIR/task.sh" status \
    --project "$project" \
    --id "$task_id" \
    --status failed \
    --actor "$owner" \
    --reason "deadline_exceeded_after_${elapsed_minutes}m" 2>/dev/null || true

  contract_id="$("$PYTHON3" -m superharness.engine.contract contract_id --file "$CONTRACT_FILE" 2>/dev/null || echo "unknown")"

  mkdir -p "$HANDOFFS_DIR"
  HANDOFF_FILE="$HANDOFFS_DIR/${NOW:0:10}-deadline-${task_id}.yaml"
  cat > "$HANDOFF_FILE" << HANDOFF
id: ${NOW:0:10}-deadline-${task_id}
contract_id: ${contract_id}
task: ${task_id}
from: ${owner}
to: ${new_owner}
status: deadline_exceeded
summary: "Task ${task_id} did not finish within ${deadline_minutes} minutes (elapsed: ${elapsed_minutes}m). Stopped and reassigned."
scope:
  - "Deadline enforcement"
commands: []
acceptance:
  - "New owner (${new_owner}) must complete task ${task_id}."
  - "Document why the previous attempt by ${owner} did not finish in time."
risks:
  - "Previous attempt by ${owner} left the task incomplete. Review partial work before continuing."
artifacts: []
deadline_context:
  original_owner: "${owner}"
  new_owner: "${new_owner}"
  launched_at: "${launched_at}"
  deadline_minutes: ${deadline_minutes}
  elapsed_minutes: ${elapsed_minutes}
  stopped_at: "${NOW}"
HANDOFF

  # Re-enqueue for the other owner. --force-reassign is required because the
  # contract `owner` still names the agent that missed the deadline; this is a
  # controlled handoff initiated by the deadline checker, not an accidental
  # cross-agent dispatch.
  "$PYTHON3" -m superharness.commands.inbox_enqueue \
    --project "$project" \
    --to "$new_owner" \
    --task "$task_id" \
    --priority "$priority" \
    --force-reassign

  # Append to ledger.
  if [ -f "$LEDGER_FILE" ]; then
    printf -- '- %s — deadline-exceeded — task %s — %s did not finish within %sm (elapsed: %sm), reassigned to %s\n' \
      "$NOW" "$task_id" "$owner" "$deadline_minutes" "$elapsed_minutes" "$new_owner" \
      >> "$LEDGER_FILE"
  fi

  exceeded_count=$((exceeded_count + 1))

done <<< "${LAUNCHED_LINES:-}"

echo "deadline-check: result=ok exceeded=${exceeded_count}"
