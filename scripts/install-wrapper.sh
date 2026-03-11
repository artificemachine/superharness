#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  install-wrapper.sh [--target-dir DIR]

Options:
  -t, --target-dir DIR  Install directory for superharness symlink (default: ~/.local/bin)
  -h, --help            Show this help message and exit
USAGE
}

TARGET_DIR="$HOME/.local/bin"

while [ $# -gt 0 ]; do
  case "$1" in
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE="$ROOT_DIR/superharness"
TARGET="$TARGET_DIR/superharness"

[ -x "$SOURCE" ] || { echo "Missing executable wrapper: $SOURCE" >&2; exit 1; }
mkdir -p "$TARGET_DIR"
ln -sfn "$SOURCE" "$TARGET"

echo "Installed superharness wrapper: $TARGET -> $SOURCE"
case ":$PATH:" in
  *":$TARGET_DIR:"*)
    echo "PATH already contains $TARGET_DIR"
    ;;
  *)
    echo "Add to PATH: export PATH=\"$TARGET_DIR:\$PATH\""
    ;;
esac
