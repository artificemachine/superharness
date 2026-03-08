#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-enqueue.sh --project DIR --to claude-code|codex-cli --task TASK_ID [--priority 1|2|3] [--id ID]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --to TARGET     Delegation target: claude-code or codex-cli
  -t, --task TASK_ID  Task id from contract/handoff
      --priority N    Priority 1-3 (1 highest, default: 2)
      --id ID         Optional inbox item id (default: UTC timestamp + task)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
TARGET=""
TASK_ID=""
ITEM_ID=""
PRIORITY=2

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
    --priority)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PRIORITY="$2"
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
case "$PRIORITY" in
  1|2|3) ;;
  *)
    echo "--priority must be 1, 2, or 3" >&2
    exit 2
    ;;
esac

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
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

HARNESS_DIR="$PROJECT_DIR/.superharness"
if [ ! -d "$HARNESS_DIR" ]; then
  echo "Missing .superharness directory: $HARNESS_DIR" >&2
  exit 1
fi

INBOX_FILE="$HARNESS_DIR/inbox.yaml"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX_YAML="$SCRIPT_DIR/inbox-yaml.rb"
[ -x "$INBOX_YAML" ] || { echo "Missing helper script: $INBOX_YAML" >&2; exit 1; }

if [ -z "$ITEM_ID" ]; then
  RAND_SUFFIX="$(od -An -N3 -tu1 /dev/urandom | tr -d ' \n')"
  ITEM_ID="$(date -u +%Y%m%dT%H%M%SZ)-${TASK_ID}-$$-${RAND_SUFFIX}"
fi

# Validate task project_path mapping when available in contract.
if [ -f "$CONTRACT_FILE" ]; then
  if ! TASK_EXISTS="$(ruby "$INBOX_YAML" contract_task_exists --file "$CONTRACT_FILE" --task "$TASK_ID")"; then
    echo "Failed to read task metadata from contract: $CONTRACT_FILE" >&2
    exit 1
  fi
  if ! TASK_PATH="$(ruby "$INBOX_YAML" contract_task_project_path --file "$CONTRACT_FILE" --task "$TASK_ID")"; then
    echo "Failed to read task project_path from contract: $CONTRACT_FILE" >&2
    exit 1
  fi

  # Missing task id in contract is allowed to support pre-contract queueing.
  if [ "$TASK_EXISTS" = "false" ]; then
    echo "Warning: task '$TASK_ID' not found in contract. Enqueuing anyway." >&2
  fi
  if [ "$TASK_EXISTS" = "true" ] && [ -z "$TASK_PATH" ]; then
    echo "Task '$TASK_ID' is missing project_path in $CONTRACT_FILE" >&2
    echo "Add: project_path: \"$PROJECT_DIR\"" >&2
    exit 1
  fi
  if [ -n "$TASK_PATH" ]; then
    if printf '%s' "$TASK_PATH" | grep -q '\$'; then
      echo "Task '$TASK_ID' project_path must be an absolute path, not an environment variable expression." >&2
      echo "  contract: $TASK_PATH" >&2
      echo "  expected: $PROJECT_DIR" >&2
      exit 1
    fi
    if [ ! -d "$TASK_PATH" ]; then
      echo "Task '$TASK_ID' project_path does not exist on disk." >&2
      echo "  contract: $TASK_PATH" >&2
      echo "  expected: $PROJECT_DIR" >&2
      exit 1
    fi
    TASK_PATH_CANONICAL="$(cd "$TASK_PATH" && pwd -P)"
    if [ "$TASK_PATH_CANONICAL" != "$PROJECT_DIR" ]; then
      echo "Task '$TASK_ID' project_path mismatch." >&2
      echo "  contract: $TASK_PATH_CANONICAL" >&2
      echo "  expected: $PROJECT_DIR" >&2
      exit 1
    fi
  fi
fi

if [ ! -f "$INBOX_FILE" ]; then
  printf '# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n' > "$INBOX_FILE"
fi

{
  echo ""
  echo "- id: $ITEM_ID"
  echo "  to: $TARGET"
  echo "  task: $TASK_ID"
  echo "  project: $PROJECT_DIR"
  echo "  status: pending"
  echo "  priority: $PRIORITY"
  echo "  retry_count: 0"
  echo "  max_retries: 3"
  echo "  created_at: $(date -u +%FT%TZ)"
} >> "$INBOX_FILE"

echo "Enqueued inbox item:"
echo "  id: $ITEM_ID"
echo "  to: $TARGET"
echo "  task: $TASK_ID"
echo "  priority: $PRIORITY"
echo "  file: $INBOX_FILE"
