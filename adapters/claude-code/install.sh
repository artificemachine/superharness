#!/bin/bash
# Install superharness as a Claude Code plugin
# Creates a symlink in ~/.claude/plugins/ pointing to this adapter directory.
# This way Claude Code discovers superharness as a plugin, and its hooks
# automatically merge with other plugins (like superpowers). No conflicts.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_TARGET="$HOME/.claude/plugins/superharness"

echo "superharness — Claude Code plugin install"
echo "==========================================="
echo ""

# Check if already installed
if [ -L "$PLUGIN_TARGET" ]; then
  CURRENT=$(readlink "$PLUGIN_TARGET")
  if [ "$CURRENT" = "$SCRIPT_DIR" ]; then
    echo "Already installed. Symlink is current."
    echo "  $PLUGIN_TARGET → $SCRIPT_DIR"
    exit 0
  else
    echo "Existing symlink points to: $CURRENT"
    echo "Updating to: $SCRIPT_DIR"
    rm "$PLUGIN_TARGET"
  fi
elif [ -d "$PLUGIN_TARGET" ]; then
  echo "WARNING: $PLUGIN_TARGET exists as a directory (not a symlink)."
  echo "This might be a previous manual install. Please remove it first:"
  echo "  rm -rf $PLUGIN_TARGET"
  exit 1
fi

# Create plugins directory if needed
mkdir -p "$HOME/.claude/plugins"

# Symlink this adapter directory as the plugin
ln -s "$SCRIPT_DIR" "$PLUGIN_TARGET"

echo "Plugin installed (symlinked):"
echo "  $PLUGIN_TARGET → $SCRIPT_DIR"
echo ""
echo "Claude Code will now:"
echo "  1. Discover superharness as a plugin"
echo "  2. Run its SessionStart hook alongside superpowers (no conflict)"
echo "  3. Inject your identity + cross-agent protocol every session"
echo ""
echo "Verify with:  claude /plugins   (should list superharness)"
echo ""
echo "To uninstall:  rm $PLUGIN_TARGET"
