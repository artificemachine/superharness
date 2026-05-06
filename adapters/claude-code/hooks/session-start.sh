#!/bin/bash
# superharness SessionStart hook for Claude Code
# Injects identity core + cross-agent protocol awareness on every session start.
# Works alongside superpowers — they inject skills, we inject identity + protocol.

# CLAUDE_PLUGIN_ROOT is set by Claude Code when running plugin hooks.
# It points to adapters/claude-code/ — superharness root is two levels up.
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
  SUPERHARNESS_ROOT="$(cd "$CLAUDE_PLUGIN_ROOT/../.." && pwd)"
else
  # Fallback for manual testing outside Claude Code
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SUPERHARNESS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
fi

# Read identity core
IDENTITY=""
if [ -f "$SUPERHARNESS_ROOT/protocol/templates/identity-core.md" ]; then
  IDENTITY=$(cat "$SUPERHARNESS_ROOT/protocol/templates/identity-core.md")
fi

# Detect if this project has an active superharness contract; inject full context
TASK_CONTEXT=""
PROJECT_DIR="$(pwd)"
if [ -f "$PROJECT_DIR/.superharness/contract.yaml" ]; then
  ACTIVE_TASK=$(python3 -c "
import sys
try:
    import yaml
    doc = yaml.safe_load(open('$PROJECT_DIR/.superharness/contract.yaml'))
    tasks = doc.get('tasks') or []
    for t in tasks:
        if t.get('status') in ('in_progress','plan_proposed','plan_approved','report_ready'):
            print(t.get('id',''))
            break
except: pass
" 2>/dev/null || true)
  if [ -n "$ACTIVE_TASK" ]; then
    TASK_CONTEXT=$(superharness context --project "$PROJECT_DIR" "$ACTIVE_TASK" 2>/dev/null || true)
  fi
  if [ -z "$TASK_CONTEXT" ]; then
    TASK_CONTEXT="Active contract found at .superharness/contract.yaml — run: shux context"
  fi
fi
CONTRACT_STATUS="$TASK_CONTEXT"

# Check for pending handoffs addressed to claude-code
PENDING_HANDOFFS=""
if [ -d "$PROJECT_DIR/.superharness/handoffs" ]; then
  for f in "$PROJECT_DIR/.superharness/handoffs"/*.yaml; do
    [ -f "$f" ] || continue
    if grep -q "to: claude-code" "$f" 2>/dev/null; then
      PENDING_HANDOFFS="Pending handoff for you: $f — read it before doing anything else."
      break
    fi
  done
fi

# Auto-search obsidian-semantic vault using the active contract task title (if available)
VAULT_CONTEXT=""
OBSIDIAN_DASH="${OBSIDIAN_DASH_URL:-http://localhost:8484}"
if command -v curl >/dev/null 2>&1; then
  # Extract active task title from contract.yaml for the search query
  TASK_QUERY=""
  if [ -f "$PROJECT_DIR/.superharness/contract.yaml" ]; then
    TASK_QUERY=$(python3 -c "
import sys, re
try:
    text = open('$PROJECT_DIR/.superharness/contract.yaml').read()
    # Find first in-progress or plan_proposed task title
    m = re.search(r'title:\s*[\"\'']?([^\n\"\']+)[\"\'']?', text)
    if m: print(m.group(1).strip()[:80])
except: pass
" 2>/dev/null || true)
  fi

  if [ -n "$TASK_QUERY" ]; then
    ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$TASK_QUERY" 2>/dev/null || echo "")
    if [ -n "$ENCODED" ]; then
      SEARCH_RESULT=$(curl -sf --max-time 3 "$OBSIDIAN_DASH/api/search?q=$ENCODED&limit=3" 2>/dev/null || echo "")
      if [ -n "$SEARCH_RESULT" ]; then
        VAULT_CONTEXT=$(echo "$SEARCH_RESULT" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    results = d.get('results', [])
    if not results:
        print('Vault search: no relevant notes found for this task.')
        sys.exit(0)
    lines = ['Vault notes relevant to task (auto-searched via obsidian-semantic):']
    for r in results:
        lines.append(f\"  - {r['path']} (similarity: {r['similarity']})\")
        preview = r.get('preview','')[:120].replace('\n',' ')
        lines.append(f\"    {preview}\")
    print('\n'.join(lines))
except Exception as e:
    print(f'Vault search unavailable: {e}')
" 2>/dev/null || true)
      fi
    fi
  fi

  # Fallback: just note that vault search is available if no contract task found
  if [ -z "$VAULT_CONTEXT" ]; then
    if curl -sf --max-time 2 "$OBSIDIAN_DASH/api/stats" >/dev/null 2>&1; then
      VAULT_CONTEXT="obsidian-semantic vault search is available at $OBSIDIAN_DASH. Call search_vault <topic> to retrieve relevant notes."
    fi
  fi
fi

# Ensure launchd watcher exists for this project (macOS). Non-fatal.
# SUPERHARNESS_NO_AUTO_INSTALL=1 disables auto-install (used by tests so a
# pytest tmp_path .superharness/ never registers a real plist).
WATCHER_STATUS=""
ENSURE_WATCHER="$SUPERHARNESS_ROOT/src/superharness/scripts/ensure-launchd-inbox-watcher.sh"
if [ -n "${SUPERHARNESS_NO_AUTO_INSTALL:-}" ]; then
  WATCHER_STATUS="Auto-install skipped (SUPERHARNESS_NO_AUTO_INSTALL set)."
elif [ -d "$PROJECT_DIR/.superharness" ] && [ -x "$ENSURE_WATCHER" ]; then
  # Pass confirmation flags so the installer can auto-reinstall a missing plist without prompting.
  # These flags mirror the defaults used by install-launchd-inbox-watcher.sh.
  ENSURE_OUT=$(bash "$ENSURE_WATCHER" \
    --project "$PROJECT_DIR" \
    --confirm-non-interactive yes \
    --confirm-skip-permissions yes \
    2>/dev/null || true)
  if [ -n "$ENSURE_OUT" ]; then
    WATCHER_STATUS="$ENSURE_OUT"
  else
    WATCHER_STATUS="Watcher check complete."
  fi
fi

# Check watcher heartbeat health
HEARTBEAT_FILE="$PROJECT_DIR/.superharness/watcher.heartbeat"
HEARTBEAT_STALE_SECONDS=120  # 2x default 60s interval
if [ -d "$PROJECT_DIR/.superharness" ]; then
  if [ ! -f "$HEARTBEAT_FILE" ]; then
    WATCHER_STATUS="WARNING: Watcher may not be running — no heartbeat file found. Run: superharness watch --project $PROJECT_DIR"
  else
    HB_TS="$(head -n1 "$HEARTBEAT_FILE" 2>/dev/null | tr -d '[:space:]')"
    if [ -n "$HB_TS" ]; then
      HB_EPOCH="$(date -juf "%Y-%m-%dT%H:%M:%SZ" "$HB_TS" +%s 2>/dev/null || date -d "$HB_TS" +%s 2>/dev/null || echo 0)"
      NOW_EPOCH="$(date +%s)"
      if [ "$HB_EPOCH" -gt 0 ] 2>/dev/null; then
        AGE=$(( NOW_EPOCH - HB_EPOCH ))
        if [ "$AGE" -ge "$HEARTBEAT_STALE_SECONDS" ]; then
          AGE_MIN=$(( AGE / 60 ))
          WATCHER_STATUS="WARNING: Watcher heartbeat is stale (${AGE_MIN}m ago). Watcher may have crashed. Run: superharness watch --project $PROJECT_DIR"
        else
          WATCHER_STATUS="Watcher healthy (heartbeat ${AGE}s ago)."
        fi
      fi
    fi
  fi
fi

# Read session progress snapshot from previous session's stop hook
SESSION_PROGRESS=""
PROGRESS_FILE="$PROJECT_DIR/.superharness/session-progress.md"
if [ -f "$PROGRESS_FILE" ]; then
  SESSION_PROGRESS=$(cat "$PROGRESS_FILE" 2>/dev/null || true)
fi

# Pre-compute optional sections (avoids single-quote issues in heredoc on bash 3.2)
PROGRESS_SECTION=""
if [ -n "$SESSION_PROGRESS" ]; then
  PROGRESS_SECTION="## Previous Session Snapshot
${SESSION_PROGRESS}"
fi

# Build the context injection
# All variables are pre-computed above — no $(cmd) inside the heredoc to avoid
# bash 3.2 single-quote parsing bugs in heredoc command substitutions.
CONTEXT="<superharness>
## Identity
${IDENTITY}

## Cross-Agent Protocol
You are one of two senior devs. The other is Codex CLI.
You both build AND review each other's work. Neither is the boss.
The project owner is the tech lead and assigns roles per task in the contract.

Your strengths: multi-turn reasoning, MCP tools, security review, architecture, planning.
Your weaknesses: can over-engineer, verbose, context rot on long sessions, can hallucinate APIs.

When reviewing Codex's work: check for naive implementations, missed edge cases, architectural blind spots, security shortcuts.
When Codex reviews YOUR work: expect challenges on over-abstraction and unnecessary complexity. Take them seriously.

Protocol files live in .superharness/ (contract.yaml, handoffs/, ledger.md, failures.yaml, decisions.yaml).
- Before starting: read contract.yaml, failures.yaml, decisions.yaml, and any handoffs addressed to you.
- Before implementing: search failures.yaml for past failures with this technology/approach.
- When done with a task: write a handoff for the next agent + append to ledger.md.
- When you make a decision between alternatives: log it in the contract decisions section.
- When something fails: log it in the contract failures section.
- When reviewing: use the review lenses assigned in the contract (security, architecture, performance, tests, error-handling, devops, api-contract). Read the diff, challenge decisions, log findings. Never rubber-stamp.

## Enforcement hooks active:
- scope-guard: blocks writes to .env/credentials/keys, warns on system files
- branch-guard: blocks push to main/master, warns on force push and destructive git ops
- ledger-append: auto-logs file changes to .superharness/ledger.md

${VAULT_CONTEXT}
${CONTRACT_STATUS}
${PENDING_HANDOFFS}
${WATCHER_STATUS}

${PROGRESS_SECTION}

## Session Start Instruction
When starting a new session (not a /continue), display a brief status summary BEFORE the first message. Format:

---
superharness | branch: BRANCH | task: TASK-ID (STATUS)
One-line task title
Restored from previous session snapshot (if applicable)
Pending handoff - read before starting (if applicable)
N uncommitted files (if applicable)
---

Keep it to 3-5 lines max. Do not dump the full context. If no task or contract is active, just show the branch.
</superharness>"

# Output in Claude Code SessionStart format
# Use Python to build the full JSON — avoids bash ${var:1:-1} which is unsupported on bash 3.2 (macOS default)
echo "$CONTEXT" | python3 -c "import sys,json; print(json.dumps({'additionalContext': sys.stdin.read()}))"
