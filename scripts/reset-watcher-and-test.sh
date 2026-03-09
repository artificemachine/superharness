#!/bin/bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  reset-watcher-and-test.sh --project DIR [--task TASK_ID] [--to TARGET] [--interval SEC]

Options:
  -p, --project DIR   Project path (required)
  -t, --task TASK_ID  Task id to enqueue for test (default: mcp-docs)
      --to TARGET     claude-code|codex-cli|both (default: both)
  -i, --interval SEC  launchd poll interval (default: 30)
  -h, --help          Show this help message
USAGE
}

PROJECT_DIR=""
TASK_ID="mcp-docs"
TARGET="both"
INTERVAL="30"

while [ $# -gt 0 ]; do
  case "$1" in
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
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET="$2"
      shift 2
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
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }
case "$TARGET" in
  claude-code|codex-cli|both) ;;
  *)
    echo "--to must be claude-code|codex-cli|both" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

INSTALL="$ROOT_DIR/scripts/install-launchd-inbox-watcher.sh"
UNINSTALL="$ROOT_DIR/scripts/uninstall-launchd-inbox-watcher.sh"
WRAPPER="$ROOT_DIR/superharness"

[ -x "$INSTALL" ] || { echo "Missing installer: $INSTALL" >&2; exit 1; }
[ -x "$UNINSTALL" ] || { echo "Missing uninstaller: $UNINSTALL" >&2; exit 1; }
[ -x "$WRAPPER" ] || { echo "Missing wrapper: $WRAPPER" >&2; exit 1; }
[ -d "$PROJECT_DIR/.superharness" ] || { echo "Missing .superharness in project: $PROJECT_DIR" >&2; exit 1; }

echo "==> Installing wrapper into ~/.local/bin"
bash "$WRAPPER" install-wrapper >/dev/null || true
hash -r || true

echo "==> Reinstalling launchd watcher"
bash "$UNINSTALL" --project "$PROJECT_DIR" >/dev/null || true
bash "$INSTALL" --project "$PROJECT_DIR" --to "$TARGET" --interval "$INTERVAL"

LABEL="com.superharness.inbox.$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
OUT_LOG="$HOME/Library/Logs/superharness/${LABEL}.out.log"
ERR_LOG="$HOME/Library/Logs/superharness/${LABEL}.err.log"

echo "==> Restarting launchd job"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "==> Clearing old logs"
: > "$OUT_LOG"
: > "$ERR_LOG"

echo "==> Enqueueing test task"
"$WRAPPER" enqueue --project "$PROJECT_DIR" --to codex-cli --task "$TASK_ID" --priority 1 || true

echo "==> Verification"
launchctl list | rg "$LABEL" || true
echo "--- plist path/env ---"
plutil -p "$PLIST" | rg "ProgramArguments|EnvironmentVariables|PATH|inbox-watch" || true
echo "--- out log (tail) ---"
tail -n 40 "$OUT_LOG" || true
echo "--- err log (tail) ---"
tail -n 40 "$ERR_LOG" || true

echo
echo "Done. Watcher reset workflow complete for: $PROJECT_DIR"
