#!/bin/bash
# superharness session-exit hook — NOT a Stop hook
#
# Contains behaviors that must only run at true session exit:
#   - mark in-progress claude-code tasks as stopped
#   - write handoff YAMLs
#   - pause active inbox items targeting claude-code
#   - pkill MCP servers spawned for this session
#
# Do NOT register this as a Claude Code Stop hook.
# Stop fires on every assistant turn; these side-effects on every turn break
# the contract lifecycle, flood handoffs/, and kill MCP tools mid-session.
#
# Invocation options:
#   - Manual: bash session-exit.sh  (run after closing Claude)
#   - Shell trap: trap 'bash /path/to/session-exit.sh' EXIT  (in launch wrapper)
#   - Scheduled cleanup: cron / launchd one-shot after inactivity timeout

if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
  SUPERHARNESS_ROOT="$(cd "$CLAUDE_PLUGIN_ROOT/../.." && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SUPERHARNESS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
fi

PROJECT_DIR="$(pwd)"
SH_DIR="$PROJECT_DIR/.superharness"

[ -d "$SH_DIR" ] || exit 0

TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ")"

_ledger() { [ -f "$SH_DIR/ledger.md" ] && echo "$1" >> "$SH_DIR/ledger.md"; }

# Gather git context for handoffs
GIT_BRANCH=""
GIT_STATUS=""
GIT_LOG=""
if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_BRANCH=$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null || true)
  GIT_STATUS=$(git -C "$PROJECT_DIR" status --short 2>/dev/null | head -20 || true)
  GIT_LOG=$(git -C "$PROJECT_DIR" log --oneline -5 2>/dev/null || true)
fi

TASK_CONTEXT=""
if command -v superharness >/dev/null 2>&1; then
  TASK_CONTEXT=$(superharness context --project "$PROJECT_DIR" 2>/dev/null || true)
fi

INBOX_FILE=""
if [ -f "$SH_DIR/inbox.yaml" ]; then
  INBOX_FILE="$SH_DIR/inbox.yaml"
elif [ -f "$SH_DIR/inbox.json" ]; then
  INBOX_FILE="$SH_DIR/inbox.json"
fi

# --- Stop active Claude-owned tasks and write handoffs ---
STOPPED_TASK_IDS=""
if [ -f "$SH_DIR/state.sqlite3" ] && command -v python3 >/dev/null 2>&1; then
  export SH_SESSION_STOP_TIMESTAMP="$TIMESTAMP"
  export SH_SESSION_STOP_HARNESS_DIR="$SH_DIR"
  export SH_SESSION_STOP_TASK_CONTEXT="$TASK_CONTEXT"
  export SH_SESSION_STOP_BRANCH="${GIT_BRANCH:-}"
  export SH_SESSION_STOP_GIT_STATUS="${GIT_STATUS:-}"
  export SH_SESSION_STOP_GIT_LOG="${GIT_LOG:-}"
  STOPPED_TASK_IDS="$(python3 - <<'PY'
import os
import sys
import yaml

timestamp = os.environ.get("SH_SESSION_STOP_TIMESTAMP", "").strip()
harness_dir = os.environ.get("SH_SESSION_STOP_HARNESS_DIR", "").strip()
task_context = (os.environ.get("SH_SESSION_STOP_TASK_CONTEXT") or "").strip()
branch = (os.environ.get("SH_SESSION_STOP_BRANCH") or "").strip()
git_status = (os.environ.get("SH_SESSION_STOP_GIT_STATUS") or "").strip()
git_log = (os.environ.get("SH_SESSION_STOP_GIT_LOG") or "").strip()

project_dir = os.path.dirname(harness_dir)
handoffs_dir = os.path.join(harness_dir, "handoffs")
os.makedirs(handoffs_dir, exist_ok=True)
timestamp_safe = (timestamp or "unknown").replace(":", "-")

summary = "Session ended before task completion; task marked stopped by session-exit hook."
outcome = "Claude Code session ended while the task was still in progress. The task was marked stopped for operator review."
context = (
    "Session snapshot: .superharness/session-progress.md\n"
    f"Task context:\n{task_context or '(none)'}\n\n"
    f"Branch:\n{branch or '(not a git repo or detached HEAD)'}\n\n"
    f"Uncommitted changes:\n{git_status or '(clean)'}\n\n"
    f"Recent commits:\n{git_log or '(none)'}\n"
)

