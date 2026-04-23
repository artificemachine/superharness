#!/bin/bash
# install-operator-service.sh — Installs the Superharness Guardian as a persistent macOS service.
set -euo pipefail

PROJECT_DIR="$(cd "${1:-.}" && pwd -P)"
LABEL="com.superharness.operator.$(echo "$PROJECT_DIR" | md5 | head -c 8)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/superharness"
mkdir -p "$LOG_DIR"

# Identify the python interpreter
PYTHON_BIN="$(which python3)"

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>-m</string>
        <string>superharness.cli</string>
        <string>operator</string>
        <string>start</string>
        <string>--project</string>
        <string>${PROJECT_DIR}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/${LABEL}.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/${LABEL}.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>${PROJECT_DIR}/src</string>
        <key>SUPERHARNESS_FORCE_NO_SDK</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "🛡️  Superharness Guardian re-installed: ${LABEL}"
