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
# Always targets the repo-local .venv, never a bare `python3`/`pip` off
# PATH — a shared/global interpreter with no repo context has no business
# being mutated by this script. The repo .venv is uv-created and has no
# `pip` in it, so the install step falls back to `uv pip install` when
# `python -m pip` is unavailable.
#
# Usage:
#   bash scripts/dev-reinstall.sh           # from repo root
#   bash scripts/dev-reinstall.sh --check   # verify only, no install
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
VENV_PY="$VENV/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    echo "ERROR: no interpreter at $VENV_PY — run 'python3 -m venv $VENV' first." >&2
    exit 1
fi

SITE=$("$VENV_PY" -c "import site; print(site.getsitepackages()[0])")
EXPECTED=$("$VENV_PY" - <<'PY'
import tomllib, pathlib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
print(data["project"]["version"])
PY
)

if [[ "${1:-}" == "--check" ]]; then
    ACTUAL=$("$VENV_PY" -c "from importlib.metadata import version; print(version('superharness'))" 2>/dev/null || echo "not-installed")
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

echo "Installing superharness==$EXPECTED (editable) into $VENV from $REPO_ROOT ..."
if "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    "$VENV_PY" -m pip install -e "$REPO_ROOT" -q
elif command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="$VENV" uv pip install -e "$REPO_ROOT" -q
else
    echo "ERROR: no pip in $VENV_PY and no 'uv' on PATH — cannot install." >&2
    exit 1
fi

ACTUAL=$("$VENV_PY" -c "from importlib.metadata import version; print(version('superharness'))")
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
    echo "ERROR: version mismatch after install: installed=$ACTUAL expected=$EXPECTED" >&2
    exit 1
fi

echo "ok: superharness $ACTUAL installed"
