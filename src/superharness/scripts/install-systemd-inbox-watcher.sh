#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  install-systemd-inbox-watcher.sh --project DIR [--interval SEC] [--to claude-code|codex-cli|both] [--print-only] [--codex-bypass] [--recover-timeout-minutes N] [--recover-action stale|retry]

Installs a systemd user service and timer for the superharness inbox watcher.
Mirrors install-launchd-inbox-watcher.sh for Linux.

Options:
  -p, --project DIR   Project directory containing .superharness/ (required)
  -i, --interval SEC  Poll interval in seconds (default: 15)
      --to TARGET     Dispatch target filter (default: both)
      --print-only    Prepare prompts only; do not launch CLIs
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
      --recover-timeout-minutes N  Mark launched rows stale/retry after N minutes (default: 20)
      --recover-action MODE  stale or retry (default: retry)
  -h, --help          Show this help message and exit

Environment:
  CONFIRM_NON_INTERACTIVE=yes   Skip non-interactive confirmation prompt
USAGE
}

PROJECT_DIR=""
INTERVAL=15
TARGET="both"
PRINT_ONLY=0
CODEX_BYPASS=0
RECOVER_TIMEOUT_MINUTES=20
RECOVER_ACTION=retry

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -i|--interval)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      INTERVAL="$2"
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
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

case "$TARGET" in
  both|claude-code|codex-cli) ;;
  *)
    echo "--to must be one of: both, claude-code, codex-cli" >&2
    exit 2
    ;;
esac

case "$INTERVAL" in
  ''|*[!0-9]*|0)
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

if [ ! -d "$PROJECT_DIR/.superharness" ]; then
  echo "Missing .superharness in project: $PROJECT_DIR" >&2
  exit 1
fi

# Confirmation gate
if [ "$PRINT_ONLY" -eq 0 ]; then
  CONFIRM="${CONFIRM_NON_INTERACTIVE:-}"
  if [ "$CONFIRM" != "yes" ] && [ "$CONFIRM" != "YES" ]; then
    if [ -t 0 ]; then
      printf 'Allow unattended non-interactive watcher? [y/N]: ' >&2
      read -r answer
      case "$answer" in
        y|Y|yes|YES) ;;
        *) echo "Aborted." >&2; exit 1 ;;
      esac
    else
      echo "Refusing unattended install without CONFIRM_NON_INTERACTIVE=yes" >&2
      exit 1
    fi
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER="$SCRIPT_DIR/inbox-watch.sh"
[ -f "$WATCHER" ] || { echo "Missing watcher script: $WATCHER" >&2; exit 1; }

# Resolve python3 binary
PYTHON3_BIN="$(command -v python3 2>/dev/null || true)"
if [ -z "$PYTHON3_BIN" ]; then
  echo "python3 not found on PATH" >&2
  exit 1
fi

PROJECT_SLUG="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-' | sed 's/-$//')"
UNIT_NAME="superharness-inbox-${PROJECT_SLUG}"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$UNIT_DIR/${UNIT_NAME}.service"
TIMER_FILE="$UNIT_DIR/${UNIT_NAME}.timer"
LOG_DIR="$HOME/.local/share/superharness/logs"
mkdir -p "$UNIT_DIR" "$LOG_DIR"

# Build watcher arguments
WATCHER_ARGS="$WATCHER --project $PROJECT_DIR --to $TARGET --non-interactive"
if [ "$PRINT_ONLY" -eq 1 ]; then
  WATCHER_ARGS="$WATCHER --project $PROJECT_DIR --to $TARGET --print-only"
fi
WATCHER_ARGS="$WATCHER_ARGS --recover-timeout-minutes $RECOVER_TIMEOUT_MINUTES --recover-action $RECOVER_ACTION"
if [ "$CODEX_BYPASS" -eq 1 ]; then
  WATCHER_ARGS="$WATCHER_ARGS --codex-bypass"
fi

# Build environment block
ENV_BLOCK="Environment=SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES"
if [ "$PRINT_ONLY" -eq 0 ]; then
  ENV_BLOCK="$ENV_BLOCK
Environment=SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES"
fi
if [ "$CODEX_BYPASS" -eq 1 ]; then
  ENV_BLOCK="$ENV_BLOCK
Environment=SUPERHARNESS_CONFIRM_CODEX_BYPASS=YES"
fi

# Write service unit
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=superharness inbox watcher for ${PROJECT_SLUG}

[Service]
Type=oneshot
ExecStart=/bin/bash $WATCHER_ARGS
${ENV_BLOCK}
StandardOutput=append:${LOG_DIR}/${UNIT_NAME}.out.log
StandardError=append:${LOG_DIR}/${UNIT_NAME}.err.log
EOF

# Write timer unit
cat > "$TIMER_FILE" << EOF
[Unit]
Description=superharness inbox watcher timer for ${PROJECT_SLUG}

[Timer]
OnBootSec=10
OnUnitActiveSec=${INTERVAL}
Unit=${UNIT_NAME}.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable "${UNIT_NAME}.timer"
systemctl --user start "${UNIT_NAME}.timer"

echo "Installed systemd inbox watcher:"
echo "  Service: $SERVICE_FILE"
echo "  Timer:   $TIMER_FILE"
echo "  Interval: ${INTERVAL}s"
echo "  Recover timeout: ${RECOVER_TIMEOUT_MINUTES}m"
echo "  Recover action: ${RECOVER_ACTION}"
echo "  Target: $TARGET"
if [ "$PRINT_ONLY" -eq 1 ]; then
  echo "  Mode: print-only"
else
  echo "  Mode: non-interactive"
fi
if [ "$CODEX_BYPASS" -eq 1 ]; then
  echo "  Codex bypass: enabled"
fi
echo "  Logs: $LOG_DIR/${UNIT_NAME}.out.log"
echo ""
echo "Commands:"
echo "  systemctl --user status ${UNIT_NAME}.timer"
echo "  journalctl --user -u ${UNIT_NAME}.service"
echo "  systemctl --user stop ${UNIT_NAME}.timer"
echo "  systemctl --user disable ${UNIT_NAME}.timer"
