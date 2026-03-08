#!/bin/bash
# Initialize a superharness instance in the current project.
# Run this from the root of any project to set up cross-agent workflows.
#
# Usage:
#   cd ~/my-project
#   bash /path/to/superharness/init-project.sh "My Project" "Python/FastAPI" "greenfield"
#
# Arguments:
#   $1 — Project name (e.g. "Cypher Farms Infra")
#   $2 — Tech stack (e.g. "Proxmox/Ansible/Python")
#   $3 — Status (e.g. "greenfield", "active", "maintenance")
#
# Creates:
#   .superharness/           — cross-agent protocol instance
#   CLAUDE.md                — Claude Code project config
#   AGENTS.md                — Codex CLI project config

set -euo pipefail

usage() {
  cat << 'EOF'
Usage:
  init-project.sh [--dry-run] [PROJECT_NAME] [TECH_STACK] [STATUS]

Options:
  -h, --help      Show this help message and exit
  -n, --dry-run   Print planned actions without writing files
EOF
}

DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -n|--dry-run)
      DRY_RUN=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(pwd)"
PROJECT_NAME="${1:-$(basename "$PROJECT_DIR")}"
TECH_STACK="${2:-TBD}"
STATUS="${3:-greenfield}"

echo "superharness — init project"
echo "==========================="
echo "  Project:  $PROJECT_NAME"
echo "  Stack:    $TECH_STACK"
echo "  Status:   $STATUS"
echo "  Dir:      $PROJECT_DIR"
echo ""

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] Would create: .superharness/{handoffs,contracts,review-lenses}"
  echo "[dry-run] Would create: .superharness/{failures.yaml,decisions.yaml,ledger.md,contract.yaml}"
  echo "[dry-run] Would create if missing: CLAUDE.md, AGENTS.md"
  exit 0
fi

# Abort if already initialized
if [ -d "$PROJECT_DIR/.superharness" ]; then
  echo ".superharness/ already exists. Aborting."
  echo "To re-initialize, remove it first: rm -rf .superharness"
  exit 1
fi

# Create directory structure
mkdir -p "$PROJECT_DIR/.superharness/handoffs"
mkdir -p "$PROJECT_DIR/.superharness/contracts"
mkdir -p "$PROJECT_DIR/.superharness/review-lenses"

# Create empty persistent stores
cat > "$PROJECT_DIR/.superharness/failures.yaml" << 'YAML'
# Cross-agent failure memory
# Both Claude Code and Codex CLI read/write this file.
# Format:
#   - what: "brief description"
#     why_failed: "root cause"
#     date: YYYY-MM-DD
#     agent: claude-code | codex-cli
#     tech: "technology/library involved"
#     severity: minor | major | critical
#     promoted: false  # set true when added to CLAUDE.md/AGENTS.md "Do Not" section
failures: []
YAML

cat > "$PROJECT_DIR/.superharness/decisions.yaml" << 'YAML'
# Cross-agent decision records (ADR-lite)
# Both Claude Code and Codex CLI read/write this file.
# Format:
#   - id: "short-kebab-id"
#     what: "decision title"
#     why: "rationale"
#     alternatives: ["alt1", "alt2"]
#     date: YYYY-MM-DD
#     by: claude-code | codex-cli | maxime
#     status: accepted | superseded | deprecated
decisions: []
YAML

# Create empty ledger
cat > "$PROJECT_DIR/.superharness/ledger.md" << EOF
# Ledger — $PROJECT_NAME

Append-only activity log. Never edit previous entries.
EOF

# Create starter contract
DATE=$(date +%Y-%m-%d)
cat > "$PROJECT_DIR/.superharness/contract.yaml" << EOF
# Active contract for $PROJECT_NAME
id: initial-setup
created: $(printf '%s' "$DATE")
created_by: maxime
status: draft

goal: "TBD — describe the current objective"

tasks: []

decisions: []

failures: []
EOF

# Generate CLAUDE.md from template
IDENTITY_CONTENT=$(cat "$SCRIPT_DIR/identity/core.md")

if [ ! -f "$PROJECT_DIR/CLAUDE.md" ]; then
  cat > "$PROJECT_DIR/CLAUDE.md" << EOF
# $(printf '%s' "$PROJECT_NAME")

## Identity
$(printf '%s\n' "$IDENTITY_CONTENT")

## This Project
- What: $(printf '%s' "$PROJECT_NAME")
- Stack: $(printf '%s' "$TECH_STACK")
- Status: $(printf '%s' "$STATUS")

