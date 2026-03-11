#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/../engine/discuss.rb"

usage() {
  cat << 'USAGE'
Usage:
  discuss.sh <status|approve> [options]

Status options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --task TASK_ID     Optional task id filter

Approve options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --task TASK_ID     Required task id to approve
  --by ACTOR         Approver identity (default: owner)
  --note TEXT        Optional approval note

Examples:
  discuss.sh status --project .
  discuss.sh approve --project . --task <task-id> --by owner --note "Approved"
USAGE
}

SUBCMD="${1:-}"
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  shift
fi

if [ -z "$SUBCMD" ] || [ "$SUBCMD" = "help" ] || [ "$SUBCMD" = "-h" ] || [ "$SUBCMD" = "--help" ]; then
  usage
  exit 0
fi

# Check Ruby availability
command -v ruby >/dev/null 2>&1 || { echo "Error: ruby is required but not found in PATH" >&2; exit 1; }

PROJECT_DIR="$(pwd)"
TASK_ID=""
ACTOR="owner"
NOTE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --task)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
      shift 2
      ;;
    --by)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      ACTOR="$2"
      shift 2
      ;;
    --note)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      NOTE="$2"
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

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
HARNESS_DIR="$PROJECT_DIR/.superharness"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
INBOX_FILE="$HARNESS_DIR/inbox.yaml"

[ -d "$HARNESS_DIR" ] || { echo "Missing .superharness directory: $HARNESS_DIR" >&2; exit 1; }
[ -d "$HANDOFF_DIR" ] || { echo "Missing handoffs directory: $HANDOFF_DIR" >&2; exit 1; }

case "$SUBCMD" in
  status)
    ruby "$ENGINE" status \
      --handoff-dir "$HANDOFF_DIR" \
      ${TASK_ID:+--task "$TASK_ID"}
    ;;

  approve)
    [ -n "$TASK_ID" ] || { echo "--task is required for approve" >&2; exit 2; }
    ruby "$ENGINE" approve \
      --handoff-dir "$HANDOFF_DIR" \
      --contract-file "$CONTRACT_FILE" \
      --inbox-file "$INBOX_FILE" \
      --task "$TASK_ID" \
      --project-dir "$PROJECT_DIR" \
      --by "$ACTOR" \
      --note "$NOTE"
    ;;

  *)
    echo "Unknown discuss subcommand: $SUBCMD" >&2
    usage >&2
    exit 2
    ;;
esac
