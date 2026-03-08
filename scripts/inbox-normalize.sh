#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-normalize.sh --project DIR [--archive] [--drop-status prepared] [--drop-id-prefix PREFIX]

Options:
  -p, --project DIR         Project directory containing .superharness/ (required)
      --archive             Archive dropped rows into .superharness/inbox.archive.yaml
      --drop-status STATUS  Drop rows with this status (repeatable). Default: prepared
      --drop-id-prefix PFX  Drop rows whose id starts with prefix (repeatable)
  -h, --help                Show this help message and exit
USAGE
}

PROJECT_DIR=""
ARCHIVE=0
DROP_STATUSES=()
DROP_PREFIXES=()

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --archive)
      ARCHIVE=1
      shift
      ;;
    --drop-status)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      DROP_STATUSES+=("$2")
      shift 2
      ;;
    --drop-id-prefix)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      DROP_PREFIXES+=("$2")
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
ARCHIVE_FILE="$PROJECT_DIR/.superharness/inbox.archive.yaml"

if [ ! -f "$INBOX_FILE" ]; then
  echo "Inbox file not found: $INBOX_FILE" >&2
  exit 1
fi

if [ ${#DROP_STATUSES[@]} -eq 0 ]; then
  DROP_STATUSES=("prepared")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX_YAML="$SCRIPT_DIR/inbox-yaml.rb"
[ -x "$INBOX_YAML" ] || { echo "Missing helper script: $INBOX_YAML" >&2; exit 1; }

args=(normalize --file "$INBOX_FILE")
for s in "${DROP_STATUSES[@]}"; do
  args+=(--drop-status "$s")
done
for p in "${DROP_PREFIXES[@]}"; do
  args+=(--drop-prefix "$p")
done
if [ "$ARCHIVE" -eq 1 ]; then
  args+=(--archive-file "$ARCHIVE_FILE" --now "$(date -u +%FT%TZ)")
fi
ruby "$INBOX_YAML" "${args[@]}"
echo "Normalized inbox: $INBOX_FILE"
