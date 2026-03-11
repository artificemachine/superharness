#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  inbox-dispatch.sh --project DIR [--to claude-code|codex-cli] [--print-only] [--non-interactive] [--codex-bypass] [--launcher-timeout SECONDS]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --to TARGET     Optional target filter: claude-code or codex-cli
      --print-only    Build and print kickoff prompt without launching CLI
      --non-interactive  Run target launchers in non-interactive mode
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
      --launcher-timeout SECONDS  Kill launcher after SECONDS (default: 0 = no timeout)
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
TARGET_FILTER=""
PRINT_ONLY=0
NON_INTERACTIVE=0
CODEX_BYPASS=0
LAUNCHER_TIMEOUT=0

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET_FILTER="$2"
      shift 2
      ;;
    --print-only)
      PRINT_ONLY=1
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --codex-bypass)
      CODEX_BYPASS=1
      shift
      ;;
    --launcher-timeout)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      LAUNCHER_TIMEOUT="$2"
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

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }

case "$TARGET_FILTER" in
  ""|claude-code|codex-cli) ;;
  *)
    echo "--to must be claude-code or codex-cli" >&2
    exit 2
    ;;
esac

case "$LAUNCHER_TIMEOUT" in
  ''|*[!0-9]*)
    echo "--launcher-timeout must be a non-negative integer" >&2
    exit 2
    ;;
esac

HARNESS_DIR="$PROJECT_DIR/.superharness"
INBOX_FILE="$HARNESS_DIR/inbox.yaml"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"

if [ ! -f "$INBOX_FILE" ]; then
  echo "Inbox file not found: $INBOX_FILE" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_CLAUDE="$SCRIPT_DIR/delegate-to-claude.sh"
LAUNCH_CODEX="$SCRIPT_DIR/delegate-to-codex.sh"
INBOX_YAML="$SCRIPT_DIR/inbox-yaml.rb"
CONTRACT_YAML="$SCRIPT_DIR/../engine/contract.rb"

if [ ! -x "$LAUNCH_CLAUDE" ] || [ ! -x "$LAUNCH_CODEX" ] || [ ! -x "$INBOX_YAML" ] || [ ! -f "$CONTRACT_YAML" ]; then
  echo "Missing launcher scripts in $SCRIPT_DIR" >&2
  exit 1
fi

LOCK_FILE="${INBOX_FILE}.lock"
LOCK_DIR="${LOCK_FILE}.d"
LOCK_HELD=0
DIRTY_WORKTREE_REASON="dirty_worktree_requires_user_confirmation"

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_HELD=1
    return 0
  fi
  return 1
}

release_lock() {
  if [ "$LOCK_HELD" -eq 1 ]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
    LOCK_HELD=0
  fi
}

acquire_lock_with_retry() {
  local attempts="${1:-50}"
  local delay_seconds="${2:-0.1}"
  local attempt=0

  while [ "$attempt" -lt "$attempts" ]; do
    if acquire_lock; then
      return 0
    fi
    sleep "$delay_seconds"
    attempt=$((attempt + 1))
  done
  return 1
}

mark_item_failed() {
  local item_id="$1"
  local failed_at="$2"

  if ! acquire_lock_with_retry 50 0.1; then
    echo "Failed to acquire inbox lock while marking failure for $item_id" >&2
    return 1
  fi

  if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$item_id" --from launched --to failed --now "$failed_at" --stamp-key failed_at >/dev/null 2>&1 \
    || ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$item_id" --from running --to failed --now "$failed_at" --stamp-key failed_at >/dev/null 2>&1; then
    release_lock
    echo "Inbox item updated: $item_id -> failed"
    return 0
  fi

  release_lock
  echo "Failed to mark inbox item as failed for $item_id" >&2
  return 1
}

project_has_dirty_worktree() {
  local project_dir="$1"
  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi
  if ! git -C "$project_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi
  if [ -n "$(git -C "$project_dir" status --porcelain --untracked-files=normal 2>/dev/null)" ]; then
    return 0
  fi
  return 1
}

