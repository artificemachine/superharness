#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-watch.sh --project DIR [--to claude-code|codex-cli|both] [--print-only] [--non-interactive] [--codex-bypass] [--recover-timeout-minutes N] [--recover-action stale|retry]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --to TARGET     Dispatch target filter (default: both)
      --print-only    Prepare prompts only, do not launch CLIs
      --non-interactive  Launch CLIs non-interactively where supported
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
      --recover-timeout-minutes N  Mark launched rows stale/retry after N minutes (default: 20)
      --recover-action MODE  stale (default) or retry
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
TARGET="both"
PRINT_ONLY=0
NON_INTERACTIVE=0
CODEX_BYPASS=0
RECOVER_TIMEOUT_MINUTES=20
RECOVER_ACTION="stale"

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET="$2"
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
    --recover-timeout-minutes)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      RECOVER_TIMEOUT_MINUTES="$2"
      shift 2
      ;;
    --recover-action)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      RECOVER_ACTION="$2"
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
case "$TARGET" in
  both|claude-code|codex-cli) ;;
  *)
    echo "--to must be one of: both, claude-code, codex-cli" >&2
    exit 2
    ;;
esac
case "$RECOVER_ACTION" in
  stale|retry) ;;
  *)
    echo "--recover-action must be one of: stale, retry" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH="$SCRIPT_DIR/inbox-dispatch.sh"
RECOVER="$SCRIPT_DIR/inbox-recover-stale.sh"

if [ ! -x "$DISPATCH" ] || [ ! -x "$RECOVER" ]; then
  echo "Missing executable dispatcher: $DISPATCH" >&2
  exit 1
fi

LOCK_KEY="$(printf '%s' "$PROJECT_DIR" | shasum | awk '{print $1}')"
LOCK_DIR="/tmp/superharness-inbox-watch-${LOCK_KEY}.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Watcher already running for project: $PROJECT_DIR"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" >/dev/null 2>&1 || true' EXIT

COMMON_ARGS=(--project "$PROJECT_DIR")
if [ "$PRINT_ONLY" -eq 1 ]; then
  COMMON_ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  COMMON_ARGS+=(--non-interactive)
fi
if [ "$CODEX_BYPASS" -eq 1 ]; then
  COMMON_ARGS+=(--codex-bypass)
fi

RECOVER_ARGS=(--project "$PROJECT_DIR" --timeout-minutes "$RECOVER_TIMEOUT_MINUTES" --action "$RECOVER_ACTION")
bash "$RECOVER" "${RECOVER_ARGS[@]}" || true

run_dispatch() {
  local to="$1"
  bash "$DISPATCH" "${COMMON_ARGS[@]}" --to "$to" || true
}

if [ "$TARGET" = "both" ] || [ "$TARGET" = "claude-code" ]; then
  run_dispatch "claude-code"
fi

if [ "$TARGET" = "both" ] || [ "$TARGET" = "codex-cli" ]; then
  run_dispatch "codex-cli"
fi
