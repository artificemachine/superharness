#!/bin/bash
set -euo pipefail

usage() {
  cat << 'EOF'
Usage:
  install-git-hooks.sh [--force] [--dry-run]

Options:
  -f, --force      Replace existing core.hooksPath if it is already set
  -n, --dry-run    Print planned action without changing git config
  -h, --help       Show this help message and exit
EOF
}

FORCE=0
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    -f|--force)
      FORCE=1
      shift
      ;;
    -n|--dry-run)
      DRY_RUN=1
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

TARGET_HOOKS_PATH=".githooks"
CURRENT_HOOKS_PATH="$(git config --get core.hooksPath || true)"

if [ "$CURRENT_HOOKS_PATH" = "$TARGET_HOOKS_PATH" ]; then
  echo "Local git hooks path already configured: $TARGET_HOOKS_PATH"
  echo "pre-commit runs scripts/check-shell-entrypoints.sh"
  exit 0
fi

if [ -n "$CURRENT_HOOKS_PATH" ] && [ "$FORCE" -ne 1 ]; then
  echo "core.hooksPath is already set to: $CURRENT_HOOKS_PATH"
  echo "Refusing to overwrite without --force."
  exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  if [ -n "$CURRENT_HOOKS_PATH" ] && [ "$FORCE" -eq 1 ]; then
    echo "[dry-run] Would replace core.hooksPath: $CURRENT_HOOKS_PATH -> $TARGET_HOOKS_PATH"
  else
    echo "[dry-run] Would set core.hooksPath: $TARGET_HOOKS_PATH"
  fi
  exit 0
fi

git config core.hooksPath "$TARGET_HOOKS_PATH"
echo "Configured local git hooks path: $TARGET_HOOKS_PATH"
echo "pre-commit now runs scripts/check-shell-entrypoints.sh"
