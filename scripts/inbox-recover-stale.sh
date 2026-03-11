#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-recover-stale.sh --project DIR [--timeout-minutes N] [--action stale|retry]

Options:
  -p, --project DIR         Project directory containing .superharness/ (required)
      --timeout-minutes N   Mark launched rows stale/retry after N minutes (default: 20)
      --action MODE         stale (default) or retry
  -h, --help                Show this help message and exit
USAGE
}

PROJECT_DIR=""
TIMEOUT_MINUTES=20
ACTION="stale"

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --timeout-minutes)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TIMEOUT_MINUTES="$2"
      shift 2
      ;;
    --action)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      ACTION="$2"
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
case "$ACTION" in
  stale|retry) ;;
  *)
    echo "--action must be stale or retry" >&2
    exit 2
    ;;
esac
case "$TIMEOUT_MINUTES" in
  ''|*[!0-9]*)
    echo "--timeout-minutes must be a non-negative integer" >&2
    exit 2
    ;;
esac

INBOX_FILE="$PROJECT_DIR/.superharness/inbox.yaml"
if [ ! -f "$INBOX_FILE" ]; then
  echo "Inbox file not found: $INBOX_FILE" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX_YAML="$SCRIPT_DIR/inbox-yaml.rb"
[ -x "$INBOX_YAML" ] || { echo "Missing helper script: $INBOX_YAML" >&2; exit 1; }

NOW="$(date -u +%FT%TZ)"
ruby "$INBOX_YAML" recover_launched --file "$INBOX_FILE" --now "$NOW" --timeout-minutes "$TIMEOUT_MINUTES" --action "$ACTION"
