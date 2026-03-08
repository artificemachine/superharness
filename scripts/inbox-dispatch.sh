#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-dispatch.sh --project DIR [--to claude-code|codex-cli] [--print-only] [--non-interactive]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --to TARGET     Optional target filter: claude-code or codex-cli
      --print-only    Build and print kickoff prompt without launching CLI
      --non-interactive  Run target launchers in non-interactive mode
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
TARGET_FILTER=""
PRINT_ONLY=0
NON_INTERACTIVE=0

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET_FILTER="$2"
      shift 2
      ;;
    --print-only)
      PRINT_ONLY=1
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
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

case "$TARGET_FILTER" in
  ""|claude-code|codex-cli) ;;
  *)
    echo "--to must be claude-code or codex-cli" >&2
    exit 2
    ;;
esac

HARNESS_DIR="$PROJECT_DIR/.superharness"
INBOX_FILE="$HARNESS_DIR/inbox.yaml"

if [ ! -f "$INBOX_FILE" ]; then
  echo "Inbox file not found: $INBOX_FILE" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_CLAUDE="$SCRIPT_DIR/delegate-to-claude.sh"
LAUNCH_CODEX="$SCRIPT_DIR/delegate-to-codex.sh"

if [ ! -x "$LAUNCH_CLAUDE" ] || [ ! -x "$LAUNCH_CODEX" ]; then
  echo "Missing launcher scripts in $SCRIPT_DIR" >&2
  exit 1
fi

read_item() {
  awk -v target="$TARGET_FILTER" '
    function consider_candidate() {
      local_priority = priority
      if (local_priority == "" || local_priority !~ /^[0-9]+$/) {
        local_priority = 2
      }
      if (local_priority < 1 || local_priority > 3) {
        local_priority = 2
      }
      if (best_id == "" || local_priority < best_priority) {
        best_id = id
        best_to = to
        best_task = task
        best_project = project
        best_retry_count = retry_count
        best_max_retries = max_retries
        best_priority = local_priority
      }
    }
    function flush() {
      if (id != "" && status == "pending") {
        if (target == "" || to == target) {
          consider_candidate()
        }
      }
    }
    BEGIN {
      best_id = best_to = best_task = best_project = ""
      best_retry_count = best_max_retries = ""
      best_priority = 99
    }
    /^- id:[[:space:]]*/ {
      flush()
      id = $0
      sub(/^- id:[[:space:]]*/, "", id)
      to = task = project = status = retry_count = max_retries = priority = ""
      next
    }
    /^[[:space:]]*to:[[:space:]]*/ { to = $0; sub(/^[[:space:]]*to:[[:space:]]*/, "", to); next }
    /^[[:space:]]*task:[[:space:]]*/ { task = $0; sub(/^[[:space:]]*task:[[:space:]]*/, "", task); next }
    /^[[:space:]]*project:[[:space:]]*/ { project = $0; sub(/^[[:space:]]*project:[[:space:]]*/, "", project); next }
    /^[[:space:]]*priority:[[:space:]]*/ { priority = $0; sub(/^[[:space:]]*priority:[[:space:]]*/, "", priority); next }
    /^[[:space:]]*retry_count:[[:space:]]*/ { retry_count = $0; sub(/^[[:space:]]*retry_count:[[:space:]]*/, "", retry_count); next }
    /^[[:space:]]*max_retries:[[:space:]]*/ { max_retries = $0; sub(/^[[:space:]]*max_retries:[[:space:]]*/, "", max_retries); next }
    /^[[:space:]]*status:[[:space:]]*/ { status = $0; sub(/^[[:space:]]*status:[[:space:]]*/, "", status); next }
    END {
      flush()
      if (best_id != "") {
        print best_id "|" best_to "|" best_task "|" best_project "|" best_retry_count "|" best_max_retries "|" best_priority
      }
    }
  ' "$INBOX_FILE"
}

ITEM="$(read_item || true)"
if [ -z "$ITEM" ]; then
  echo "No pending inbox items found in $INBOX_FILE"
  exit 0
fi

ITEM_ID="$(printf '%s' "$ITEM" | cut -d'|' -f1)"
ITEM_TO="$(printf '%s' "$ITEM" | cut -d'|' -f2)"
ITEM_TASK="$(printf '%s' "$ITEM" | cut -d'|' -f3)"
ITEM_PROJECT="$(printf '%s' "$ITEM" | cut -d'|' -f4)"
ITEM_RETRY_COUNT="$(printf '%s' "$ITEM" | cut -d'|' -f5)"
ITEM_MAX_RETRIES="$(printf '%s' "$ITEM" | cut -d'|' -f6)"
ITEM_PRIORITY="$(printf '%s' "$ITEM" | cut -d'|' -f7)"

