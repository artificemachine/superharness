#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  install-launchd-inbox-watcher.sh --project DIR [--interval SEC] [--to claude-code|codex-cli|both] [--print-only] [--codex-bypass] [--confirm-non-interactive yes|no] [--allow-protected-path]

Options:
  -p, --project DIR   Project directory containing .superharness/ (required)
  -i, --interval SEC  Poll interval in seconds (default: 30)
      --to TARGET     Dispatch target filter (default: both)
      --print-only    Prepare prompts only; do not launch CLIs
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
      --confirm-non-interactive yes|no  Set SUPERHARNESS_CONFIRM_NON_INTERACTIVE explicitly
      --allow-protected-path  Allow install for macOS protected folders (Documents/Desktop/Downloads)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
INTERVAL=30
TARGET="both"
PRINT_ONLY=0
CODEX_BYPASS=0
CONFIRM_NON_INTERACTIVE=""
ALLOW_PROTECTED_PATH=0

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
    --confirm-non-interactive)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      CONFIRM_NON_INTERACTIVE="$2"
      shift 2
      ;;
    --allow-protected-path)
      ALLOW_PROTECTED_PATH=1
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
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
case "$TARGET" in
  both|claude-code|codex-cli) ;;
  *)
    echo "--to must be one of: both, claude-code, codex-cli" >&2
    exit 2
    ;;
esac

case "$CONFIRM_NON_INTERACTIVE" in
  ""|yes|no) ;;
  *)
    echo "--confirm-non-interactive must be yes or no" >&2
    exit 2
    ;;
esac

if [ "$(uname -s)" = "Darwin" ] && [ "$ALLOW_PROTECTED_PATH" -ne 1 ]; then
  case "$PROJECT_DIR" in
    "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*)
      echo "Refusing launchd install for protected macOS folder: $PROJECT_DIR" >&2
      echo "Reason: launchd may fail with 'Operation not permitted' under TCC-protected paths." >&2
      echo "Fixes:" >&2
      echo "  1) Move project to non-protected path (e.g. ~/DevOpsCelstn/...)" >&2
      echo "  2) Re-run install-launchd-inbox-watcher.sh" >&2
      echo "  3) Or bypass with --allow-protected-path (not recommended)" >&2
      exit 1
      ;;
  esac
fi

if [ ! -d "$PROJECT_DIR/.superharness" ]; then
  echo "Missing .superharness in project: $PROJECT_DIR" >&2
  exit 1
fi

if [ -z "$CONFIRM_NON_INTERACTIVE" ]; then
  if [ -t 0 ]; then
    printf 'Allow unattended non-interactive launches (sets SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES)? [y/N]: ' >&2
    read -r ans
    case "$ans" in
      y|Y|yes|YES) CONFIRM_NON_INTERACTIVE="yes" ;;
      *) CONFIRM_NON_INTERACTIVE="no" ;;
    esac
  else
    # Non-interactive install defaults to current behavior to avoid breaking automation.
    CONFIRM_NON_INTERACTIVE="yes"
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER="$SCRIPT_DIR/inbox-watch.sh"
[ -x "$WATCHER" ] || { echo "Missing watcher script: $WATCHER" >&2; exit 1; }

# launchd does not always inherit interactive shell PATH (nvm/homebrew/local bins).
BASE_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
EXTRA_PATHS=""
for bin in codex claude ruby python3; do
  if command -v "$bin" >/dev/null 2>&1; then
    dir="$(dirname "$(command -v "$bin")")"
    case ":$BASE_PATH:$EXTRA_PATHS:" in
      *":$dir:"*) ;;
      *) EXTRA_PATHS="${EXTRA_PATHS:+$EXTRA_PATHS:}$dir" ;;
    esac
  fi
done
LAUNCHD_PATH="$BASE_PATH"
if [ -n "$EXTRA_PATHS" ]; then
  LAUNCHD_PATH="$LAUNCHD_PATH:$EXTRA_PATHS"
fi

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
if [ "$CODEX_BYPASS" -eq 1 ]; then
  ARGS+=("--codex-bypass")
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
  echo "    <key>EnvironmentVariables</key>"
  echo "    <dict>"
  echo "      <key>PATH</key>"
  echo "      <string>${LAUNCHD_PATH}</string>"
  echo "      <key>SUPERHARNESS_CONFIRM_NON_INTERACTIVE</key>"
  if [ "$CONFIRM_NON_INTERACTIVE" = "yes" ]; then
    echo "      <string>YES</string>"
  else
    echo "      <string>NO</string>"
  fi
  echo "    </dict>"
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
if [ "$CODEX_BYPASS" -eq 1 ]; then
  echo "  Codex bypass: enabled"
fi
if [ "$CONFIRM_NON_INTERACTIVE" = "yes" ]; then
  echo "  Non-interactive confirmation: enabled (YES)"
else
  echo "  Non-interactive confirmation: disabled (NO)"
fi
echo "  PATH: $LAUNCHD_PATH"
echo "  Logs: $LOG_DIR/${LABEL}.out.log"
