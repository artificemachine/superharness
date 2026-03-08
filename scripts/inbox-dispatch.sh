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
    function flush() {
      if (id != "" && status == "pending") {
        if (target == "" || to == target) {
          print id "|" to "|" task "|" project
          exit 0
        }
      }
    }
    /^- id:[[:space:]]*/ {
      flush()
      id = $0
      sub(/^- id:[[:space:]]*/, "", id)
      to = task = project = status = ""
      next
    }
    /^[[:space:]]*to:[[:space:]]*/ { to = $0; sub(/^[[:space:]]*to:[[:space:]]*/, "", to); next }
    /^[[:space:]]*task:[[:space:]]*/ { task = $0; sub(/^[[:space:]]*task:[[:space:]]*/, "", task); next }
    /^[[:space:]]*project:[[:space:]]*/ { project = $0; sub(/^[[:space:]]*project:[[:space:]]*/, "", project); next }
    /^[[:space:]]*status:[[:space:]]*/ { status = $0; sub(/^[[:space:]]*status:[[:space:]]*/, "", status); next }
    END {
      flush()
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

if [ -z "$ITEM_PROJECT" ]; then
  ITEM_PROJECT="$PROJECT_DIR"
fi

STATUS_AFTER="launched"
LAUNCH_ARGS=(--project "$ITEM_PROJECT" --task "$ITEM_TASK")
if [ "$PRINT_ONLY" -eq 1 ]; then
  STATUS_AFTER="prepared"
  LAUNCH_ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  STATUS_AFTER="launched"
  LAUNCH_ARGS+=(--non-interactive)
fi

case "$ITEM_TO" in
  claude-code)
    bash "$LAUNCH_CLAUDE" "${LAUNCH_ARGS[@]}"
    ;;
  codex-cli)
    bash "$LAUNCH_CODEX" "${LAUNCH_ARGS[@]}"
    ;;
  *)
    echo "Unsupported target '$ITEM_TO' for inbox item '$ITEM_ID'" >&2
    exit 1
    ;;
esac

tmp="$(mktemp)"
awk -v id="$ITEM_ID" -v status_after="$STATUS_AFTER" '
  BEGIN { in_block = 0; updated = 0 }
  /^- id:[[:space:]]*/ {
    current = $0
    sub(/^- id:[[:space:]]*/, "", current)
    in_block = (current == id)
  }
  {
    if (in_block && $0 ~ /^[[:space:]]*status:[[:space:]]*pending[[:space:]]*$/) {
      sub(/pending/, status_after)
      updated = 1
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

echo "Inbox item updated: $ITEM_ID -> $STATUS_AFTER"
