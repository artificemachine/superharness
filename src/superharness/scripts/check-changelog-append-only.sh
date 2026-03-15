#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  check-changelog-append-only.sh [--file PATH] (--staged | --base-ref REF [--head-ref REF])

Checks that CHANGELOG content is append-only.

Modes:
  --staged            Compare staged blob against HEAD blob for PATH.
  --base-ref REF      Compare REF blob against HEAD blob for PATH.
  --head-ref REF      Optional head ref when using --base-ref (default: HEAD).

Options:
  --file PATH         Target file path (default: CHANGELOG.md)
  -h, --help          Show this help and exit
EOF
}

TARGET_FILE="CHANGELOG.md"
MODE=""
BASE_REF=""
HEAD_REF="HEAD"

while [ $# -gt 0 ]; do
  case "$1" in
    --file)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET_FILE="$2"
      shift 2
      ;;
    --staged)
      MODE="staged"
      shift
      ;;
    --base-ref)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      MODE="base"
      BASE_REF="$2"
      shift 2
      ;;
    --head-ref)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      HEAD_REF="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[ -n "$MODE" ] || { echo "Either --staged or --base-ref is required" >&2; exit 2; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
old_file="$tmp_dir/old"
new_file="$tmp_dir/new"

write_blob_or_empty() {
  local ref="$1"
  local path="$2"
  local out="$3"
  if git cat-file -e "${ref}:${path}" 2>/dev/null; then
    git show "${ref}:${path}" > "$out"
  else
    : > "$out"
  fi
}

if [ "$MODE" = "staged" ]; then
  if ! git diff --cached --name-only -- "$TARGET_FILE" | grep -q "^${TARGET_FILE}$"; then
    exit 0
  fi
  write_blob_or_empty "HEAD" "$TARGET_FILE" "$old_file"
  if git cat-file -e ":${TARGET_FILE}" 2>/dev/null; then
    git show ":${TARGET_FILE}" > "$new_file"
  else
    echo "ERROR: staged target not found in index: $TARGET_FILE" >&2
    exit 1
  fi
else
  [ -n "$BASE_REF" ] || { echo "--base-ref requires a value" >&2; exit 2; }
  write_blob_or_empty "$BASE_REF" "$TARGET_FILE" "$old_file"
  write_blob_or_empty "$HEAD_REF" "$TARGET_FILE" "$new_file"
fi

old_size="$(wc -c < "$old_file" | tr -d ' ')"
new_size="$(wc -c < "$new_file" | tr -d ' ')"

if [ "$new_size" -lt "$old_size" ]; then
  echo "ERROR: $TARGET_FILE is not append-only (file became smaller)." >&2
  exit 1
fi

if [ "$old_size" -gt 0 ] && ! head -c "$old_size" "$new_file" | cmp -s - "$old_file"; then
  echo "ERROR: $TARGET_FILE changed existing content. Only append at EOF is allowed." >&2
  exit 1
fi

exit 0
