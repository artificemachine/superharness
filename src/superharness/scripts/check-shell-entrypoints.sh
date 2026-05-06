#!/bin/bash
set -euo pipefail

# Keep this list explicit to avoid forcing execute bits on non-entrypoint helpers.
ENTRYPOINT_FILES=(
  "adapters/claude-code/install.sh"
  "adapters/claude-code/hooks/branch-guard.sh"
  "adapters/claude-code/hooks/ledger-append.sh"
  "adapters/claude-code/hooks/scope-guard.sh"
  "adapters/claude-code/hooks/session-start.sh"
  "adapters/claude-code/hooks/session-stop.sh"
  "src/superharness/scripts/check-shell-entrypoints.sh"
  "src/superharness/scripts/check-contract-hygiene.sh"
  "src/superharness/scripts/contract-today.sh"
  "src/superharness/scripts/delegate-task.sh"
  "src/superharness/scripts/delegate-to-claude.sh"
  "src/superharness/scripts/delegate-to-codex.sh"
  "src/superharness/scripts/delegate-to-gemini.sh"
  "src/superharness/scripts/delegate-to-opencode.sh"
  "src/superharness/scripts/ensure-launchd-inbox-watcher.sh"
  "src/superharness/scripts/inbox-dispatch.sh"
  "src/superharness/scripts/inbox-deadline-check.sh"
  "src/superharness/scripts/inbox-watch.sh"
  "src/superharness/scripts/install-remote.sh"
  "src/superharness/scripts/install-launchd-inbox-watcher.sh"
  "src/superharness/scripts/install-systemd-inbox-watcher.sh"
  "src/superharness/scripts/install-git-hooks.sh"
  "src/superharness/scripts/task.sh"
  "src/superharness/scripts/uninstall-launchd-inbox-watcher.sh"
  "src/superharness/scripts/check-changelog-append-only.sh"
  "src/superharness/scripts/reset-watcher-and-test.sh"
  "src/superharness/scripts/status.sh"
  "src/superharness/scripts/notify.sh"
  "src/superharness/scripts/worktree.sh"
  "src/superharness/scripts/demo.sh"
  "src/superharness/scripts/heartbeat.sh"
  "src/superharness/scripts/init-project.sh"
  "cli/recall.sh"
  "cli/status.sh"
  "src/superharness/adapters/claude-code/install.sh"
  "src/superharness/adapters/claude-code/hooks/branch-guard.sh"
  "src/superharness/adapters/claude-code/hooks/ledger-append.sh"
  "src/superharness/adapters/claude-code/hooks/scope-guard.sh"
  "src/superharness/adapters/claude-code/hooks/session-start.sh"
  "src/superharness/adapters/claude-code/hooks/session-stop.sh"
)

HOOK_FILES=(
  ".githooks/pre-commit"
)

usage() {
  cat <<'USAGE'
Usage: check-shell-entrypoints.sh [--list-entrypoints|--list-hooks|--list-all]

Validates configured shell entrypoints/hooks for:
  - shebang presence
  - executable mode
  - bash syntax
  - allowlist drift against tracked executable files

Optional listing modes:
  --list-entrypoints  Print entrypoint files (one per line) and exit
  --list-hooks        Print hook files (one per line) and exit
  --list-all          Print entrypoints and hooks (one per line) and exit
  -h, --help          Show this help message
USAGE
}

list_entries() {
  local item
  for item in "$@"; do
    echo "$item"
  done
}

if [ $# -gt 0 ]; then
  case "$1" in
    --list-entrypoints)
      list_entries "${ENTRYPOINT_FILES[@]}"
      exit 0
      ;;
    --list-hooks)
      list_entries "${HOOK_FILES[@]}"
      exit 0
      ;;
    --list-all)
      list_entries "${ENTRYPOINT_FILES[@]}"
      list_entries "${HOOK_FILES[@]}"
      exit 0
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
fi

if [ ${#ENTRYPOINT_FILES[@]} -eq 0 ] && [ ${#HOOK_FILES[@]} -eq 0 ]; then
  echo "No shell entrypoints/hooks configured for validation."
  exit 0
fi

failures=0

check_script_file() {
  local file="$1"
  local label="$2"

  if [ ! -f "$file" ]; then
    echo "[FAIL] Missing $label file: $file"
    failures=$((failures + 1))
    return
  fi

  local first_line
  first_line=$(sed -n '1p' "$file")
  if [[ "$first_line" != "#!"* ]]; then
    echo "[FAIL] Missing shebang: $file"
    failures=$((failures + 1))
  fi

  local mode
  mode=$(git ls-files -s -- "$file" | awk '{print $1}')
  if [ -n "$mode" ]; then
    if [ "$mode" != "100755" ]; then
      echo "[FAIL] Non-executable git mode ($mode): $file (expected 100755)"
      failures=$((failures + 1))
    fi
  elif [ ! -x "$file" ]; then
    echo "[FAIL] File is not executable: $file"
    failures=$((failures + 1))
  fi

  if ! bash -n "$file"; then
    echo "[FAIL] Bash syntax error: $file"
    failures=$((failures + 1))
  fi
}

for file in "${ENTRYPOINT_FILES[@]}"; do
  check_script_file "$file" "entrypoint"
done

for file in "${HOOK_FILES[@]}"; do
  check_script_file "$file" "hook"
done

is_in_list() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [ "$item" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

# Detect allowlist drift: every tracked executable .sh and .githooks file must be explicitly listed.
while IFS= read -r file; do
  if [ -n "$file" ] && ! is_in_list "$file" "${ENTRYPOINT_FILES[@]}"; then
    echo "[FAIL] Executable shell file missing from ENTRYPOINT_FILES allowlist: $file"
    failures=$((failures + 1))
  fi
done < <(git ls-files -s '*.sh' | awk '$1=="100755"{print $4}')

while IFS= read -r file; do
  if [ -n "$file" ] && ! is_in_list "$file" "${HOOK_FILES[@]}"; then
    echo "[FAIL] Executable hook file missing from HOOK_FILES allowlist: $file"
    failures=$((failures + 1))
  fi
done < <(git ls-files -s '.githooks/*' | awk '$1=="100755"{print $4}')

if [ "$failures" -ne 0 ]; then
  echo ""
  echo "Shell entrypoint guard failed with $failures issue(s)."
  echo "Fixes:"
  echo "  chmod +x <file>"
  echo "  Ensure first line starts with #!"
  echo "  Resolve bash syntax errors"
  echo "  Add new executable entrypoints/hooks to this script allowlist"
  exit 1
fi

total=$(( ${#ENTRYPOINT_FILES[@]} + ${#HOOK_FILES[@]} ))
echo "Shell entrypoint guard passed for $total file(s)."
