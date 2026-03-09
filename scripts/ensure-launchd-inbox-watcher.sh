#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  ensure-launchd-inbox-watcher.sh --project DIR [--interval SEC] [--to claude-code|codex-cli|both] [--print-only]

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

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Skipped watcher ensure (launchd only): non-macOS platform."
  exit 0
fi

if [ ! -d "$PROJECT_DIR/.superharness" ]; then
  echo "Skipped watcher ensure: .superharness missing in $PROJECT_DIR"
  exit 0
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

case "$PROJECT_DIR" in
  "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*)
    echo "Skipped watcher ensure: protected macOS folder ($PROJECT_DIR)."
    echo "Move project outside Documents/Desktop/Downloads for reliable launchd execution."
    exit 0
    ;;
esac

PROJECT_SLUG="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
LABEL="com.superharness.inbox.${PROJECT_SLUG}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ -f "$PLIST_PATH" ]; then
  echo "Watcher already configured: $LABEL"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$SCRIPT_DIR/install-launchd-inbox-watcher.sh"
[ -x "$INSTALLER" ] || { echo "Missing installer: $INSTALLER" >&2; exit 1; }

args=(--project "$PROJECT_DIR" --interval "$INTERVAL" --to "$TARGET")
if [ "$PRINT_ONLY" -eq 1 ]; then
  args+=(--print-only)
fi

bash "$INSTALLER" "${args[@]}"
