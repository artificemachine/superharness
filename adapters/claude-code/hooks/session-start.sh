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

# Detect if this project has an active superharness contract
CONTRACT_STATUS=""
PROJECT_DIR="$(pwd)"
if [ -f "$PROJECT_DIR/.superharness/contract.yaml" ]; then
  CONTRACT_STATUS="Active contract found at .superharness/contract.yaml — read it before starting work."
fi

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

# Ensure launchd watcher exists for this project (macOS). Non-fatal.
WATCHER_STATUS=""
ENSURE_WATCHER="$SUPERHARNESS_ROOT/scripts/ensure-launchd-inbox-watcher.sh"
if [ -d "$PROJECT_DIR/.superharness" ] && [ -x "$ENSURE_WATCHER" ]; then
  ENSURE_OUT=$(bash "$ENSURE_WATCHER" --project "$PROJECT_DIR" 2>/dev/null || true)
  if [ -n "$ENSURE_OUT" ]; then
    WATCHER_STATUS="$ENSURE_OUT"
  else
    WATCHER_STATUS="Watcher check complete."
  fi
fi

# Build the context injection
CONTEXT="$(cat <<EOF
<superharness>
## Identity
$(printf '%s\n' "$IDENTITY")

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
- When you make a decision between alternatives: log it in the contract's decisions section.
- When something fails: log it in the contract's failures section.
- When reviewing: use the review lenses assigned in the contract (security, architecture, performance, tests, error-handling, devops, api-contract). Read the diff, challenge decisions, log findings. Never rubber-stamp.

## Enforcement hooks active:
- scope-guard: blocks writes to .env/credentials/keys, warns on system files
- branch-guard: blocks push to main/master, warns on force push and destructive git ops
- ledger-append: auto-logs file changes to .superharness/ledger.md

$(printf '%s\n' "$CONTRACT_STATUS")
$(printf '%s\n' "$PENDING_HANDOFFS")
$(printf '%s\n' "$WATCHER_STATUS")
</superharness>
EOF
)"

# Escape for JSON output
ESCAPED=$(echo "$CONTEXT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
# Remove surrounding quotes from json.dumps
ESCAPED=${ESCAPED:1:-1}

# Output in Claude Code SessionStart format
cat <<EOF
{
  "additionalContext": "$ESCAPED"
}
EOF