mark_item_paused_dirty_worktree() {
  local item_id="$1"
  local paused_at="$2"

  if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$item_id" --from pending --to paused --now "$paused_at" --stamp-key paused_at >/dev/null 2>&1; then
    ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$item_id" --key pause_reason --value "$DIRTY_WORKTREE_REASON" >/dev/null 2>&1 || true
    echo "Inbox item updated: $item_id -> paused (dirty worktree requires interactive confirmation)"
    return 0
  fi
  return 1
}

if ! acquire_lock; then
  echo "Another inbox dispatcher is active for $INBOX_FILE; skipping."
  exit 0
fi
trap 'release_lock' EXIT

READ_ARGS=(next_pending --file "$INBOX_FILE")
if [ -n "$TARGET_FILTER" ]; then
  READ_ARGS+=(--to "$TARGET_FILTER")
fi
if ! ITEM="$(ruby "$INBOX_YAML" "${READ_ARGS[@]}" 2>&1)"; then
  echo "Failed to read pending inbox item from $INBOX_FILE: $ITEM" >&2
  exit 1
fi
if [ -z "$ITEM" ]; then
  exit 0
fi

ITEM_FIELDS=()
while IFS= read -r -d '' field; do
  ITEM_FIELDS+=("$field")
done < <(
  printf '%s' "$ITEM" | ruby -rjson -e '
    h = JSON.parse(STDIN.read)
    keys = %w[id to task project retry_count max_retries priority]
    keys.each { |k| print(h.fetch(k, "").to_s); print("\0") }
  '
)
if [ "${#ITEM_FIELDS[@]}" -lt 7 ]; then
  echo "Failed to parse pending inbox item from $INBOX_FILE" >&2
  exit 1
fi

ITEM_ID="${ITEM_FIELDS[0]}"
ITEM_TO="${ITEM_FIELDS[1]}"
ITEM_TASK="${ITEM_FIELDS[2]}"
ITEM_PROJECT="${ITEM_FIELDS[3]}"
ITEM_RETRY_COUNT="${ITEM_FIELDS[4]}"
ITEM_MAX_RETRIES="${ITEM_FIELDS[5]}"
ITEM_PRIORITY="${ITEM_FIELDS[6]}"

if [ -z "$ITEM_PROJECT" ]; then
  ITEM_PROJECT="$PROJECT_DIR"
fi
if [ -z "$ITEM_RETRY_COUNT" ]; then
  ITEM_RETRY_COUNT=0
fi
if [ -z "$ITEM_MAX_RETRIES" ]; then
  ITEM_MAX_RETRIES=3
fi
if [ -z "$ITEM_PRIORITY" ]; then
  ITEM_PRIORITY=2
fi

EXEC_PROJECT="$ITEM_PROJECT"
PROJECT_HARNESS_REAL=""
ITEM_HARNESS_REAL=""
if [ -d "$PROJECT_DIR/.superharness" ]; then
  PROJECT_HARNESS_REAL="$(cd "$PROJECT_DIR/.superharness" && pwd -P)"
fi
if [ -d "$ITEM_PROJECT/.superharness" ]; then
  ITEM_HARNESS_REAL="$(cd "$ITEM_PROJECT/.superharness" && pwd -P)"
fi
# Worker-mode dispatch: when project and item share the same .superharness tree,
# run the launcher from the dispatcher project path (clean worker) instead of
# the source path recorded in inbox rows.
if [ -n "$PROJECT_HARNESS_REAL" ] && [ -n "$ITEM_HARNESS_REAL" ] && [ "$PROJECT_HARNESS_REAL" = "$ITEM_HARNESS_REAL" ] && [ "$PROJECT_DIR" != "$ITEM_PROJECT" ]; then
  EXEC_PROJECT="$PROJECT_DIR"
fi

LAUNCHER=""
case "$ITEM_TO" in
  claude-code) LAUNCHER="$LAUNCH_CLAUDE" ;;
  codex-cli) LAUNCHER="$LAUNCH_CODEX" ;;
  *)
    echo "Unsupported target '$ITEM_TO' for inbox item '$ITEM_ID'" >&2
    exit 1
    ;;
