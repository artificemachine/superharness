#!/bin/bash
set -euo pipefail

PYTHON3="${SUPERHARNESS_PYTHON:-python3}"
exec "$PYTHON3" -m superharness.commands.delegate --to claude-code "$@"
