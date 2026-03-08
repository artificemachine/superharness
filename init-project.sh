#!/bin/bash
# Initialize a superharness instance in the current project.
# Run this from the root of any project to set up cross-agent workflows.
#
# Usage:
#   cd ~/my-project
#   bash /path/to/superharness/init-project.sh "My Project" "Python/FastAPI" "greenfield"
#
# Arguments:
#   $1 — Project name (e.g. "Acme Platform")
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
DATE="$(date +%Y-%m-%d)"
TEMPLATE_DIR="$SCRIPT_DIR/protocol/templates"

render_template() {
  local src="$1"
  local dst="$2"
  local identity_block="${3:-}"
  python3 - "$src" "$dst" "$PROJECT_NAME" "$TECH_STACK" "$STATUS" "$PROJECT_DIR" "$DATE" "$identity_block" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
project_name = sys.argv[3]
tech_stack = sys.argv[4]
status = sys.argv[5]
project_dir = sys.argv[6]
date = sys.argv[7]
identity_block = sys.argv[8]

text = src.read_text()
text = text.replace("{{PROJECT_NAME}}", project_name)
text = text.replace("{{TECH_STACK}}", tech_stack)
text = text.replace("{{STATUS}}", status)
text = text.replace("{{PROJECT_DIR}}", project_dir)
text = text.replace("{{DATE}}", date)
text = text.replace("{{IDENTITY_BLOCK}}", identity_block)
dst.write_text(text)
PY
}

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
#     by: claude-code | codex-cli | owner
#     status: accepted | superseded | deprecated
decisions: []
YAML

# Create empty ledger
if [ -f "$TEMPLATE_DIR/ledger.md" ]; then
  render_template "$TEMPLATE_DIR/ledger.md" "$PROJECT_DIR/.superharness/ledger.md"
else
  cat > "$PROJECT_DIR/.superharness/ledger.md" << EOF
# Ledger — $PROJECT_NAME

Append-only activity log. Never edit previous entries.
EOF
fi

# Create starter contract
if [ -f "$TEMPLATE_DIR/contract.yaml" ]; then
  render_template "$TEMPLATE_DIR/contract.yaml" "$PROJECT_DIR/.superharness/contract.yaml"
else
  cat > "$PROJECT_DIR/.superharness/contract.yaml" << EOF
# Active contract for $PROJECT_NAME
id: initial-setup
created: $(printf '%s' "$DATE")
created_by: owner
status: draft

goal: "TBD — describe the current objective"

tasks: []

decisions: []

failures: []
EOF
fi

cat >> "$PROJECT_DIR/.superharness/contract.yaml" << EOF

# Task schema (recommended):
# tasks:
#   - id: "task-id"
#     title: "Task title"
#     status: "todo|in_progress|done"
#     owner: "claude-code|codex-cli"
#     project_path: "$PROJECT_DIR"
EOF

# Generate CLAUDE.md from template
IDENTITY_CONTENT=$(cat "$SCRIPT_DIR/identity/core.md")

if [ ! -f "$PROJECT_DIR/CLAUDE.md" ]; then
  if [ -f "$TEMPLATE_DIR/CLAUDE.md.template" ]; then
    render_template "$TEMPLATE_DIR/CLAUDE.md.template" "$PROJECT_DIR/CLAUDE.md" "$(printf '%s' "$IDENTITY_CONTENT")"
  else
    cat > "$PROJECT_DIR/CLAUDE.md" << EOF
# $(printf '%s' "$PROJECT_NAME")

## Identity
$(printf '%s\n' "$IDENTITY_CONTENT")

## This Project
- What: $(printf '%s' "$PROJECT_NAME")
- Stack: $(printf '%s' "$TECH_STACK")
- Status: $(printf '%s' "$STATUS")

## Cross-Agent Protocol
- Read \`.superharness/contract.yaml\` before starting work.
- Keep task status, ledger, and handoff updated before stopping.
EOF
  fi
  echo "Created: CLAUDE.md"
else
  echo "Skipped: CLAUDE.md (already exists)"
fi

# Generate AGENTS.md from template
if [ ! -f "$PROJECT_DIR/AGENTS.md" ]; then
  if [ -f "$TEMPLATE_DIR/AGENTS.md.template" ]; then
    render_template "$TEMPLATE_DIR/AGENTS.md.template" "$PROJECT_DIR/AGENTS.md"
  else
    cat > "$PROJECT_DIR/AGENTS.md" << EOF
# $PROJECT_NAME

## Identity
You are working for the project owner.

## This Project
- What: $PROJECT_NAME
- Stack: $TECH_STACK
- Status: $STATUS

## Cross-Agent Protocol
- Read \`.superharness/contract.yaml\` before starting work.
- Keep task status, ledger, and handoff updated before stopping.
EOF
  fi
  echo "Created: AGENTS.md"
else
  echo "Skipped: AGENTS.md (already exists)"
fi

# Ensure launchd watcher is installed (macOS). Non-fatal if unavailable.
ENSURE_WATCHER="$SCRIPT_DIR/scripts/ensure-launchd-inbox-watcher.sh"
if [ -x "$ENSURE_WATCHER" ]; then
  if bash "$ENSURE_WATCHER" --project "$PROJECT_DIR" >/dev/null 2>&1; then
    echo "Watcher: launchd inbox watcher is configured."
  else
    echo "Watcher: unable to auto-configure launchd watcher (continuing)."
  fi
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
