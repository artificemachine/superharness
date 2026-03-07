#!/bin/bash
# newblacc-superharness installer
# Installs the superharness framework to the configured install directory
# and registers it as a Claude Code plugin.

set -euo pipefail

INSTALL_DIR="${SUPERHARNESS_DIR:-${HOME}/superharness}"
CLAUDE_PLUGINS_DIR="${CLAUDE_CONFIG_DIR:-${HOME}/.config/claude}/plugins"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== newblacc-superharness installer ==="
echo ""

# --- Check if already installed ---
if [ -d "${INSTALL_DIR}" ] && [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
  echo "WARNING: ${INSTALL_DIR} already exists."
  read -p "Overwrite? (y/N): " confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
  fi
fi

# --- Copy framework ---
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
  echo "Copying framework to ${INSTALL_DIR}..."
  mkdir -p "${INSTALL_DIR}"
  cp -r "${SCRIPT_DIR}/"* "${INSTALL_DIR}/"
  cp -r "${SCRIPT_DIR}/.claude-plugin" "${INSTALL_DIR}/"
  echo "Done."
else
  echo "Already in install directory. Skipping copy."
fi

# --- Make hooks executable ---
echo "Setting hook permissions..."
chmod +x "${INSTALL_DIR}/hooks/"*.sh 2>/dev/null || true

# --- Register as Claude Code plugin (symlink approach) ---
if [ -d "${HOME}/.claude" ]; then
  echo "Registering with Claude Code..."
  mkdir -p "${CLAUDE_PLUGINS_DIR}"
  ln -sf "${INSTALL_DIR}" "${CLAUDE_PLUGINS_DIR}/newblacc-superharness" 2>/dev/null || true
  echo "Symlinked to ${CLAUDE_PLUGINS_DIR}/newblacc-superharness"
else
  echo "NOTE: Claude config directory not found. Claude Code not installed or not configured."
  echo "      You can manually register later."
fi

# --- Summary ---
echo ""
echo "=== Installation complete ==="
echo ""
echo "Installed to: ${INSTALL_DIR}"
echo ""
echo "Skills available:"
for skill_dir in "${INSTALL_DIR}/skills"/*/; do
  if [ -f "${skill_dir}/SKILL.md" ]; then
    echo "  - $(basename "${skill_dir}")"
  fi
done
echo ""
echo "Hooks:"
for hook in "${INSTALL_DIR}/hooks/"*.sh; do
  echo "  - $(basename "${hook}")"
done
echo ""
echo "Next steps:"
echo "  1. Review skills in ${INSTALL_DIR}/skills/"
echo "  2. Customize skills to match your current workflow"
echo "  3. Add your own skills with: mkdir ${INSTALL_DIR}/skills/my-skill && touch ${INSTALL_DIR}/skills/my-skill/SKILL.md"
echo "  4. Restart Claude Code to pick up the plugin"
echo ""
