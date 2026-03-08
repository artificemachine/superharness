#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  install-launchd-inbox-watcher.sh --project DIR [--interval SEC] [--to claude-code|codex-cli|both] [--print-only]

Options:
  -p, --project DIR   Project directory containing .superharness/ (required)
  -i, --interval SEC  Poll interval in seconds (default: 30)
      --to TARGET     Dispatch target filter (default: both)
      --print-only    Prepare prompts only; do not launch CLIs
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
INTERVAL=30
TARGET="both"
PRINT_ONLY=0

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

if [ ! -d "$PROJECT_DIR/.superharness" ]; then
  echo "Missing .superharness in project: $PROJECT_DIR" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER="$SCRIPT_DIR/inbox-watch.sh"
[ -x "$WATCHER" ] || { echo "Missing watcher script: $WATCHER" >&2; exit 1; }

PROJECT_SLUG="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
LABEL="com.superharness.inbox.${PROJECT_SLUG}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/superharness"
mkdir -p "$PLIST_DIR" "$LOG_DIR"

ARGS=("$WATCHER" "--project" "$PROJECT_DIR" "--to" "$TARGET" "--non-interactive")
if [ "$PRINT_ONLY" -eq 1 ]; then
  ARGS=("$WATCHER" "--project" "$PROJECT_DIR" "--to" "$TARGET" "--print-only")
fi

{
  echo "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
  echo "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">"
  echo "<plist version=\"1.0\">"
  echo "  <dict>"
  echo "    <key>Label</key>"
  echo "    <string>${LABEL}</string>"
  echo "    <key>ProgramArguments</key>"
  echo "    <array>"
  echo "      <string>/bin/bash</string>"
  for arg in "${ARGS[@]}"; do
    echo "      <string>${arg}</string>"
  done
  echo "    </array>"
  echo "    <key>RunAtLoad</key>"
  echo "    <true/>"
  echo "    <key>StartInterval</key>"
  echo "    <integer>${INTERVAL}</integer>"
  echo "    <key>StandardOutPath</key>"
  echo "    <string>${LOG_DIR}/${LABEL}.out.log</string>"
  echo "    <key>StandardErrorPath</key>"
  echo "    <string>${LOG_DIR}/${LABEL}.err.log</string>"
  echo "  </dict>"
  echo "</plist>"
} > "$PLIST_PATH"

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed launchd inbox watcher:"
echo "  Label: $LABEL"
echo "  Plist: $PLIST_PATH"
echo "  Interval: ${INTERVAL}s"
echo "  Target: $TARGET"
if [ "$PRINT_ONLY" -eq 1 ]; then
  echo "  Mode: print-only"
else
  echo "  Mode: non-interactive"
fi
echo "  Logs: $LOG_DIR/${LABEL}.out.log"
