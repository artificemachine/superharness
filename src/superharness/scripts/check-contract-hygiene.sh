#!/bin/bash
set -euo pipefail

PYTHON3="${SUPERHARNESS_PYTHON:-python3}"
exec "$PYTHON3" -m superharness.engine.validate "$@"