esac

if [ "$NON_INTERACTIVE" -eq 1 ] && [ "$PRINT_ONLY" -eq 0 ] && [ "$ITEM_TO" = "codex-cli" ] && project_has_dirty_worktree "$EXEC_PROJECT"; then
  PAUSE_NOW="$(date -u +%FT%TZ)"
  if mark_item_paused_dirty_worktree "$ITEM_ID" "$PAUSE_NOW"; then
    release_lock
    exit 0
  fi
fi

LAUNCH_ARGS=(--project "$EXEC_PROJECT" --task "$ITEM_TASK")
if [ "$PRINT_ONLY" -eq 1 ]; then
  LAUNCH_ARGS+=(--print-only)
fi
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  LAUNCH_ARGS+=(--non-interactive)
fi
if [ "$CODEX_BYPASS" -eq 1 ]; then
  LAUNCH_ARGS+=(--codex-bypass)
fi

LAUNCH_NOW="$(date -u +%FT%TZ)"
LAUNCH_RESULT="$(ruby "$INBOX_YAML" launch --file "$INBOX_FILE" --id "$ITEM_ID" --now "$LAUNCH_NOW" 2>&1)" || LAUNCH_RC=$?
LAUNCH_RC=${LAUNCH_RC:-0}
release_lock

if [ "$LAUNCH_RC" -eq 4 ]; then
  echo "Inbox item updated: $ITEM_ID -> failed (retry limit reached: $ITEM_RETRY_COUNT/$ITEM_MAX_RETRIES)"
  exit 1
fi
if [ "$LAUNCH_RC" -ne 0 ]; then
  echo "Failed to launch inbox item transition for $ITEM_ID: $LAUNCH_RESULT" >&2
  exit 1
fi

NEW_RETRY_COUNT="$(printf '%s\n' "$LAUNCH_RESULT" | sed -n 's/.*retry_count=\([0-9][0-9]*\).*/\1/p')"
if [ -z "$NEW_RETRY_COUNT" ]; then
  NEW_RETRY_COUNT="$ITEM_RETRY_COUNT"
fi
echo "Inbox item updated: $ITEM_ID -> launched (priority=$ITEM_PRIORITY, retries=$NEW_RETRY_COUNT/$ITEM_MAX_RETRIES)"

run_with_timeout() {
  local secs="$1"
  shift
  python3 - "$secs" "$@" <<'PY'
import os
import signal
import subprocess
import sys

timeout = int(sys.argv[1])
argv = sys.argv[2:]
if not argv:
    raise SystemExit(2)

proc = subprocess.Popen(argv, preexec_fn=os.setsid)
timed_out = False

def on_alarm(signum, frame):
    global timed_out
    timed_out = True
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

signal.signal(signal.SIGALRM, on_alarm)
signal.alarm(timeout)
rc = proc.wait()
signal.alarm(0)
if timed_out:
    sys.exit(124)
sys.exit(rc)
PY
}

LAUNCHER_RC=0
if [ "$LAUNCHER_TIMEOUT" -gt 0 ]; then
  run_with_timeout "$LAUNCHER_TIMEOUT" bash "$LAUNCHER" "${LAUNCH_ARGS[@]}" &
  LAUNCHER_PID=$!
else
  bash "$LAUNCHER" "${LAUNCH_ARGS[@]}" &
  LAUNCHER_PID=$!
fi

ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$ITEM_ID" --key pid --value "$LAUNCHER_PID" 2>/dev/null || true

wait "$LAUNCHER_PID" || LAUNCHER_RC=$?

ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$ITEM_ID" --key pid --value "" 2>/dev/null || true

if [ "$LAUNCHER_RC" -ne 0 ]; then
  FAIL_NOW="$(date -u +%FT%TZ)"
  if [ "$LAUNCHER_RC" -eq 124 ]; then
    echo "Launcher timed out after ${LAUNCHER_TIMEOUT}s for $ITEM_ID" >&2
  fi
  mark_item_failed "$ITEM_ID" "$FAIL_NOW"
  exit 1
