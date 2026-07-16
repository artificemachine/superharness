#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  install-launchd-inbox-watcher.sh --project DIR [--interval SEC] [--to TARGET|both] [--print-only] [--codex-bypass] [--recover-timeout-minutes N] [--recover-action stale|retry] [--launcher-timeout SECONDS] [--confirm-non-interactive yes|no] [--confirm-skip-permissions yes|no] [--confirm-codex-bypass yes|no] [--allow-protected-path]

Options:
  -p, --project DIR   Project directory containing .superharness/ (required)
  -i, --interval SEC  Poll interval in seconds (default: 15)
      --to TARGET     Dispatch target filter (default: both)
      --print-only    Prepare prompts only; do not launch CLIs
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
      --recover-timeout-minutes N  Mark launched rows stale/retry after N minutes (default: 20)
      --recover-action MODE  stale or retry (default: retry)
      --launcher-timeout SECONDS  Kill launcher after SECONDS (default: 0 = no timeout)
      --confirm-non-interactive yes|no  Set SUPERHARNESS_CONFIRM_NON_INTERACTIVE explicitly
      --confirm-skip-permissions yes|no  Set SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS explicitly
      --confirm-codex-bypass yes|no  Set SUPERHARNESS_CONFIRM_CODEX_BYPASS explicitly
      --allow-protected-path  Allow install for macOS protected folders (Documents/Desktop/Downloads)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
INTERVAL=15
TARGET="both"
PRINT_ONLY=0
CODEX_BYPASS=0
RECOVER_TIMEOUT_MINUTES=20
RECOVER_ACTION=retry
LAUNCHER_TIMEOUT=0
CONFIRM_NON_INTERACTIVE=""
CONFIRM_SKIP_PERMISSIONS=""
CONFIRM_CODEX_BYPASS=""
ALLOW_PROTECTED_PATH=0

xml_escape() {
  local escaped="${1//&/&amp;}"
  escaped="${escaped//</&lt;}"
  escaped="${escaped//>/&gt;}"
  escaped="${escaped//\"/&quot;}"
  escaped="${escaped//\'/&apos;}"
  printf '%s' "$escaped"
}

prompt_confirmation() {
  local prompt="$1"
  local answer
  if [ ! -t 0 ]; then
    return 1
  fi
  printf '%s [y/N]: ' "$prompt" >&2
  read -r answer
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

resolve_confirmation_flag() {
  local flag_name="$1"
  local prompt="$2"
  local current_value="$3"

  case "$current_value" in
    yes|no)
      printf '%s' "$current_value"
      return 0
      ;;
    "")
      if prompt_confirmation "$prompt"; then
        printf 'yes'
      else
        printf 'no'
      fi
      return 0
      ;;
    *)
      echo "Internal error: unsupported confirmation state for $flag_name" >&2
      exit 2
      ;;
  esac
}

require_confirmation_yes() {
  local flag_name="$1"
  local flag_value="$2"
  local guidance="$3"
  if [ "$flag_value" != "yes" ]; then
    echo "$guidance" >&2
    exit 1
  fi
}

plist_key() {
  printf '      <key>%s</key>\n' "$(xml_escape "$1")"
}

plist_string() {
  printf '      <string>%s</string>\n' "$(xml_escape "$1")"
}

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
    --launcher-timeout)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      LAUNCHER_TIMEOUT="$2"
      shift 2
      ;;
    --confirm-non-interactive)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      CONFIRM_NON_INTERACTIVE="$2"
      shift 2
      ;;
    --confirm-skip-permissions)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      CONFIRM_SKIP_PERMISSIONS="$2"
      shift 2
      ;;
    --confirm-codex-bypass)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      CONFIRM_CODEX_BYPASS="$2"
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
# Validation: 'both' is always valid; others are validated by the watcher-worker command at runtime.

# watcher-worker.py installs against a worker COPY of the project, with
# .superharness/ symlinked back to the real source project (so ticks share
# one contract/state directory instead of forking it). Without this, the
# watcher process resolves its XDG state.db path from the worker dir's own
# (different) absolute path, finds nothing there, and falls back through
# get_connection()'s legacy-path branch — which, via the symlink, writes a
# *second* state.sqlite3 into the SAME .superharness/ dir as the source
# project's XDG db, recreating a split-brain every tick. Resolve the real
# source dir here and pass it through SUPERHARNESS_STATE_PROJECT so every
# tick's state read/write targets the one XDG db the source project uses
# (the same mechanism worktree dispatch already relies on — see db.py's
# get_connection() docstring). No-op (STATE_PROJECT_DIR == PROJECT_DIR) when
# .superharness isn't a symlink, e.g. installing directly against a real
# project without going through watcher-worker.
if [ -L "$PROJECT_DIR/.superharness" ]; then
  STATE_PROJECT_DIR="$(python3 -c "import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))" "$PROJECT_DIR/.superharness")"
else
  STATE_PROJECT_DIR="$PROJECT_DIR"
fi

case "$CONFIRM_NON_INTERACTIVE" in
  ""|yes|no) ;;
  *)
    echo "--confirm-non-interactive must be yes or no" >&2
    exit 2
    ;;
