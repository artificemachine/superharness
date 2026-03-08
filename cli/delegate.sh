#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  delegate.sh --to claude-code|codex-cli [--project DIR] [--task TASK_ID] [--print-only] [--non-interactive]

Options:
      --to TARGET     Required: claude-code or codex-cli
  -p, --project DIR   Project directory containing .superharness/ (default: current dir)
  -t, --task TASK_ID  Specific task id to run (otherwise read from latest handoff for target)
      --print-only    Print generated prompt and exit (do not launch CLI)
      --non-interactive  Launch target in non-interactive mode where supported
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR="$(pwd)"
TARGET=""
TASK_ID=""
PRINT_ONLY=0
NON_INTERACTIVE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET="$2"
      shift 2
      ;;
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -t|--task)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
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

case "$TARGET" in
  claude-code|codex-cli) ;;
  *)
    echo "--to must be claude-code or codex-cli" >&2
    exit 2
    ;;
esac

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

HARNESS_DIR="$PROJECT_DIR/.superharness"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
ENGINE_CONTRACT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/engine/contract.rb"

[ -f "$ENGINE_CONTRACT" ] || { echo "Missing contract engine: $ENGINE_CONTRACT" >&2; exit 1; }
[ -f "$CONTRACT_FILE" ] || { echo "Missing contract file: $CONTRACT_FILE" >&2; exit 1; }
[ -d "$HANDOFF_DIR" ] || { echo "Missing handoff directory: $HANDOFF_DIR" >&2; exit 1; }

CONTRACT_ID="$(ruby "$ENGINE_CONTRACT" contract_id --file "$CONTRACT_FILE" | tr -d '\"')"
[ -n "$CONTRACT_ID" ] || CONTRACT_ID="unknown-contract"

LATEST_HANDOFF=""
if [ -z "$TASK_ID" ]; then
  RES="$(ruby "$ENGINE_CONTRACT" latest_handoff_task --dir "$HANDOFF_DIR" --to "$TARGET")"
  if [ -n "$RES" ]; then
    TASK_ID="$(printf '%s' "$RES" | cut -d'|' -f1)"
    LATEST_HANDOFF="$(printf '%s' "$RES" | cut -d'|' -f2-)"
  fi
fi

if [ -z "$TASK_ID" ]; then
  echo "Could not determine task id. Provide --task TASK_ID or create a $TARGET handoff in $HANDOFF_DIR" >&2
  exit 1
fi

if [ "$TARGET" = "claude-code" ]; then
  if [ -n "$LATEST_HANDOFF" ]; then
    PROMPT="continue contract
Read the latest handoff addressed to claude-code and execute task ${TASK_ID}.
Use scope, commands, and acceptance criteria from the handoff.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and refresh the handoff with outcomes.
Contract id: ${CONTRACT_ID}."
  else
    PROMPT="continue contract
No handoff exists yet for task ${TASK_ID}.
Read .superharness/contract.yaml directly and execute task ${TASK_ID}.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and create a new handoff with outcomes.
Contract id: ${CONTRACT_ID}."
  fi
else
  if [ -n "$LATEST_HANDOFF" ]; then
    PROMPT="continue contract
Read the latest handoff addressed to codex-cli and execute task ${TASK_ID}.
Use scope, commands, and acceptance criteria from the handoff.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and refresh the handoff with outcomes.
Contract id: ${CONTRACT_ID}."
  else
    PROMPT="continue contract
No handoff exists yet for task ${TASK_ID}.
Read .superharness/contract.yaml directly and execute task ${TASK_ID}.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and create a new handoff with outcomes.
Contract id: ${CONTRACT_ID}."
  fi
fi

echo "Project: $PROJECT_DIR"
echo "Contract: $CONTRACT_ID"
echo "Task: $TASK_ID"
if [ -n "$LATEST_HANDOFF" ]; then
  echo "Handoff: $LATEST_HANDOFF"
fi

if [ "$PRINT_ONLY" -eq 1 ]; then
  echo ""
  echo "Generated prompt:"
  echo "-----------------"
  printf '%s\n' "$PROMPT"
  exit 0
fi

if [ "$TARGET" = "claude-code" ]; then
  if ! command -v claude >/dev/null 2>&1; then
    echo "claude CLI is not installed or not on PATH" >&2
    exit 1
  fi
  echo ""
  if [ "$NON_INTERACTIVE" -eq 1 ]; then
    echo "Launching Claude (non-interactive)..."
    cd "$PROJECT_DIR"
    exec claude -p "$PROMPT"
  fi
  echo "Launching Claude..."
  cd "$PROJECT_DIR"
  exec claude "$PROMPT"
else
  if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI is not installed or not on PATH" >&2
    exit 1
  fi
  echo ""
  if [ "$NON_INTERACTIVE" -eq 1 ]; then
    echo "Launching Codex (non-interactive)..."
    exec codex exec -C "$PROJECT_DIR" "$PROMPT"
  fi
  echo "Launching Codex..."
  exec codex -C "$PROJECT_DIR" "$PROMPT"
fi
