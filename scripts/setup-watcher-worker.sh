#!/bin/bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  setup-watcher-worker.sh --project DIR [--worker DIR] [--interval SEC] [--recover-timeout-minutes N] [--recover-action stale|retry] [--launcher-timeout SECONDS] [--to claude-code|codex-cli|both] [--codex-bypass]

Creates/refreshes a clean watcher worker directory (without .git), links
.superharness from the source project, installs launchd watcher, and records
the watcher project path in .superharness/watcher.yaml.

Options:
  -p, --project DIR   Source project directory containing .superharness/ (required)
  -w, --worker DIR    Worker directory (default: ~/.superharness-workers/<project-basename>)
  -i, --interval SEC  Watcher interval in seconds (default: 15)
      --recover-timeout-minutes N  Mark launched rows stale/retry after N minutes (default: 3)
      --recover-action MODE  stale or retry (default: retry)
      --launcher-timeout SECONDS  Kill launcher after SECONDS (default: 180)
      --to TARGET     Dispatch target: claude-code|codex-cli|both (default: both)
      --codex-bypass  Enable codex dangerous bypass in non-interactive mode
  -h, --help          Show this help message
USAGE
}

PROJECT_DIR=""
WORKER_DIR=""
INTERVAL=15
RECOVER_TIMEOUT_MINUTES=3
RECOVER_ACTION=retry
LAUNCHER_TIMEOUT=180
TARGET="both"
CODEX_BYPASS=0

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -w|--worker)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      WORKER_DIR="$2"
      shift 2
      ;;
    -i|--interval)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      INTERVAL="$2"
      shift 2
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
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET="$2"
      shift 2
      ;;
    --codex-bypass)
      CODEX_BYPASS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
[ -d "$PROJECT_DIR/.superharness" ] || { echo "Missing .superharness in project: $PROJECT_DIR" >&2; exit 1; }
[ -d "$PROJECT_DIR/scripts" ] || { echo "Missing scripts/ in project: $PROJECT_DIR" >&2; exit 1; }

case "$TARGET" in
  both|claude-code|codex-cli) ;;
  *)
    echo "--to must be one of: both, claude-code, codex-cli" >&2
    exit 2
    ;;
esac

case "$INTERVAL" in
  ''|0|*[!0-9]*)
    echo "--interval must be a positive integer" >&2
    exit 2
    ;;
esac

case "$RECOVER_TIMEOUT_MINUTES" in
  ''|*[!0-9]*)
    echo "--recover-timeout-minutes must be a non-negative integer" >&2
    exit 2
    ;;
esac

case "$RECOVER_ACTION" in
  stale|retry) ;;
  *)
    echo "--recover-action must be stale or retry" >&2
    exit 2
    ;;
esac

case "$LAUNCHER_TIMEOUT" in
  ''|*[!0-9]*)
    echo "--launcher-timeout must be a non-negative integer" >&2
    exit 2
    ;;
esac

if [ -z "$WORKER_DIR" ]; then
  WORKER_DIR="$HOME/.superharness-workers/$(basename "$PROJECT_DIR")"
fi
mkdir -p "$WORKER_DIR"
WORKER_DIR="$(cd "$WORKER_DIR" && pwd -P)"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.superharness' \
    --exclude '.venv' \
    --exclude 'node_modules' \
    --exclude '.pytest_cache' \
    "$PROJECT_DIR"/ "$WORKER_DIR"/
else
  find "$WORKER_DIR" -mindepth 1 -maxdepth 1 ! -name '.superharness' -exec rm -rf {} +
  tar -C "$PROJECT_DIR" \
    --exclude='.git' \
    --exclude='.superharness' \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='.pytest_cache' \
    -cf - . | tar -C "$WORKER_DIR" -xf -
fi

if [ -e "$WORKER_DIR/.superharness" ] && [ ! -L "$WORKER_DIR/.superharness" ]; then
  rm -rf "$WORKER_DIR/.superharness"
fi
if [ -L "$WORKER_DIR/.superharness" ]; then
  rm -f "$WORKER_DIR/.superharness"
fi
ln -s "$PROJECT_DIR/.superharness" "$WORKER_DIR/.superharness"

INSTALL_SCRIPT="$PROJECT_DIR/scripts/install-launchd-inbox-watcher.sh"
INSTALL_ARGS=(
  --project "$WORKER_DIR"
  --interval "$INTERVAL"
  --recover-timeout-minutes "$RECOVER_TIMEOUT_MINUTES"
  --recover-action "$RECOVER_ACTION"
  --launcher-timeout "$LAUNCHER_TIMEOUT"
  --to "$TARGET"
  --confirm-non-interactive yes
  --confirm-skip-permissions yes
)
if [ "$CODEX_BYPASS" -eq 1 ]; then
  INSTALL_ARGS+=(--codex-bypass --confirm-codex-bypass yes)
fi
bash "$INSTALL_SCRIPT" "${INSTALL_ARGS[@]}"

WATCHER_CFG="$PROJECT_DIR/.superharness/watcher.yaml"
{
  echo "watcher_project: \"$WORKER_DIR\""
  echo "updated_at: \"$(date -u +%FT%TZ)\""
  echo "interval_seconds: $INTERVAL"
  echo "recover_timeout_minutes: $RECOVER_TIMEOUT_MINUTES"
  echo "recover_action: $RECOVER_ACTION"
  echo "launcher_timeout_seconds: $LAUNCHER_TIMEOUT"
  echo "target: $TARGET"
  if [ "$CODEX_BYPASS" -eq 1 ]; then
    echo "codex_bypass: true"
  else
    echo "codex_bypass: false"
  fi
} > "$WATCHER_CFG"

echo "Watcher worker is ready."
echo "  Source project : $PROJECT_DIR"
echo "  Worker project : $WORKER_DIR"
echo "  Config written : $WATCHER_CFG"
echo "  Interval       : ${INTERVAL}s"
echo "  Recover timeout: ${RECOVER_TIMEOUT_MINUTES}m"
echo "  Recover action: ${RECOVER_ACTION}"
echo "  Launcher timeout: ${LAUNCHER_TIMEOUT}s"
if [ "$CODEX_BYPASS" -eq 1 ]; then
  echo "  Codex bypass  : enabled"
else
  echo "  Codex bypass  : disabled"
fi