esac

case "$CONFIRM_SKIP_PERMISSIONS" in
  ""|yes|no) ;;
  *)
    echo "--confirm-skip-permissions must be yes or no" >&2
    exit 2
    ;;
esac

case "$CONFIRM_CODEX_BYPASS" in
  ""|yes|no) ;;
  *)
    echo "--confirm-codex-bypass must be yes or no" >&2
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

case "$LAUNCHER_TIMEOUT" in
  ''|*[!0-9]*)
    echo "--launcher-timeout must be a non-negative integer" >&2
    exit 2
    ;;
esac

if [ "$(uname -s)" = "Darwin" ] && [ "$ALLOW_PROTECTED_PATH" -ne 1 ]; then
  case "$PROJECT_DIR" in
    "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*)
      echo "Refusing launchd install for protected macOS folder: $PROJECT_DIR" >&2
      echo "Reason: launchd may fail with 'Operation not permitted' under TCC-protected paths." >&2
      echo "Fixes:" >&2
      echo "  1) Move project to non-protected path (e.g. ~/Projects/...)" >&2
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

if [ "$PRINT_ONLY" -eq 0 ]; then
  CONFIRM_NON_INTERACTIVE="$(
    resolve_confirmation_flag \
      "SUPERHARNESS_CONFIRM_NON_INTERACTIVE" \
      "Allow unattended non-interactive launches (sets SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES)?" \
      "$CONFIRM_NON_INTERACTIVE"
  )"
  require_confirmation_yes \
    "SUPERHARNESS_CONFIRM_NON_INTERACTIVE" \
    "$CONFIRM_NON_INTERACTIVE" \
    "Refusing to install unattended watcher without --confirm-non-interactive yes."

  case "$TARGET" in
    both|claude-code)
      CONFIRM_SKIP_PERMISSIONS="$(
        resolve_confirmation_flag \
          "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS" \
          "Allow Claude to run unattended with --dangerously-skip-permissions (sets SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES)?" \
          "$CONFIRM_SKIP_PERMISSIONS"
      )"
      require_confirmation_yes \
        "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS" \
        "$CONFIRM_SKIP_PERMISSIONS" \
        "Refusing to install Claude unattended watcher without --confirm-skip-permissions yes."
      ;;
  esac

  if [ "$CODEX_BYPASS" -eq 1 ]; then
    CONFIRM_CODEX_BYPASS="$(
      resolve_confirmation_flag \
        "SUPERHARNESS_CONFIRM_CODEX_BYPASS" \
        "Allow Codex to run unattended with --dangerously-bypass-approvals-and-sandbox (sets SUPERHARNESS_CONFIRM_CODEX_BYPASS=YES)?" \
        "$CONFIRM_CODEX_BYPASS"
    )"
    require_confirmation_yes \
      "SUPERHARNESS_CONFIRM_CODEX_BYPASS" \
      "$CONFIRM_CODEX_BYPASS" \
      "Refusing to install Codex bypass watcher without --confirm-codex-bypass yes."
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER="$SCRIPT_DIR/inbox-watch.sh"
[ -x "$WATCHER" ] || { echo "Missing watcher script: $WATCHER" >&2; exit 1; }

# launchd does not always inherit interactive shell PATH (nvm/homebrew/local bins).
BASE_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
EXTRA_PATHS=""
for bin in codex claude gemini python3; do
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

