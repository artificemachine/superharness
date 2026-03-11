#!/bin/bash
set -euo pipefail

# Discussion round dispatcher — called by inbox-watch.sh each cycle.
# Scans active discussions, checks for round completion, advances or
# closes, and enqueues next-round inbox items for both participants.

usage() {
  cat << 'USAGE'
Usage:
  discussion-dispatch.sh --project DIR

Scans .superharness/discussions/ for active discussions, advances
completed rounds, and enqueues next-round inbox items.
USAGE
}

PROJECT_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }

DISCUSSIONS_DIR="$PROJECT_DIR/.superharness/discussions"
[ -d "$DISCUSSIONS_DIR" ] || exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/../engine/discussion.rb"
INBOX_ENGINE="$SCRIPT_DIR/../engine/inbox.rb"
INBOX_FILE="$PROJECT_DIR/.superharness/inbox.yaml"

[ -f "$ENGINE" ] || { echo "Missing discussion engine: $ENGINE" >&2; exit 1; }
[ -f "$INBOX_ENGINE" ] || { echo "Missing inbox engine: $INBOX_ENGINE" >&2; exit 1; }

for state_file in "$DISCUSSIONS_DIR"/*/state.yaml; do
  [ -f "$state_file" ] || continue

  DISCUSSION_DIR="$(dirname "$state_file")"

  # Read state as JSON
  STATUS_JSON="$(ruby "$ENGINE" status --discussion-dir "$DISCUSSION_DIR" 2>/dev/null)" || continue
  DISC_STATUS="$(printf '%s' "$STATUS_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["status"]')"
  [ "$DISC_STATUS" = "active" ] || continue

  CURRENT_ROUND="$(printf '%s' "$STATUS_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["current_round"]')"
  DISC_ID="$(printf '%s' "$STATUS_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["id"]')"
  TOPIC="$(printf '%s' "$STATUS_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["topic"]')"

  # Check if current round is complete
  CHECK_JSON="$(ruby "$ENGINE" check_round --discussion-dir "$DISCUSSION_DIR" --round "$CURRENT_ROUND" 2>/dev/null)" || continue
  COMPLETE="$(printf '%s' "$CHECK_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["complete"]')"

  if [ "$COMPLETE" = "true" ]; then
    # Advance: closes with consensus/no_consensus or bumps to next round
    ADVANCE_JSON="$(ruby "$ENGINE" advance --discussion-dir "$DISCUSSION_DIR" 2>/dev/null)" || continue
    ACTION="$(printf '%s' "$ADVANCE_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["action"]')"

    if [ "$ACTION" = "advanced" ]; then
      NEXT_ROUND="$(printf '%s' "$ADVANCE_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["next_round"]')"
      echo "Discussion $DISC_ID: advanced to round $NEXT_ROUND"

      # Read participants and enqueue inbox items for each
      PARTICIPANTS="$(printf '%s' "$STATUS_JSON" | ruby -rjson -e 'JSON.parse(STDIN.read)["participants"].each { |p| puts p }')"
      while IFS= read -r AGENT; do
        [ -n "$AGENT" ] || continue
        NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        ITEM_ID="$(date -u +%Y%m%dT%H%M%SZ)-${DISC_ID}-r${NEXT_ROUND}-${AGENT}-$$-$(( RANDOM * RANDOM ))"
        ruby "$INBOX_ENGINE" enqueue \
          --file "$INBOX_FILE" \
          --id "$ITEM_ID" \
          --to "$AGENT" \
          --task "${DISC_ID}/round-${NEXT_ROUND}" \
          --project "$PROJECT_DIR" \
          --priority 1 \
          --created-at "$NOW" 2>/dev/null || true
        echo "  Enqueued round $NEXT_ROUND for $AGENT: $ITEM_ID"
      done <<< "$PARTICIPANTS"

    elif [ "$ACTION" = "closed" ]; then
      REASON="$(printf '%s' "$ADVANCE_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["reason"]')"
      ROUND="$(printf '%s' "$ADVANCE_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["round"]')"
      echo "Discussion $DISC_ID: closed (reason=$REASON, round=$ROUND)"
    fi
  else
    # Round not complete — check if inbox items exist for pending agents
    PENDING="$(printf '%s' "$CHECK_JSON" | ruby -rjson -e 'JSON.parse(STDIN.read)["agents_pending"].each { |p| puts p }')"
    while IFS= read -r AGENT; do
      [ -n "$AGENT" ] || continue
      TASK_KEY="${DISC_ID}/round-${CURRENT_ROUND}"
      # Check if an active inbox item already exists for this agent+task
      HAS_ACTIVE="$(ruby "$INBOX_ENGINE" has_active --file "$INBOX_FILE" --to "$AGENT" --task "$TASK_KEY" 2>/dev/null || echo "false")"
      if [ "$HAS_ACTIVE" != "true" ]; then
        NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        ITEM_ID="$(date -u +%Y%m%dT%H%M%SZ)-${DISC_ID}-r${CURRENT_ROUND}-${AGENT}-$$-$(( RANDOM * RANDOM ))"
        ruby "$INBOX_ENGINE" enqueue \
          --file "$INBOX_FILE" \
          --id "$ITEM_ID" \
          --to "$AGENT" \
          --task "$TASK_KEY" \
          --project "$PROJECT_DIR" \
          --priority 1 \
          --created-at "$NOW" 2>/dev/null || true
        echo "  Enqueued round $CURRENT_ROUND for $AGENT: $ITEM_ID"
      fi
    done <<< "$PENDING"
  fi
done