## Cross-Agent Protocol
This project uses superharness. Protocol files are in \`.superharness/\`.
- Read \`contract.yaml\` before starting any work.
- Read \`failures.yaml\` before implementing — search for past failures with this technology.
- Read \`decisions.yaml\` for architectural context.
- Read any handoffs in \`handoffs/\` addressed to \`claude-code\`.
- When you make a decision between alternatives: log it in the contract's decisions section.
- When something fails: log it in the contract's failures section.
- When you finish a task: update contract status, write a handoff, append to ledger.
- When reviewing Codex's work: use the review lenses assigned to the task in the contract.

## Session Lifecycle (Required)
- Start of task: read \`.superharness/contract.yaml\`, \`.superharness/failures.yaml\`, \`.superharness/decisions.yaml\`, and relevant handoffs.
- During task: stay in assigned scope; log important tradeoffs in contract decisions.
- End of task: update contract task status, append one line to \`.superharness/ledger.md\`, and create/update a handoff file in \`.superharness/handoffs/\`.
- If blocked/failure: log the failure in contract failures (and promote reusable failures to \`failures.yaml\`).

## Operator Shortcuts
- \`continue contract\`: resume active contract and execute the full lifecycle automatically.
- \`close task <task_id>\`: mark task status, append ledger, and write handoff before stopping.

## Delegation Prompting Rule
When the user asks to read the contract (or equivalent), do this:
1. Read \`.superharness/contract.yaml\`.
2. Summarize contract id, status, and tasks with owner/status.
3. If any task is \`todo\` or \`in_progress\` and owner is \`codex-cli\`, ask:
   "Do you want me to delegate \`<task_id>\` to codex-cli now?"
4. If user says yes:
   - set task status to \`in_progress\` (if needed),
   - create/update \`.superharness/handoffs/<DATE>-<TASK_ID>.yaml\` addressed to \`codex-cli\`,
   - append one line to \`.superharness/ledger.md\`,
   - return the exact Codex kickoff prompt.

## Trigger Phrase: contract today
When the user says \`contract today\`, treat it as an explicit request to run the full Delegation Prompting Rule above.

## Review Lenses
When reviewing, check the \`review_lenses\` field on the task. Apply only the assigned lenses:
- security: auth, secrets, injection, data exposure
- architecture: patterns, coupling, dependency direction
- performance: N+1 queries, memory, scaling
- tests: coverage, edge cases, determinism
- error-handling: failure modes, logging, graceful degradation
- devops: config, CI/CD, observability
- api-contract: backwards compatibility, versioning

## Do Not
<!-- Promoted failures go here — paste from .superharness/failures.yaml when severity=critical -->

## Project Rules
- Security: never commit secrets, never skip security scan
- Branches: feature branches, never push to main
- Tests: run before every handoff
EOF
  echo "Created: CLAUDE.md"
else
  echo "Skipped: CLAUDE.md (already exists)"
fi

# Generate AGENTS.md from template
if [ ! -f "$PROJECT_DIR/AGENTS.md" ]; then
  cat > "$PROJECT_DIR/AGENTS.md" << 'AGENTSEOF'
# {{PROJECT_NAME}}

## Identity
You are working for Maxime Roy. Solo dev, 15+ yrs. C++/Python/Rust/Solidity.
Constraints: 10-20 hrs/week side projects. Evenings + weekends. Ship > plan.

Anti-patterns to guard against:
1. Scope creep — don't start features outside the current task
2. Over-planning — implement, don't plan more
3. Shiny object — use what's already chosen, don't switch tools

## Cross-Agent Protocol
You are one of two senior devs. The other is Claude Code.
You both build AND review each other's work. Neither is the boss.
Maxime is the tech lead — he assigns roles per task in the contract.

Your strengths: fast sandboxed execution, test-driven, focused single-task work, headless batch.
Your weaknesses: limited context (no MCP/browser), can miss big picture, no memory between runs, may choose naive solutions.

When reviewing Claude's work: check for over-abstraction, unnecessary layers, verbose code, hallucinated dependencies.
When Claude reviews YOUR work: expect challenges on edge cases and architectural impact. Take them seriously.

Protocol files are in `.superharness/`.
- Read `contract.yaml` before starting any work. Find YOUR assigned tasks.
- Read `failures.yaml` before implementing — search for past failures with this technology.
- Read `decisions.yaml` for architectural context.
- Read any handoffs in `handoffs/` addressed to `codex-cli`.
- When you make a decision between alternatives: log it in the contract's decisions section.
- When something fails: log it in the contract's failures section.
- When you finish a task: update contract status, write a handoff YAML, append to `ledger.md`.
- When reviewing: use the review lenses assigned to the task in the contract. Never rubber-stamp.

## Session Lifecycle (Required)
- Start of task: read `.superharness/contract.yaml`, `.superharness/failures.yaml`, `.superharness/decisions.yaml`, and relevant handoffs.
- During task: stay in assigned scope; log important tradeoffs in contract decisions.
- End of task: update contract task status, append one line to `.superharness/ledger.md`, and create/update a handoff file in `.superharness/handoffs/`.
- If blocked/failure: log the failure in contract failures (and promote reusable failures to `failures.yaml`).

## Operator Shortcuts
- `continue contract`: resume active contract and execute the full lifecycle automatically.
- `close task <task_id>`: mark task status, append ledger, and write handoff before stopping.

## Delegation Prompting Rule
When the user asks to read the contract (or equivalent), do this:
1. Read `.superharness/contract.yaml`.
2. Summarize contract id, status, and tasks with owner/status.
3. If any task is `todo` or `in_progress` and owner is `claude-code`, ask:
   "Do you want me to delegate `<task_id>` to claude-code now?"
4. If user says yes:
   - set task status to `in_progress` (if needed),
   - create/update `.superharness/handoffs/<DATE>-<TASK_ID>.yaml` addressed to `claude-code`,
   - append one line to `.superharness/ledger.md`,
   - return the exact Claude kickoff prompt.

## Trigger Phrase: contract today
When the user says `contract today`, treat it as an explicit request to run the full Delegation Prompting Rule above.

## Review Lenses
When reviewing, check the `review_lenses` field on the task. Apply only the assigned lenses:
- security: auth, secrets, injection, data exposure
- architecture: patterns, coupling, dependency direction
- performance: N+1 queries, memory, scaling
- tests: coverage, edge cases, determinism
- error-handling: failure modes, logging, graceful degradation
- devops: config, CI/CD, observability
- api-contract: backwards compatibility, versioning

## Handoff Format
When you complete a task, create `.superharness/handoffs/<DATE>-<TASK_ID>.yaml`:
```yaml
from: codex-cli
to: claude-code
date: <ISO_DATETIME>
contract: <CONTRACT_ID>
task: <TASK_ID>
context:
  branch: <BRANCH>
  files_changed: []
  tests: "X/Y passing"
  build: "clean|failing"
