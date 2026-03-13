#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  doctor.sh [--project DIR] [--check]

Options:
  -p, --project DIR   Project directory to validate (default: current dir)
  --check             Exit with non-zero on any failure or warning (for CI)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR="$(pwd)"
CHECK_MODE=0

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --check)
      CHECK_MODE=1
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

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

failures=0
warns=0
PLATFORM="$(uname -s)"

install_hint() {
  local dep="$1"
  case "$dep" in
    ruby)
      if [ "$PLATFORM" = "Darwin" ]; then
        echo "       brew install ruby"
      else
        echo "       sudo apt install ruby   # or: sudo dnf install ruby"
      fi
      ;;
    python3)
      if [ "$PLATFORM" = "Darwin" ]; then
        echo "       brew install python3"
      else
        echo "       sudo apt install python3   # or: sudo dnf install python3"
      fi
      ;;
    claude)
      echo "       npm i -g @anthropic-ai/claude-code"
      ;;
    codex)
      echo "       npm i -g @openai/codex"
      ;;
  esac
}

check_dep() {
  local dep="$1"
  if command -v "$dep" >/dev/null 2>&1; then
    echo "PASS dep:$dep"
  else
    echo "WARN dep:$dep missing"
    install_hint "$dep"
    warns=$((warns + 1))
  fi
}

echo "superharness doctor"
echo "project: $PROJECT_DIR"

check_dep ruby
check_dep python3
check_dep claude
check_dep codex

HARNESS_DIR="$PROJECT_DIR/.superharness"
if [ -d "$HARNESS_DIR" ]; then
  echo "PASS project:.superharness present"
else
  echo "FAIL project:.superharness missing"
  echo "       Run: superharness init \"Project\" \"Stack\" \"active\""
  failures=$((failures + 1))
fi

case "$PROJECT_DIR" in
  "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*)
    echo "WARN project:path is macOS protected folder (launchd may fail: Operation not permitted)"
    warns=$((warns + 1))
    ;;
esac

for f in contract.yaml ledger.md decisions.yaml failures.yaml; do
  if [ -f "$HARNESS_DIR/$f" ]; then
    echo "PASS file:$f"
  else
    echo "FAIL file:$f missing"
    echo "       Re-initialize: superharness init"
    failures=$((failures + 1))
  fi
done

if [ -d "$HARNESS_DIR/handoffs" ]; then
  echo "PASS dir:handoffs"
else
  echo "FAIL dir:handoffs missing"
  echo "       Run: mkdir -p .superharness/handoffs"
  failures=$((failures + 1))
fi

if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  hooks_path="$(git -C "$PROJECT_DIR" config --get core.hooksPath || true)"
  if [ "$hooks_path" = ".githooks" ]; then
    echo "PASS git:core.hooksPath=.githooks"
  elif [ -n "$hooks_path" ]; then
    echo "WARN git:core.hooksPath=$hooks_path"
    warns=$((warns + 1))
  else
    echo "WARN git:core.hooksPath not set"
    echo "       Run: git config core.hooksPath .githooks"
    warns=$((warns + 1))
  fi
else
  echo "WARN git:not a git repository"
  warns=$((warns + 1))
fi

if [ "$PLATFORM" = "Darwin" ]; then
  slug="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
  label="com.superharness.inbox.${slug}"
  if launchctl list | grep -q "$label"; then
    echo "PASS watcher:$label loaded"
  else
    echo "WARN watcher:$label not loaded"
    echo "       The background watcher is required — would you like to install it? (run: bash scripts/install-launchd-inbox-watcher.sh --project .)"
    echo "       Or use foreground mode instead: superharness watch --foreground --project ."
    warns=$((warns + 1))
  fi
else
  echo "INFO watcher:launchd not available (non-macOS)"
  echo "       Use foreground mode: superharness watch --foreground --project ."
fi

echo "summary: failures=$failures warnings=$warns"
if [ "$failures" -gt 0 ]; then
  echo ""
  echo "→ Fix the failures above, then re-run 'shux doctor'."
  exit 1
fi
if [ "$CHECK_MODE" -eq 1 ] && [ "$warns" -gt 0 ]; then
  exit 1
fi
echo ""
echo "→ Next: run 'shux contract' to see your tasks, or 'shux monitor' to open the dashboard."
