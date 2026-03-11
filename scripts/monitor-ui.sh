#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'USAGE'
Usage:
  monitor-ui.sh --project DIR [--port PORT] [--host HOST] [--refresh-seconds N]

Options:
  --project DIR          Project directory containing .superharness/
  --port PORT            HTTP port to bind (default: 8765)
  --host HOST            Bind host (loopback only; default: 127.0.0.1)
  --refresh-seconds N    Dashboard refresh interval in seconds (default: 3)
  -h, --help             Show this help message and exit
USAGE
  exit 0
fi

exec python3 "$SCRIPT_DIR/monitor-ui.py" "$@"