fi

# In non-interactive mode, the launched process has already exited. If the task
# did not transition itself to done/failed, reconcile stuck states immediately.
if [ "$NON_INTERACTIVE" -eq 1 ] && [ "$PRINT_ONLY" -eq 0 ]; then
  RECONCILE_NOW="$(date -u +%FT%TZ)"
  if ! acquire_lock_with_retry 50 0.1; then
    echo "Failed to acquire inbox lock while reconciling status for $ITEM_ID" >&2
    exit 1
  fi
  RECONCILED=0
  FINAL_STATE=""

  if [ -f "$CONTRACT_FILE" ]; then
    if ! FINAL_STATE="$(ruby "$CONTRACT_YAML" task_status --file "$CONTRACT_FILE" --task "$ITEM_TASK" 2>&1)"; then
      echo "Failed to read contract task status for $ITEM_TASK: $FINAL_STATE" >&2
      FINAL_STATE=""
    fi
  fi

  case "$FINAL_STATE" in
    done)
      if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "done" --now "$RECONCILE_NOW" --stamp-key done_at >/dev/null 2>&1; then
        RECONCILED=1
      elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "done" --now "$RECONCILE_NOW" --stamp-key done_at >/dev/null 2>&1; then
        RECONCILED=1
      fi
      ;;
    failed)
      if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
        RECONCILED=1
      elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
        RECONCILED=1
      fi
      ;;
    pending_user_approval)
      if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "paused" --now "$RECONCILE_NOW" --stamp-key paused_at >/dev/null 2>&1; then
        ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$ITEM_ID" --key pause_reason --value "awaiting_user_approval" >/dev/null 2>&1 || true
        RECONCILED=3
      elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "paused" --now "$RECONCILE_NOW" --stamp-key paused_at >/dev/null 2>&1; then
        ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$ITEM_ID" --key pause_reason --value "awaiting_user_approval" >/dev/null 2>&1 || true
        RECONCILED=3
      fi
      ;;
    *)
      if [ "$ITEM_TO" = "codex-cli" ] && project_has_dirty_worktree "$EXEC_PROJECT"; then
        if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "paused" --now "$RECONCILE_NOW" --stamp-key paused_at >/dev/null 2>&1; then
          ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$ITEM_ID" --key pause_reason --value "$DIRTY_WORKTREE_REASON" >/dev/null 2>&1 || true
          RECONCILED=2
        elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "paused" --now "$RECONCILE_NOW" --stamp-key paused_at >/dev/null 2>&1; then
          ruby "$INBOX_YAML" set_field --file "$INBOX_FILE" --id "$ITEM_ID" --key pause_reason --value "$DIRTY_WORKTREE_REASON" >/dev/null 2>&1 || true
          RECONCILED=2
        fi
      else
        if ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from launched --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
          RECONCILED=1
        elif ruby "$INBOX_YAML" set_status --file "$INBOX_FILE" --id "$ITEM_ID" --from running --to "failed" --now "$RECONCILE_NOW" --stamp-key failed_at >/dev/null 2>&1; then
          RECONCILED=1
        fi
      fi
      ;;
  esac
  release_lock

  if [ "$RECONCILED" -eq 2 ]; then
    echo "Inbox item updated: $ITEM_ID -> paused ($DIRTY_WORKTREE_REASON)"
    exit 0
  fi
  if [ "$RECONCILED" -eq 3 ]; then
    echo "Inbox item updated: $ITEM_ID -> paused (awaiting_user_approval)"
    exit 0
  fi
  if [ "$RECONCILED" -eq 1 ]; then
    if [ "$FINAL_STATE" = "done" ]; then
      echo "Inbox item updated: $ITEM_ID -> done (reconciled from contract task status)"
      exit 0
    fi
    echo "Inbox item updated: $ITEM_ID -> failed (non-interactive launch exited without done/failed)"
    exit 1
  fi
fi
