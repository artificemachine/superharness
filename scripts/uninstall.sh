#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  uninstall.sh [--dry-run] [--all]

Removes superharness system-level artifacts (launchd plists, wrapper symlink).
Does NOT remove per-project .superharness/ directories.

Options:
  --dry-run   Show what would be removed without making changes
  --all       Remove all known artifacts (default: prompt per item)
  -h, --help  Show this help message and exit
USAGE
}

DRY_RUN=0
ALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --all)
      ALL=1
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

removed=0

action() {
  local label="$1"
  local path="$2"
  local type="$3"  # file or dir
  local confirm=""

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] Would remove $type: $path ($label)"
    removed=$((removed + 1))
    return
  fi

  if [ "$ALL" -eq 1 ]; then
    confirm="y"
  elif [ -t 0 ]; then
    echo -n "Remove $type: $path ($label)? [y/N] "
    read -r confirm
  else
    echo "Skipped (non-interactive, use --all to force): $path"
    return
  fi

  if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
    if [ "$type" = "file" ] && [ -f "$path" ]; then
      rm "$path"
      echo "Removed: $path"
      removed=$((removed + 1))
    elif [ "$type" = "dir" ] && [ -d "$path" ]; then
      rm -rf "$path"
      echo "Removed: $path"
      removed=$((removed + 1))
    fi
  else
    echo "Skipped: $path"
  fi
}

echo "superharness uninstall"
echo "======================"
echo ""

# 1. Remove launchd plists
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
if [ -d "$LAUNCH_AGENTS" ]; then
  for plist in "$LAUNCH_AGENTS"/com.superharness.inbox.*.plist; do
    [ -f "$plist" ] || continue
    label="$(basename "$plist" .plist)"
    # Unload before removing
    if [ "$DRY_RUN" -eq 0 ]; then
      launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    else
      echo "[dry-run] Would unload launchd service: $label"
    fi
    action "launchd plist" "$plist" "file"
  done
fi

# 2. Remove watcher logs
LOG_DIR="$HOME/Library/Logs/superharness"
if [ -d "$LOG_DIR" ]; then
  action "watcher logs" "$LOG_DIR" "dir"
fi

# 3. Remove wrapper symlink
WRAPPER="$HOME/.local/bin/superharness"
if [ -L "$WRAPPER" ]; then
  action "wrapper symlink" "$WRAPPER" "file"
fi

# 4. Remove watcher lock files
for lockdir in /tmp/superharness-inbox-watch-*.lock; do
  [ -d "$lockdir" ] || continue
  action "watcher lock" "$lockdir" "dir"
done

echo ""
if [ "$removed" -eq 0 ]; then
  echo "Nothing to remove."
else
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run complete. $removed item(s) would be removed."
  else
    echo "Removed $removed item(s)."
  fi
fi

echo ""
echo "========================================================"
echo "IMPORTANT: Per-project state is NOT removed."
echo ""
echo "  .superharness/ directories inside your projects are"
echo "  intentionally preserved — they contain your contract,"
echo "  handoffs, ledger, and failure memory."
echo ""
echo "  To remove a project's state:"
echo "    rm -rf /path/to/project/.superharness"
echo ""
echo "  To remove Claude Code hooks:"
echo "    Edit ~/.claude/settings.json and delete the"
echo "    superharness entries under 'hooks'."
echo "========================================================"
