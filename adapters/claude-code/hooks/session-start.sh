#!/bin/bash
# superreins SessionStart hook for Claude Code
# Injects identity core + cross-agent protocol awareness on every session start.
# Works alongside superpowers — they inject skills, we inject identity + protocol.

# CLAUDE_PLUGIN_ROOT is set by Claude Code when running plugin hooks.
# It points to adapters/claude-code/ — superreins root is two levels up.
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
  SUPERHARNESS_ROOT="$(cd "$CLAUDE_PLUGIN_ROOT/../.." && pwd)"
else
  # Fallback for manual testing outside Claude Code
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SUPERHARNESS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
fi

# Read identity core
IDENTITY=""
if [ -f "$SUPERHARNESS_ROOT/identity/core.md" ]; then
  IDENTITY=$(cat "$SUPERHARNESS_ROOT/identity/core.md")
fi

# Detect if this project has an active superreins contract
CONTRACT_STATUS=""
PROJECT_DIR="$(pwd)"
if [ -f "$PROJECT_DIR/.superreins/contract.yaml" ]; then
  CONTRACT_STATUS="Active contract found at .superreins/contract.yaml — read it before starting work."
fi

# Check for pending handoffs addressed to claude-code
PENDING_HANDOFFS=""
if [ -d "$PROJECT_DIR/.superreins/handoffs" ]; then
  for f in "$PROJECT_DIR/.superreins/handoffs"/*.yaml; do
    [ -f "$f" ] || continue
    if grep -q "to: claude-code" "$f" 2>/dev/null; then
      PENDING_HANDOFFS="Pending handoff for you: $f — read it before doing anything else."
      break
    fi
  done
fi

# Build the context injection
CONTEXT="<superreins>
## Identity
$IDENTITY

## Cross-Agent Protocol
You are one of two senior devs. The other is Codex CLI.
You both build AND review each other's work. Neither is the boss.
Maxime is the tech lead — he assigns roles per task in the contract.

Your strengths: multi-turn reasoning, MCP tools, security review, architecture, planning.
Your weaknesses: can over-engineer, verbose, context rot on long sessions, can hallucinate APIs.

When reviewing Codex's work: check for naive implementations, missed edge cases, architectural blind spots, security shortcuts.
When Codex reviews YOUR work: expect challenges on over-abstraction and unnecessary complexity. Take them seriously.

Protocol files live in .superreins/ (contract.yaml, handoffs/, ledger.md, failures.yaml, decisions.yaml).
- Before starting: read contract.yaml, failures.yaml, decisions.yaml, and any handoffs addressed to you.
- Before implementing: search failures.yaml for past failures with this technology/approach.
- When done with a task: write a handoff for the next agent + append to ledger.md.
- When you make a decision between alternatives: log it in the contract's decisions section.
- When something fails: log it in the contract's failures section.
- When reviewing: use the review lenses assigned in the contract (security, architecture, performance, tests, error-handling, devops, api-contract). Read the diff, challenge decisions, log findings. Never rubber-stamp.

## Enforcement hooks active:
- scope-guard: blocks writes to .env/credentials/keys, warns on system files
- branch-guard: blocks push to main/master, warns on force push and destructive git ops
- ledger-append: auto-logs file changes to .superreins/ledger.md

$CONTRACT_STATUS
$PENDING_HANDOFFS
</superreins>"

# Escape for JSON output
ESCAPED=$(echo "$CONTEXT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
# Remove surrounding quotes from json.dumps
ESCAPED=${ESCAPED:1:-1}

# Output in dual format (Claude Code + Cursor compatibility)
cat <<EOF
{
  "additional_context": "$ESCAPED",
  "hookSpecificOutput": {
    "additionalContext": "$ESCAPED"
  }
}
EOF
