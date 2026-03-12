#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec ruby "$SCRIPT_DIR/../engine/recall.rb" "$@"
