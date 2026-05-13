#!/usr/bin/env bash
# dev-reinstall.sh — clean editable reinstall for superharness.
#
# Problem: `pip install -e .` after a version bump does not replace the old
# `superharness-{prev_ver}.dist-info` directory, so `importlib.metadata` and
# `shux --version` keep reporting the stale version until the old dir is
# removed manually.
#
# This script removes every stale superharness dist-info and editable .pth
# file before reinstalling, guaranteeing the post-install version matches
# what is declared in pyproject.toml.
#
# Usage:
#   bash scripts/dev-reinstall.sh           # from repo root
#   bash scripts/dev-reinstall.sh --check   # verify only, no install
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=$(python3 -c "import site; print(site.getsitepackages()[0])")
EXPECTED=$(python3 - <<'PY'
import tomllib, pathlib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
print(data["project"]["version"])
PY
)

if [[ "${1:-}" == "--check" ]]; then
    ACTUAL=$(python3 -c "from importlib.metadata import version; print(version('superharness'))" 2>/dev/null || echo "not-installed")
    if [[ "$ACTUAL" == "$EXPECTED" ]]; then
        echo "ok: superharness $ACTUAL matches pyproject.toml"
        exit 0
    else
        echo "STALE: installed=$ACTUAL pyproject.toml=$EXPECTED" >&2
        exit 1
    fi
fi

echo "Removing stale superharness dist-info and editable .pth from $SITE ..."
find "$SITE" -maxdepth 1 -name "superharness-*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$SITE" -maxdepth 1 -name "__editable__.superharness-*.pth" -exec rm -f {} + 2>/dev/null || true

echo "Installing superharness==$EXPECTED (editable) from $REPO_ROOT ..."
pip install -e "$REPO_ROOT" -q

ACTUAL=$(python3 -c "from importlib.metadata import version; print(version('superharness'))")
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
    echo "ERROR: version mismatch after install: installed=$ACTUAL expected=$EXPECTED" >&2
    exit 1
fi

echo "ok: superharness $ACTUAL installed"
