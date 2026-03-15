#!/bin/bash
# S1 shim: delegates to Python command module
set -euo pipefail
PYTHON3="${SUPERHARNESS_PYTHON:-python3}"
exec "$PYTHON3" -m superharness.commands.inbox_watch "$@"