what_was_done: |
  Brief summary of what you implemented.
what_to_check: |
  - Things the reviewer should look at
review_findings: |
  - Findings per review lens (if this was a review task)
do_not:
  - Things that are out of scope
```

## Do Not
<!-- Promoted failures go here — paste from .superharness/failures.yaml when severity=critical -->

## Rules
- Never edit .env, credentials, tokens
- Never skip tests before handoff
- Never push directly to main
- Stay in scope. If something needs doing but isn't in the contract, note it in the handoff — don't do it.

## This Project
AGENTSEOF
  # Replace the placeholder with actual project info
  python3 - "$PROJECT_DIR/AGENTS.md" "$PROJECT_NAME" << 'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
project_name = sys.argv[2]
path.write_text(path.read_text().replace("{{PROJECT_NAME}}", project_name))
PY
  echo "- What: $PROJECT_NAME" >> "$PROJECT_DIR/AGENTS.md"
  echo "- Stack: $TECH_STACK" >> "$PROJECT_DIR/AGENTS.md"
  echo "- Status: $STATUS" >> "$PROJECT_DIR/AGENTS.md"
  echo "Created: AGENTS.md"
else
  echo "Skipped: AGENTS.md (already exists)"
fi

echo ""
echo "Done. Project initialized with superharness."
echo ""
echo "Directory structure:"
echo "  .superharness/"
echo "  ├── contract.yaml       ← edit this with your first task"
echo "  ├── contracts/           ← completed contracts archive"
echo "  ├── handoffs/            ← agent handoff files"
echo "  ├── review-lenses/       ← project-specific lenses (optional)"
echo "  ├── failures.yaml        ← cross-agent failure memory"
echo "  ├── decisions.yaml       ← cross-agent decision records"
echo "  └── ledger.md            ← append-only activity log"
echo ""
echo "Next steps:"
echo "  1. Edit .superharness/contract.yaml with your first task"
echo "  2. Review CLAUDE.md and AGENTS.md — add project-specific context"
echo "  3. Add .superharness/ to .gitignore OR commit it (your choice)"
echo "  4. Start a Claude Code or Codex session — the hooks will pick it up"
