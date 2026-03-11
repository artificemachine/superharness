#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-watch.sh --project DIR [--foreground] [--interval SEC] [--to claude-code|codex-cli|both] [--print-only] [--non-interactive] [--codex-bypass] [--recover-timeout-minutes N] [--recover-action stale|retry] [--launcher-timeout SECONDS] [--lock-stale-minutes N]

Options:
  -p, --project DIR   Project directory containing .superharness/
  -f, --foreground    Run continuously in the foreground (cross-platform)
  -i, --interval SEC  Poll interval in seconds for foreground mode (default: 30)
      --to TARGET     Dispatch target filter (default: both)
      --print-only    Prepare prompts only, do not launch CLIs
      --non-interactive  Launch CLIs non-interactively where supported
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
      --recover-timeout-minutes N  Mark launched rows stale/retry after N minutes (default: 20)
      --recover-action MODE  stale (default) or retry
      --launcher-timeout SECONDS  Kill launcher after SECONDS (passed to inbox-dispatch.sh, default: 0 = no timeout)
      --lock-stale-minutes N  Auto-break watcher lock if older than N minutes (default: 30)
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
LAUNCHER_TIMEOUT=0
LOCK_STALE_MINUTES=30
FOREGROUND=0
INTERVAL=30

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
    --launcher-timeout)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      LAUNCHER_TIMEOUT="$2"
      shift 2
      ;;
    --lock-stale-minutes)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      LOCK_STALE_MINUTES="$2"
      shift 2
      ;;
    -f|--foreground)
      FOREGROUND=1
      shift
      ;;
    -i|--interval)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      INTERVAL="$2"
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
if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
if [ ! -d "$PROJECT_DIR/.superharness" ]; then
  echo "Not a superharness project (missing .superharness/): $PROJECT_DIR" >&2
  echo "Run: superharness init" >&2
  exit 1
fi
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
case "$RECOVER_TIMEOUT_MINUTES" in
  ''|*[!0-9]*)
    echo "--recover-timeout-minutes must be a non-negative integer" >&2
    exit 2
    ;;
esac
case "$LAUNCHER_TIMEOUT" in
  ''|*[!0-9]*)
    echo "--launcher-timeout must be a non-negative integer" >&2
    exit 2
    ;;
esac
case "$LOCK_STALE_MINUTES" in
  ''|*[!0-9]*)
    echo "--lock-stale-minutes must be a non-negative integer" >&2
    exit 2
    ;;
esac
case "$INTERVAL" in
  ''|0|*[!0-9]*)
    echo "--interval must be a positive integer" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH="$SCRIPT_DIR/inbox-dispatch.sh"
RECOVER="$SCRIPT_DIR/inbox-recover-stale.sh"
DEADLINE_CHECK="$SCRIPT_DIR/inbox-deadline-check.sh"

if [ ! -x "$DISPATCH" ]; then
  echo "Missing executable dispatcher: $DISPATCH" >&2
  exit 1
fi
if [ ! -x "$RECOVER" ]; then
  echo "Missing executable recover script: $RECOVER" >&2
  exit 1
fi

LOCK_KEY="$(printf '%s' "$PROJECT_DIR" | shasum | awk '{print $1}')"
LOCK_DIR="/tmp/superharness-inbox-watch-${LOCK_KEY}.lock"

# Auto-break stale watcher lock if older than LOCK_STALE_MINUTES
if [ -d "$LOCK_DIR" ] && [ "$LOCK_STALE_MINUTES" -gt 0 ]; then
  LOCK_AGE_SECONDS=0
  if stat -f %m "$LOCK_DIR" >/dev/null 2>&1; then
    # macOS stat
    LOCK_CREATED="$(stat -f %m "$LOCK_DIR")"
    NOW_EPOCH="$(date +%s)"
    LOCK_AGE_SECONDS=$(( NOW_EPOCH - LOCK_CREATED ))
  elif stat -c %Y "$LOCK_DIR" >/dev/null 2>&1; then
    # GNU/Linux stat
    LOCK_CREATED="$(stat -c %Y "$LOCK_DIR")"
    NOW_EPOCH="$(date +%s)"
    LOCK_AGE_SECONDS=$(( NOW_EPOCH - LOCK_CREATED ))
  fi
  LOCK_STALE_SECONDS=$(( LOCK_STALE_MINUTES * 60 ))
  if [ "$LOCK_AGE_SECONDS" -ge "$LOCK_STALE_SECONDS" ]; then
    echo "Auto-breaking stale watcher lock (age: ${LOCK_AGE_SECONDS}s, threshold: ${LOCK_STALE_SECONDS}s): $LOCK_DIR"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
fi

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
if [ "$LAUNCHER_TIMEOUT" -gt 0 ]; then
  COMMON_ARGS+=(--launcher-timeout "$LAUNCHER_TIMEOUT")
fi

RECOVER_ARGS=(--project "$PROJECT_DIR" --timeout-minutes "$RECOVER_TIMEOUT_MINUTES" --action "$RECOVER_ACTION")
INBOX_FILE="$PROJECT_DIR/.superharness/inbox.yaml"

run_dispatch() {
  local to="$1"
  bash "$DISPATCH" "${COMMON_ARGS[@]}" --to "$to" || true
}

sync_worker_copy() {
  local source_repo="$PROJECT_DIR"
  local worker_dir="$HOME/.superharness-workers/$(basename "$source_repo")"
  if [ -d "$worker_dir" ] && [ -d "$source_repo/.git" ]; then
    rsync -a --delete \
      --exclude '.git' \
      --exclude '.superharness/inbox.yaml' \
      "$source_repo/" "$worker_dir/" 2>/dev/null || true
  fi
}

run_cycle() {
  sync_worker_copy

  if [ -x "$DEADLINE_CHECK" ]; then
    bash "$DEADLINE_CHECK" --project "$PROJECT_DIR" || true
  fi

  # Skip dispatch/recover if no inbox exists yet (avoids noisy repeated errors)
  if [ ! -f "$INBOX_FILE" ]; then
    return
  fi

  bash "$RECOVER" "${RECOVER_ARGS[@]}" || true

  if [ "$TARGET" = "both" ] || [ "$TARGET" = "claude-code" ]; then
    run_dispatch "claude-code"
  fi

  if [ "$TARGET" = "both" ] || [ "$TARGET" = "codex-cli" ]; then
    run_dispatch "codex-cli"
  fi
}

if [ "$FOREGROUND" -eq 1 ]; then
  RUNNING=1
  trap 'RUNNING=0; echo ""; echo "Watcher stopped."; rmdir "$LOCK_DIR" >/dev/null 2>&1 || true; exit 0' INT TERM HUP
  echo "superharness watcher (foreground) — project: $PROJECT_DIR"
  echo "Polling every ${INTERVAL}s. Press Ctrl+C to stop."
  while [ "$RUNNING" -eq 1 ]; do
    run_cycle
    sleep "$INTERVAL" &
    wait $! 2>/dev/null || true
  done
else
  # Single-cycle mode (for launchd / cron)
  run_cycle
fi
