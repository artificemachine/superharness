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
INBOX_YAML="$SCRIPT_DIR/inbox-yaml.rb"

if [ ! -x "$LAUNCH_CLAUDE" ] || [ ! -x "$LAUNCH_CODEX" ] || [ ! -x "$INBOX_YAML" ]; then
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

if ! acquire_lock; then
  echo "Another inbox dispatcher is active for $INBOX_FILE; skipping."
  exit 0
fi
trap 'release_lock' EXIT

READ_ARGS=(next_pending --file "$INBOX_FILE")
if [ -n "$TARGET_FILTER" ]; then
  READ_ARGS+=(--to "$TARGET_FILTER")
fi
if ! ITEM="$(ruby "$INBOX_YAML" "${READ_ARGS[@]}")"; then
  echo "Failed to read pending inbox item from $INBOX_FILE" >&2
  exit 1
fi
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

LAUNCH_ARGS=(--project "$ITEM_PROJECT" --task "$ITEM_TASK")
if [ "$PRINT_ONLY" -eq 1 ]; then
  LAUNCH_ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  LAUNCH_ARGS+=(--non-interactive)
fi

LAUNCH_NOW="$(date -u +%FT%TZ)"
LAUNCH_RESULT="$(ruby "$INBOX_YAML" launch --file "$INBOX_FILE" --id "$ITEM_ID" --now "$LAUNCH_NOW")" || LAUNCH_RC=$?
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

LAUNCHER=""
case "$ITEM_TO" in
  claude-code) LAUNCHER="$LAUNCH_CLAUDE" ;;
  codex-cli) LAUNCHER="$LAUNCH_CODEX" ;;
  *)
    echo "Unsupported target '$ITEM_TO' for inbox item '$ITEM_ID'" >&2
    exit 1
    ;;
esac

if ! bash "$LAUNCHER" "${LAUNCH_ARGS[@]}"; then
  FAIL_NOW="$(date -u +%FT%TZ)"
  if ! acquire_lock; then
    echo "Failed to acquire inbox lock while marking failure for $ITEM_ID" >&2
    exit 1
  fi
  ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to failed --now "$FAIL_NOW" --stamp-key failed_at >/dev/null
  release_lock
  echo "Inbox item updated: $ITEM_ID -> failed"
  exit 1
fi
