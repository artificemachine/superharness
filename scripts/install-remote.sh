#!/bin/bash
# install-remote.sh — Clone superharness and install the CLI wrapper
#
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/celstnblacc/superharness/main/scripts/install-remote.sh | bash
#
# Usage (with options):
#   bash install-remote.sh [--dir DIR] [--target-dir DIR]
set -euo pipefail

REPO_URL="https://github.com/celstnblacc/superharness.git"
DEFAULT_CLONE_DIR="$HOME/.local/share/superharness"
TARGET_DIR="$HOME/.local/bin"
CLONE_DIR=""

usage() {
  cat << 'USAGE'
Usage:
  install-remote.sh [--dir DIR] [--target-dir DIR]

Options:
  -d, --dir DIR         Where to clone the superharness repo (default: ~/.local/share/superharness)
  -t, --target-dir DIR  Where to install the superharness symlink (default: ~/.local/bin)
  -h, --help            Show this help message and exit
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    -d|--dir)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      CLONE_DIR="$2"
      shift 2
      ;;
    -t|--target-dir)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLONE_DIR="${CLONE_DIR:-$DEFAULT_CLONE_DIR}"

# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------
need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing prerequisite: $1" >&2; exit 1; }
}
need git
need bash
need ruby
need python3

echo "superharness — remote install"
echo "=============================="
echo "Repo:       $REPO_URL"
echo "Clone dir:  $CLONE_DIR"
echo "Symlink to: $TARGET_DIR/superharness"
echo ""

# ---------------------------------------------------------------------------
# Clone or update
# ---------------------------------------------------------------------------
if [ -d "$CLONE_DIR/.git" ]; then
  echo "Repository already exists at $CLONE_DIR — pulling latest..."
  git -C "$CLONE_DIR" pull --ff-only
else
  echo "Cloning superharness..."
  git clone "$REPO_URL" "$CLONE_DIR"
fi

echo ""

# ---------------------------------------------------------------------------
# Install wrapper symlink
# ---------------------------------------------------------------------------
bash "$CLONE_DIR/scripts/install-wrapper.sh" --target-dir "$TARGET_DIR"

echo ""
echo "Done. Run 'superharness version' to verify."
