#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  uninstall-launchd-inbox-watcher.sh --project DIR

Options:
  -p, --project DIR   Project directory used during install (required)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
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

PROJECT_SLUG="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
LABEL="com.superharness.inbox.${PROJECT_SLUG}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "Uninstalled launchd inbox watcher:"
echo "  Label: $LABEL"
echo "  Removed: $PLIST_PATH"
