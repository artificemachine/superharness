#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-enqueue.sh --project DIR --to claude-code|codex-cli --task TASK_ID [--id ID]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --to TARGET     Delegation target: claude-code or codex-cli
  -t, --task TASK_ID  Task id from contract/handoff
      --id ID         Optional inbox item id (default: UTC timestamp + task)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
TARGET=""
TASK_ID=""
ITEM_ID=""

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET="$2"
      shift 2
      ;;
    -t|--task)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
      shift 2
      ;;
    --id)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      ITEM_ID="$2"
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
[ -n "$TARGET" ] || { echo "--to is required" >&2; exit 2; }
[ -n "$TASK_ID" ] || { echo "--task is required" >&2; exit 2; }

case "$TARGET" in
  claude-code|codex-cli) ;;
  *)
    echo "--to must be claude-code or codex-cli" >&2
    exit 2
    ;;
esac

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi

HARNESS_DIR="$PROJECT_DIR/.superharness"
if [ ! -d "$HARNESS_DIR" ]; then
  echo "Missing .superharness directory: $HARNESS_DIR" >&2
  exit 1
fi

INBOX_FILE="$HARNESS_DIR/inbox.yaml"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
if [ -z "$ITEM_ID" ]; then
  ITEM_ID="$(date -u +%Y%m%dT%H%M%SZ)-${TASK_ID}"
fi

# Validate task project_path mapping when available in contract.
if [ -f "$CONTRACT_FILE" ]; then
  TASK_PATH="$(awk -v task="$TASK_ID" '
    BEGIN { in_task=0; found=0; path="" }
    /^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ {
      if (in_task == 1) { exit }
      id = $0
      sub(/^[[:space:]]*-[[:space:]]*id:[[:space:]]*/, "", id)
      gsub(/"/, "", id)
      if (id == task) { in_task=1; found=1 }
      next
    }
    in_task == 1 && /^[[:space:]]*project_path:[[:space:]]*/ {
      path = $0
      sub(/^[[:space:]]*project_path:[[:space:]]*/, "", path)
      gsub(/"/, "", path)
      print path
      exit
    }
    in_task == 1 && /^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ { exit }
    END {
      if (found == 0) {
        # Task id missing in contract; allow enqueue but note upstream.
      }
    }
  ' "$CONTRACT_FILE")"

  if rg -q "^[[:space:]]*-[[:space:]]*id:[[:space:]]*\"?${TASK_ID}\"?[[:space:]]*$" "$CONTRACT_FILE"; then
    if [ -z "$TASK_PATH" ]; then
      echo "Task '$TASK_ID' is missing project_path in $CONTRACT_FILE" >&2
      echo "Add: project_path: \"$PROJECT_DIR\"" >&2
      exit 1
    fi
    if [ "$TASK_PATH" != "$PROJECT_DIR" ]; then
      echo "Task '$TASK_ID' project_path mismatch." >&2
      echo "  contract: $TASK_PATH" >&2
      echo "  expected: $PROJECT_DIR" >&2
      exit 1
    fi
  fi
fi

if [ ! -f "$INBOX_FILE" ]; then
  printf '# Delegation inbox\n# status: pending|prepared|launched|done|failed\n' > "$INBOX_FILE"
fi

{
  echo ""
  echo "- id: $ITEM_ID"
  echo "  to: $TARGET"
  echo "  task: $TASK_ID"
  echo "  project: $PROJECT_DIR"
  echo "  status: pending"
  echo "  created_at: $(date -u +%FT%TZ)"
} >> "$INBOX_FILE"

echo "Enqueued inbox item:"
echo "  id: $ITEM_ID"
echo "  to: $TARGET"
echo "  task: $TASK_ID"
echo "  file: $INBOX_FILE"
