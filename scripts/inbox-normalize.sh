#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-normalize.sh --project DIR [--archive] [--drop-status prepared] [--drop-id-prefix PREFIX]

Options:
  -p, --project DIR         Project directory containing .superharness/ (required)
      --archive             Move dropped rows into .superharness/inbox.archive.yaml
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

tmp="$(mktemp)"
if [ "$ARCHIVE" -eq 1 ]; then
  if [ ! -f "$ARCHIVE_FILE" ]; then
    printf '# Inbox archive\n' > "$ARCHIVE_FILE"
  fi
  {
    echo ""
    echo "# normalized_at: $(date -u +%FT%TZ)"
    cat "$INBOX_FILE"
  } >> "$ARCHIVE_FILE"
fi

awk -v drop_statuses="$(IFS=,; echo "${DROP_STATUSES[*]}")" \
  -v drop_prefixes="$(IFS=,; echo "${DROP_PREFIXES[*]-}")" '
  function status_should_drop(s,   n, i, arr) {
    n = split(drop_statuses, arr, ",")
    for (i = 1; i <= n; i++) {
      if (arr[i] != "" && s == arr[i]) return 1
    }
    return 0
  }
  function id_should_drop(id,   n, i, arr, pfx) {
    n = split(drop_prefixes, arr, ",")
    for (i = 1; i <= n; i++) {
      pfx = arr[i]
      if (pfx != "" && index(id, pfx) == 1) return 1
    }
    return 0
  }
  function emit_block(drop,   i) {
    if (block_len == 0) return
    if (!drop) {
      for (i = 1; i <= block_len; i++) print block[i]
    }
    block_len = 0
    block_id = ""
    block_status = ""
  }
  BEGIN {
    block_len = 0
  }
  NR == 1 && $0 ~ /^# Delegation inbox/ {
    print "# Delegation inbox"
    next
  }
  NR == 2 && $0 ~ /^# status:/ {
    print "# status: pending|launched|running|done|failed|stale"
    next
  }
  /^- id:[[:space:]]*/ {
    drop = (status_should_drop(block_status) || id_should_drop(block_id))
    emit_block(drop)
    block_len++
    block[block_len] = $0
    block_id = $0
    sub(/^- id:[[:space:]]*/, "", block_id)
    block_status = ""
    next
  }
  block_len > 0 {
    block_len++
    block[block_len] = $0
    if ($0 ~ /^[[:space:]]*status:[[:space:]]*/) {
      block_status = $0
      sub(/^[[:space:]]*status:[[:space:]]*/, "", block_status)
    }
    next
  }
  { print }
  END {
    drop = (status_should_drop(block_status) || id_should_drop(block_id))
    emit_block(drop)
  }
' "$INBOX_FILE" > "$tmp"

mv "$tmp" "$INBOX_FILE"
echo "Normalized inbox: $INBOX_FILE"
