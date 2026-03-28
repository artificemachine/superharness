#!/bin/bash
# S1 shim: delegates to Python command module
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
PYTHON3="${SUPERHARNESS_PYTHON:-python3}"
exec "$PYTHON3" -m superharness.commands.inbox_dispatch "$@"
