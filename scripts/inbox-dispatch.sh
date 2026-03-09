#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-dispatch.sh --project DIR [--to claude-code|codex-cli] [--print-only] [--non-interactive] [--codex-bypass]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --to TARGET     Optional target filter: claude-code or codex-cli
      --print-only    Build and print kickoff prompt without launching CLI
      --non-interactive  Run target launchers in non-interactive mode
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
TARGET_FILTER=""
PRINT_ONLY=0
NON_INTERACTIVE=0
CODEX_BYPASS=0

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
    --codex-bypass)
      CODEX_BYPASS=1
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
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"

if [ ! -f "$INBOX_FILE" ]; then
  echo "Inbox file not found: $INBOX_FILE" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_CLAUDE="$SCRIPT_DIR/delegate-to-claude.sh"
LAUNCH_CODEX="$SCRIPT_DIR/delegate-to-codex.sh"
INBOX_YAML="$SCRIPT_DIR/inbox-yaml.rb"
CONTRACT_YAML="$SCRIPT_DIR/../engine/contract.rb"

if [ ! -x "$LAUNCH_CLAUDE" ] || [ ! -x "$LAUNCH_CODEX" ] || [ ! -x "$INBOX_YAML" ] || [ ! -f "$CONTRACT_YAML" ]; then
  echo "Missing launcher scripts in $SCRIPT_DIR" >&2
  exit 1
fi

LOCK_FILE="${INBOX_FILE}.lock"
LOCK_DIR="${LOCK_FILE}.d"
LOCK_HELD=0

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_HELD=1
    return 0
  fi
  return 1
}

release_lock() {
  if [ "$LOCK_HELD" -eq 1 ]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
    LOCK_HELD=0
  fi
}

acquire_lock_with_retry() {
  local attempts="${1:-50}"
  local delay_seconds="${2:-0.1}"
  local attempt=0

  while [ "$attempt" -lt "$attempts" ]; do
    if acquire_lock; then
      return 0
    fi
    sleep "$delay_seconds"
    attempt=$((attempt + 1))
  done
  return 1
}

mark_item_failed() {
  local item_id="$1"
  local failed_at="$2"

  if ! acquire_lock_with_retry 50 0.1; then
    echo "Failed to acquire inbox lock while marking failure for $item_id" >&2
    return 1
  fi

  if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$item_id" --from launched --to failed --now "$failed_at" --stamp-key failed_at >/dev/null 2>&1 \
    || ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$item_id" --from running --to failed --now "$failed_at" --stamp-key failed_at >/dev/null 2>&1; then
    release_lock
    echo "Inbox item updated: $item_id -> failed"
    return 0
  fi

  release_lock
  echo "Failed to mark inbox item as failed for $item_id" >&2
  return 1
}

if ! acquire_lock; then
  echo "Another inbox dispatcher is active for $INBOX_FILE; skipping."
  exit 0
fi
trap 'release_lock' EXIT

READ_ARGS=(next_pending --file "$INBOX_FILE")
if [ -n "$TARGET_FILTER" ]; then
  READ_ARGS+=(--to "$TARGET_FILTER")
fi
if ! ITEM="$(ruby "$INBOX_YAML" "${READ_ARGS[@]}" 2>&1)"; then
  echo "Failed to read pending inbox item from $INBOX_FILE: $ITEM" >&2
  exit 1
fi
if [ -z "$ITEM" ]; then
  echo "No pending inbox items found in $INBOX_FILE"
  exit 0
fi

ITEM_FIELDS=()
while IFS= read -r -d '' field; do
  ITEM_FIELDS+=("$field")
done < <(
  printf '%s' "$ITEM" | ruby -rjson -e '
    h = JSON.parse(STDIN.read)
    keys = %w[id to task project retry_count max_retries priority]
    keys.each { |k| print(h.fetch(k, "").to_s); print("\0") }
  '
)
if [ "${#ITEM_FIELDS[@]}" -lt 7 ]; then
  echo "Failed to parse pending inbox item from $INBOX_FILE" >&2
  exit 1
fi

ITEM_ID="${ITEM_FIELDS[0]}"
ITEM_TO="${ITEM_FIELDS[1]}"
ITEM_TASK="${ITEM_FIELDS[2]}"
ITEM_PROJECT="${ITEM_FIELDS[3]}"
ITEM_RETRY_COUNT="${ITEM_FIELDS[4]}"
ITEM_MAX_RETRIES="${ITEM_FIELDS[5]}"
ITEM_PRIORITY="${ITEM_FIELDS[6]}"

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