try:
    from superharness.engine import state_reader, state_writer

    stopped_ids = []
    tasks = state_reader.get_tasks(project_dir)

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("owner", "")) != "claude-code":
            continue
        if str(task.get("status", "")) != "in_progress":
            continue
        task_id = str(task.get("id", "")).strip()
        if not task_id:
            continue

        try:
            state_writer.set_task_status(project_dir, task_id, "stopped",
                stopped_at=timestamp,
                stopped_reason="session_stopped",
                summary=summary)
        except Exception:
            pass

        stopped_ids.append(task_id)

        handoff = {
            "task": task_id,
            "phase": "session_exit",
            "status": "stopped",
            "from": "claude-code",
            "to": "owner",
            "date": timestamp,
            "summary": summary,
            "outcome": outcome,
            "context": context,
            "artifacts": [".superharness/session-progress.md"],
        }
        handoff_path = os.path.join(
            handoffs_dir,
            f"{task_id}-session-exit-{timestamp_safe}-claude-code.yaml",
        )
        with open(handoff_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(handoff, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    for task_id in stopped_ids:
        print(task_id)
except Exception as exc:
    print(f"warn: could not stop contract tasks: {exc}", file=sys.stderr)
PY
)" || true
fi

for TASK_ID in $STOPPED_TASK_IDS; do
  [ -z "$TASK_ID" ] && continue
  _ledger "$TIMESTAMP session-exit: task stopped ($TASK_ID)"
  if [ -n "$INBOX_FILE" ] && command -v python3 >/dev/null 2>&1; then
    SYNC_RESULT="$(python3 -m superharness.engine.inbox sync_task_status \
      --file "$INBOX_FILE" --task "$TASK_ID" --to stopped --now "$TIMESTAMP" 2>/dev/null || true)"
    case "$SYNC_RESULT" in
      *"synced=0"*) ;;
      *"synced="*) _ledger "$TIMESTAMP session-exit: inbox task stopped ($TASK_ID)" ;;
    esac
  fi
done

# --- Pause any remaining active Claude-targeted inbox items ---
if [ -n "$INBOX_FILE" ] && command -v python3 >/dev/null 2>&1; then
  NOW="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ")"
  export SH_SESSION_STOP_INBOX_FILE="$INBOX_FILE"
  PAUSABLE_IDS="$(python3 - <<'PY'
import os
import sys
import yaml

inbox_file = os.environ.get("SH_SESSION_STOP_INBOX_FILE", "").strip()
try:
    with open(inbox_file, encoding="utf-8") as fh:
        items = yaml.safe_load(fh.read()) or []
    for item in (items if isinstance(items, list) else []):
        if not isinstance(item, dict):
            continue
        if str(item.get("to", "")) != "claude-code":
            continue
        if str(item.get("status", "")) in ("pending", "launched", "running"):
            print(item.get("id", ""))
except Exception as exc:
    print(f"warn: {exc}", file=sys.stderr)
PY
)" || true
  for ITEM_ID in $PAUSABLE_IDS; do
    [ -z "$ITEM_ID" ] && continue
    python3 -m superharness.engine.inbox set_status \
      --file "$INBOX_FILE" --id "$ITEM_ID" \
      --from pending --to paused --now "$NOW" --stamp-key paused_at 2>/dev/null || \
    python3 -m superharness.engine.inbox set_status \
      --file "$INBOX_FILE" --id "$ITEM_ID" \
      --from launched --to paused --now "$NOW" --stamp-key paused_at 2>/dev/null || \
    python3 -m superharness.engine.inbox set_status \
      --file "$INBOX_FILE" --id "$ITEM_ID" \
      --from running --to paused --now "$NOW" --stamp-key paused_at 2>/dev/null || true
    _ledger "$TIMESTAMP session-exit: inbox item paused ($ITEM_ID)"
  done
fi

# NOTE: Do NOT unload the launchd watcher on session end.
# The watcher is a persistent background service — it must survive Claude session boundaries.

# Kill MCP children spawned for this Claude session.
pkill -TERM -f "keylogger-mcp-wrapper" 2>/dev/null || true
pkill -TERM -f "serena start-mcp-server" 2>/dev/null || true
pkill -TERM -f "KotlinLanguageServer" 2>/dev/null || true
pkill -TERM -f "kotlin_language_server" 2>/dev/null || true
pkill -TERM -f "voice-toolkit" 2>/dev/null || true
pkill -TERM -f "token-diet-mcp" 2>/dev/null || true
pkill -TERM -f "tilth mcp" 2>/dev/null || true
pkill -TERM -f "nemoclaw-mcp-server" 2>/dev/null || true

exit 0