if [ -z "$ITEM_PROJECT" ]; then
  ITEM_PROJECT="$PROJECT_DIR"
fi
if [ -z "$ITEM_RETRY_COUNT" ]; then
  ITEM_RETRY_COUNT=0
fi
if [ -z "$ITEM_MAX_RETRIES" ]; then
  ITEM_MAX_RETRIES=3
fi
if [ -z "$ITEM_PRIORITY" ]; then
  ITEM_PRIORITY=2
fi

STATUS_AFTER="launched"
LAUNCH_ARGS=(--project "$ITEM_PROJECT" --task "$ITEM_TASK")
if [ "$PRINT_ONLY" -eq 1 ]; then
  STATUS_AFTER="launched"
  LAUNCH_ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  STATUS_AFTER="launched"
  LAUNCH_ARGS+=(--non-interactive)
fi

update_status() {
  local from_status="$1"
  local to_status="$2"
  local tmp
  local now
  now="$(date -u +%FT%TZ)"
  tmp="$(mktemp)"
  awk -v id="$ITEM_ID" -v from_status="$from_status" -v to_status="$to_status" -v now="$now" '
    BEGIN { in_block = 0; updated = 0; inserted = 0 }
    /^- id:[[:space:]]*/ {
      current = $0
      sub(/^- id:[[:space:]]*/, "", current)
      in_block = (current == id)
    }
    {
      if (in_block && $0 ~ "^[[:space:]]*status:[[:space:]]*" from_status "[[:space:]]*$") {
        sub(from_status, to_status)
        updated = 1
        print
        if (to_status == "launched") {
          print "  launched_at: " now
          inserted = 1
        } else if (to_status == "failed") {
          print "  failed_at: " now
          inserted = 1
        }
        next
      }
      print
    }
    END {
      if (updated == 0) {
        exit 2
      }
    }
  ' "$INBOX_FILE" > "$tmp"
  mv "$tmp" "$INBOX_FILE"
}

# Enforce retry budget before relaunch.
if [ "$ITEM_RETRY_COUNT" -ge "$ITEM_MAX_RETRIES" ]; then
  update_status "pending" "failed"
  echo "Inbox item updated: $ITEM_ID -> failed (retry limit reached: $ITEM_RETRY_COUNT/$ITEM_MAX_RETRIES)"
  exit 1
fi

# Mark item as launched before invoking target CLI and increment retry_count.
tmp_retry="$(mktemp)"
awk -v id="$ITEM_ID" '
  BEGIN { in_block = 0; updated = 0 }
  /^- id:[[:space:]]*/ {
    current = $0
    sub(/^- id:[[:space:]]*/, "", current)
    in_block = (current == id)
  }
  {
    if (in_block && $0 ~ /^[[:space:]]*retry_count:[[:space:]]*[0-9]+[[:space:]]*$/) {
      n = $0
      sub(/^[[:space:]]*retry_count:[[:space:]]*/, "", n)
      n = n + 1
      print "  retry_count: " n
      updated = 1
      next
    }
    print
  }
  END {
    if (updated == 0) {
      exit 2
    }
  }
' "$INBOX_FILE" > "$tmp_retry"
mv "$tmp_retry" "$INBOX_FILE"
update_status "pending" "$STATUS_AFTER"
echo "Inbox item updated: $ITEM_ID -> $STATUS_AFTER (priority=$ITEM_PRIORITY, retries=$ITEM_RETRY_COUNT/$ITEM_MAX_RETRIES)"

case "$ITEM_TO" in
  claude-code)
    if ! bash "$LAUNCH_CLAUDE" "${LAUNCH_ARGS[@]}"; then
      [ "$STATUS_AFTER" = "launched" ] && update_status "launched" "failed" && echo "Inbox item updated: $ITEM_ID -> failed"
      exit 1
    fi
    ;;
  codex-cli)
    if ! bash "$LAUNCH_CODEX" "${LAUNCH_ARGS[@]}"; then
      [ "$STATUS_AFTER" = "launched" ] && update_status "launched" "failed" && echo "Inbox item updated: $ITEM_ID -> failed"
      exit 1
    fi
    ;;
  *)
    echo "Unsupported target '$ITEM_TO' for inbox item '$ITEM_ID'" >&2
    exit 1
    ;;
esac
