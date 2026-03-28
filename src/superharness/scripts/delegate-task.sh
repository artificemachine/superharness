#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  delegate-task.sh <task-id> [--project DIR] [--print-only] [--non-interactive] [--for-review]

Options:
  -p, --project DIR   Project directory containing .superharness/ (default: current dir)
      --print-only    Print generated prompt and exit (do not launch CLI)
      --non-interactive  Launch target in non-interactive mode where supported
      --for-review   Allow dispatch of a review_requested task for review workflow
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR="$(pwd)"
TASK_ID=""
PRINT_ONLY=0
NON_INTERACTIVE=0
FOR_REVIEW=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
PYTHON3="${SUPERHARNESS_PYTHON:-python3}"

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
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
    --for-review)
      FOR_REVIEW=1
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
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [ -z "$TASK_ID" ]; then
        TASK_ID="$1"
        shift
      else
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

[ -n "$TASK_ID" ] || { echo "task-id is required" >&2; usage >&2; exit 2; }

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
CONTRACT_FILE="$PROJECT_DIR/.superharness/contract.yaml"

[ -f "$CONTRACT_FILE" ] || { echo "Missing contract file: $CONTRACT_FILE" >&2; exit 1; }

OWNER="$("$PYTHON3" -m superharness.engine.contract task_owner --file "$CONTRACT_FILE" --task "$TASK_ID")"
case "$OWNER" in
  claude-code|codex-cli) ;;
  "")
    echo "Task '$TASK_ID' not found in contract: $CONTRACT_FILE" >&2
    exit 1
    ;;
  *)
    echo "Task '$TASK_ID' owner '$OWNER' is unsupported (expected claude-code|codex-cli)" >&2
    exit 1
    ;;
esac

ARGS=(--to "$OWNER" --project "$PROJECT_DIR" --task "$TASK_ID")
if [ "$PRINT_ONLY" -eq 1 ]; then
  ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  ARGS+=(--non-interactive)
fi
if [ "$FOR_REVIEW" -eq 1 ]; then
  ARGS+=(--for-review)
fi

exec "$PYTHON3" -m superharness.commands.delegate "${ARGS[@]}"