# Resolve absolute python3 path to avoid pyenv shim resolution failure under launchd.
# launchd does not run pyenv init, so shims cannot resolve the active version without
# PYENV_ROOT/PYENV_VERSION being set. Pinning the real binary sidesteps this entirely.
_resolve_python_bin() {
  local bin="$1"
  case "$bin" in
    */.pyenv/shims/*)
      "$bin" -c 'import sys; print(sys.executable)' 2>/dev/null
      ;;
    *)
      echo "$bin"
      ;;
  esac
}

PYTHON3_RESOLVED=""
# Explicit override wins when valid.
if [ -n "${SUPERHARNESS_PYTHON:-}" ]; then
  _candidate="$(_resolve_python_bin "$SUPERHARNESS_PYTHON")"
  if [ -n "$_candidate" ] && "$_candidate" -c "import superharness.engine.inbox" 2>/dev/null; then
    PYTHON3_RESOLVED="$_candidate"
  else
    echo "warning: SUPERHARNESS_PYTHON is set but cannot import superharness.engine.inbox: ${SUPERHARNESS_PYTHON}" >&2
  fi
fi

if [ -z "$PYTHON3_RESOLVED" ] && command -v python3 >/dev/null 2>&1; then
  _candidate="$(_resolve_python_bin "$(command -v python3)")"
  if [ -n "$_candidate" ] && "$_candidate" -c "import superharness.engine.inbox" 2>/dev/null; then
    PYTHON3_RESOLVED="$_candidate"
  fi
fi

# If the default python3 does not have superharness, search common candidates.
if [ -z "$PYTHON3_RESOLVED" ]; then
  for _try in python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$_try" >/dev/null 2>&1; then
      _candidate="$(_resolve_python_bin "$(command -v "$_try")")"
      if [ -n "$_candidate" ] && "$_candidate" -c "import superharness.engine.inbox" 2>/dev/null; then
        PYTHON3_RESOLVED="$_candidate"
        echo "note: pinning $PYTHON3_RESOLVED (default python3 does not have superharness)"
        break
      fi
    fi
  done
fi

if [ -z "$PYTHON3_RESOLVED" ]; then
  echo "warning: could not find a python3 with superharness installed — watcher may fail" >&2
fi

PROJECT_SLUG="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-' | sed 's/-$//')"
LABEL="com.superharness.inbox.${PROJECT_SLUG}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/superharness"
mkdir -p "$PLIST_DIR" "$LOG_DIR"

ARGS=("$WATCHER" "--project" "$PROJECT_DIR" "--to" "$TARGET" "--non-interactive")
if [ "$PRINT_ONLY" -eq 1 ]; then
  ARGS=("$WATCHER" "--project" "$PROJECT_DIR" "--to" "$TARGET" "--print-only")
fi
ARGS+=("--recover-timeout-minutes" "$RECOVER_TIMEOUT_MINUTES")
ARGS+=("--recover-action" "$RECOVER_ACTION")
if [ "$LAUNCHER_TIMEOUT" -gt 0 ]; then
  ARGS+=("--launcher-timeout" "$LAUNCHER_TIMEOUT")
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
  printf '    <string>%s</string>\n' "$(xml_escape "$LABEL")"
  echo "    <key>ProgramArguments</key>"
  echo "    <array>"
  echo "      <string>/bin/bash</string>"
  for arg in "${ARGS[@]}"; do
    plist_string "$arg"
  done
  echo "    </array>"
  echo "    <key>RunAtLoad</key>"
  echo "    <true/>"
  echo "    <key>StartInterval</key>"
  printf '    <integer>%s</integer>\n' "$INTERVAL"
  echo "    <key>KeepAlive</key>"
  echo "    <dict>"
  echo "      <key>SuccessfulExit</key>"
  echo "      <false/>"
  echo "    </dict>"
  echo "    <key>EnvironmentVariables</key>"
  echo "    <dict>"
  plist_key "PATH"
  plist_string "$LAUNCHD_PATH"
  plist_key "SUPERHARNESS_STATE_PROJECT"
  plist_string "$STATE_PROJECT_DIR"
  plist_key "SUPERHARNESS_CONFIRM_NON_INTERACTIVE"
  if [ "$CONFIRM_NON_INTERACTIVE" = "yes" ]; then
    plist_string "YES"
  else
    plist_string "NO"
  fi
  plist_key "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS"
  if [ "$CONFIRM_SKIP_PERMISSIONS" = "yes" ]; then
    plist_string "YES"
  else
    plist_string "NO"
  fi
  plist_key "SUPERHARNESS_CONFIRM_CODEX_BYPASS"
  if [ "$CONFIRM_CODEX_BYPASS" = "yes" ]; then
    plist_string "YES"
  else
    plist_string "NO"
  fi
  if [ -n "$PYTHON3_RESOLVED" ]; then
    plist_key "SUPERHARNESS_PYTHON"
    plist_string "$PYTHON3_RESOLVED"
  fi
  echo "    </dict>"
  echo "    <key>StandardOutPath</key>"
  printf '    <string>%s</string>\n' "$(xml_escape "${LOG_DIR}/${LABEL}.out.log")"
  echo "    <key>StandardErrorPath</key>"
  printf '    <string>%s</string>\n' "$(xml_escape "${LOG_DIR}/${LABEL}.err.log")"
  echo "  </dict>"
  echo "</plist>"
} > "$PLIST_PATH"

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed launchd inbox watcher:"
echo "  Label: $LABEL"
echo "  Plist: $PLIST_PATH"
echo "  Interval: ${INTERVAL}s"
echo "  Recover timeout: ${RECOVER_TIMEOUT_MINUTES}m"
echo "  Recover action: ${RECOVER_ACTION}"
if [ "$LAUNCHER_TIMEOUT" -gt 0 ]; then
  echo "  Launcher timeout: ${LAUNCHER_TIMEOUT}s"
else
  echo "  Launcher timeout: disabled"
fi
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
if [ "$CONFIRM_SKIP_PERMISSIONS" = "yes" ]; then
  echo "  Claude skip-permissions confirmation: enabled (YES)"
elif [ "$PRINT_ONLY" -eq 0 ] && { [ "$TARGET" = "both" ] || [ "$TARGET" = "claude-code" ]; }; then
  echo "  Claude skip-permissions confirmation: disabled (NO)"
fi
if [ "$CONFIRM_CODEX_BYPASS" = "yes" ]; then
  echo "  Codex bypass confirmation: enabled (YES)"
elif [ "$CODEX_BYPASS" -eq 1 ]; then
  echo "  Codex bypass confirmation: disabled (NO)"
fi
echo "  PATH: $LAUNCHD_PATH"
echo "  Logs: $LOG_DIR/${LABEL}.out.log"
