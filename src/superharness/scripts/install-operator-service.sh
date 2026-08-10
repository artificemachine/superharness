#!/bin/bash
# install-operator-service.sh — Installs the Superharness Guardian as a persistent macOS service.
set -euo pipefail

PROJECT_DIR="$(cd "${1:-.}" && pwd -P)"
shift || true
EXTRA_ARGS=""
for arg in "$@"; do
    EXTRA_ARGS="${EXTRA_ARGS}
        <string>${arg}</string>"
done

# launchd only receives a normalised boolean, never arbitrary shell/XML data.
case "$(printf '%s' "${SUPERHARNESS_WATCH_DEBUG:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) WATCH_DEBUG="1" ;;
    *) WATCH_DEBUG="0" ;;
esac

# Keep the launchd label aligned with operator_label_for_project(): hash the
# resolved path bytes, without echo's trailing newline.
LABEL="com.superharness.operator.$(printf '%s' "$PROJECT_DIR" | md5 -q | head -c 8)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/superharness"
mkdir -p "$(dirname "$PLIST_PATH")"
mkdir -p "$LOG_DIR"

# The CLI supplies its own interpreter so launchd imports the installed wheel
# that owns the command. Direct script callers fall back to PATH.
PYTHON_BIN="${SUPERHARNESS_OPERATOR_PYTHON_BIN:-$(command -v python3 || true)}"
if ! { [ -x "$PYTHON_BIN" ] && "$PYTHON_BIN" -c "import superharness" 2>/dev/null; }; then
    echo "ERROR: no usable Python interpreter for superharness: ${PYTHON_BIN:-not found}" >&2
    exit 1
fi

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
        <string>--no-daemon</string>
        <string>--project</string>
        <string>${PROJECT_DIR}</string>${EXTRA_ARGS}
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
        <key>SUPERHARNESS_FORCE_NO_SDK</key>
        <string>1</string>
        <key>SUPERHARNESS_WATCH_DEBUG</key>
        <string>${WATCH_DEBUG}</string>
    </dict>
</dict>
</plist>
EOF

UID_VALUE="$(id -u)"
launchctl bootout "gui/${UID_VALUE}/${LABEL}" 2>/dev/null || true
# bootout is asynchronous on recent macOS releases.  Do not race a new
# bootstrap against the old launchd job still being torn down.
for _ in {1..20}; do
    if ! launchctl print "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done
launchctl enable "gui/${UID_VALUE}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_VALUE}" "$PLIST_PATH"
echo "🛡️  Superharness Guardian re-installed: ${LABEL}"
