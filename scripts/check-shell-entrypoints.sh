#!/bin/bash
set -euo pipefail

# Keep this list explicit to avoid forcing execute bits on non-entrypoint helpers.
ENTRYPOINT_FILES=(
  "init-project.sh"
  "adapters/claude-code/install.sh"
  "adapters/claude-code/hooks/branch-guard.sh"
  "adapters/claude-code/hooks/ledger-append.sh"
  "adapters/claude-code/hooks/scope-guard.sh"
  "adapters/claude-code/hooks/session-start.sh"
  "scripts/check-shell-entrypoints.sh"
  "scripts/check-contract-hygiene.sh"
  "scripts/delegate-to-claude.sh"
  "scripts/delegate-to-codex.sh"
  "scripts/ensure-launchd-inbox-watcher.sh"
  "scripts/inbox-dispatch.sh"
  "scripts/inbox-enqueue.sh"
  "scripts/inbox-normalize.sh"
  "scripts/inbox-recover-stale.sh"
  "scripts/inbox-watch.sh"
  "scripts/install-launchd-inbox-watcher.sh"
  "scripts/install-git-hooks.sh"
  "scripts/uninstall-launchd-inbox-watcher.sh"
)

HOOK_FILES=(
  ".githooks/pre-commit"
)

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