LAUNCHER=""
case "$ITEM_TO" in
  claude-code) LAUNCHER="$LAUNCH_CLAUDE" ;;
  codex-cli) LAUNCHER="$LAUNCH_CODEX" ;;
  *)
    echo "Unsupported target '$ITEM_TO' for inbox item '$ITEM_ID'" >&2
    exit 1
    ;;
esac

LAUNCH_ARGS=(--project "$ITEM_PROJECT" --task "$ITEM_TASK")
if [ "$PRINT_ONLY" -eq 1 ]; then
  LAUNCH_ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  LAUNCH_ARGS+=(--non-interactive)
fi
if [ "$CODEX_BYPASS" -eq 1 ]; then
  LAUNCH_ARGS+=(--codex-bypass)
fi

LAUNCH_NOW="$(date -u +%FT%TZ)"
LAUNCH_RESULT="$(ruby "$INBOX_YAML" launch --file "$INBOX_FILE" --id "$ITEM_ID" --now "$LAUNCH_NOW" 2>&1)" || LAUNCH_RC=$?
LAUNCH_RC=${LAUNCH_RC:-0}
release_lock

if [ "$LAUNCH_RC" -eq 4 ]; then
  echo "Inbox item updated: $ITEM_ID -> failed (retry limit reached: $ITEM_RETRY_COUNT/$ITEM_MAX_RETRIES)"
  exit 1
fi
if [ "$LAUNCH_RC" -ne 0 ]; then
  echo "Failed to launch inbox item transition for $ITEM_ID: $LAUNCH_RESULT" >&2
  exit 1
fi

NEW_RETRY_COUNT="$(printf '%s\n' "$LAUNCH_RESULT" | sed -n 's/.*retry_count=\([0-9][0-9]*\).*/\1/p')"
if [ -z "$NEW_RETRY_COUNT" ]; then
  NEW_RETRY_COUNT="$ITEM_RETRY_COUNT"
fi
echo "Inbox item updated: $ITEM_ID -> launched (priority=$ITEM_PRIORITY, retries=$NEW_RETRY_COUNT/$ITEM_MAX_RETRIES)"

if ! bash "$LAUNCHER" "${LAUNCH_ARGS[@]}"; then
  FAIL_NOW="$(date -u +%FT%TZ)"
  mark_item_failed "$ITEM_ID" "$FAIL_NOW"
  exit 1
fi

# In non-interactive mode, the launched process has already exited. If the task
# did not transition itself to done/failed, reconcile stuck states immediately.
if [ "$NON_INTERACTIVE" -eq 1 ] && [ "$PRINT_ONLY" -eq 0 ]; then
  RECONCILE_NOW="$(date -u +%FT%TZ)"
  if ! acquire_lock_with_retry 50 0.1; then
    echo "Failed to acquire inbox lock while reconciling status for $ITEM_ID" >&2
    exit 1
  fi
  RECONCILED=0
  FINAL_STATE=""

  if [ -f "$CONTRACT_FILE" ]; then
    if ! FINAL_STATE="$(ruby "$CONTRACT_YAML" task_status --file "$CONTRACT_FILE" --task "$ITEM_TASK" 2>&1)"; then
      echo "Failed to read contract task status for $ITEM_TASK: $FINAL_STATE" >&2
      FINAL_STATE=""
    fi
  fi

  case "$FINAL_STATE" in
    done)
      if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "done" --now "$RECONCILE_NOW" --stamp-key done_at >/dev/null 2>&1; then
        RECONCILED=1
      elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "done" --now "$RECONCILE_NOW" --stamp-key done_at >/dev/null 2>&1; then
        RECONCILED=1
      fi
      ;;
    failed)
      if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
        RECONCILED=1
      elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
        RECONCILED=1
      fi
      ;;
    *)
      if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
        RECONCILED=1
      elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
        RECONCILED=1
      fi
      ;;
  esac
  release_lock

  if [ "$RECONCILED" -eq 1 ]; then
    if [ "$FINAL_STATE" = "done" ]; then
      echo "Inbox item updated: $ITEM_ID -> done (reconciled from contract task status)"
      exit 0
    fi
    echo "Inbox item updated: $ITEM_ID -> failed (non-interactive launch exited without done/failed)"
    exit 1
  fi
fi
