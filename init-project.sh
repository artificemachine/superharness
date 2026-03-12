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

# --- Preflight: dependency check (skip on --help) ---
_preflight_deps() {
  local missing=()
  if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
    missing+=("bash 4+  (installed: $BASH_VERSION)  →  brew install bash")
  fi
  if ! command -v ruby >/dev/null 2>&1; then
    missing+=("ruby  →  brew install ruby   OR   https://www.ruby-lang.org/en/downloads/")
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    missing+=("python3  →  brew install python3   OR   https://www.python.org/downloads/")
  fi
  if [ ${#missing[@]} -gt 0 ]; then
    echo "superharness: missing required dependencies:" >&2
    for dep in "${missing[@]}"; do
      printf '  ✗ %s\n' "$dep" >&2
    done
    echo "" >&2
    echo "Fix the above, then re-run: superharness init" >&2
    exit 1
  fi
}
_skip_preflight=0
for _a in "$@"; do case "$_a" in -h|--help) _skip_preflight=1; break ;; esac; done
[ "$_skip_preflight" -eq 0 ] && _preflight_deps
unset _a _skip_preflight

usage() {
  cat << 'EOF'
Usage:
  init-project.sh [--dry-run] [--with-watcher] [--from-profile FILE] [--detect]
                  [--interactive] [PROJECT_NAME] [TECH_STACK] [STATUS]

Options:
  -h, --help              Show this help message and exit
  -n, --dry-run           Print planned actions without writing files
  --with-watcher          Also install macOS launchd background watcher (default: off)
  --from-profile FILE     Read project name, stack, and status from a profile.yaml
                          (written by an AI agent — see docs/INSTALL-AGENT.md)
  --detect                Run engine/detect.rb and use its output for project name,
                          stack, and status (skips positional args)
  --interactive           Run a guided questionnaire to configure and initialize
                          the project (reads answers from stdin, supports piped input)
EOF
}

DRY_RUN=0
WITH_WATCHER=0
FROM_PROFILE=""
DETECT_MODE=0
INTERACTIVE_MODE=0
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
    --with-watcher)
      WITH_WATCHER=1
      shift
      ;;
    --from-profile)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      FROM_PROFILE="$2"
      shift 2
      ;;
    --detect)
      DETECT_MODE=1
      shift
      ;;
    --interactive)
      INTERACTIVE_MODE=1
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
DATE="$(date +%Y-%m-%d)"
TEMPLATE_DIR="$SCRIPT_DIR/protocol/templates"

# --- Interactive mode: questionnaire ---
if [ "$INTERACTIVE_MODE" -eq 1 ]; then
  # Check if stdin is a terminal; if not, read from pipe (enables testing)
  _is_tty=0
  [ -t 0 ] && _is_tty=1

  # Run detect.rb to learn about this project
  DETECT_SCRIPT="$SCRIPT_DIR/engine/detect.rb"
  _detected_name="$(basename "$PROJECT_DIR")"
  _detected_stack="TBD"
  _detected_status="greenfield"
  _detected_repo="none"
  _detected_team="solo"
  if [ -f "$DETECT_SCRIPT" ]; then
    _det_out="$(ruby "$DETECT_SCRIPT" --project "$PROJECT_DIR" 2>/dev/null || true)"
    if [ -n "$_det_out" ]; then
      _det_parsed="$(printf '%s\n' "$_det_out" | ruby -ryaml -e "
        d = YAML.safe_load(STDIN.read) rescue {}
        d ||= {}
        puts d['project_name'] || ''
        puts d['stack']        || 'TBD'
        puts d['status']       || 'greenfield'
        puts d['repo']         || 'none'
        puts d['team_size']    || 'solo'
      " 2>/dev/null || true)"
      if [ -n "$_det_parsed" ]; then
        _n="$(printf '%s\n' "$_det_parsed" | sed -n '1p')"
        _s="$(printf '%s\n' "$_det_parsed" | sed -n '2p')"
        _st="$(printf '%s\n' "$_det_parsed" | sed -n '3p')"
        _r="$(printf '%s\n' "$_det_parsed" | sed -n '4p')"
        _t="$(printf '%s\n' "$_det_parsed" | sed -n '5p')"
        [ -n "$_n" ]  && _detected_name="$_n"
        [ -n "$_s" ]  && _detected_stack="$_s"
        [ -n "$_st" ] && _detected_status="$_st"
        [ -n "$_r" ]  && _detected_repo="$_r"
        [ -n "$_t" ]  && _detected_team="$_t"
      fi
    fi
  fi

  echo "superharness — interactive setup"
  echo "================================"
  echo ""
  echo "Detected: ${_detected_stack} project, ${_detected_repo} remote, ${_detected_team} developer"
  echo ""

  # Question 1: Autonomy level
  if [ "$_is_tty" -eq 1 ]; then
    printf '? Autonomy level:\n  1. autonomous  — agents act without asking\n  2. supervised  — agents explain, then proceed\n  3. approval-gated — agents wait for explicit approval\n> '
  else
    printf '? Autonomy level (1=autonomous 2=supervised 3=approval-gated): '
  fi
  read -r _autonomy_choice
  case "${_autonomy_choice:-2}" in
    1) _autonomy="autonomous" ;;
    3) _autonomy="approval-gated" ;;
    *) _autonomy="supervised" ;;
  esac

  # Question 2: Project goal
  if [ "$_is_tty" -eq 1 ]; then
    printf '\n? What are you working on right now? (one sentence)\n> '
  else
    printf '? Project goal: '
  fi
  read -r _goal_input
  _goal="${_goal_input:-TBD — describe the current objective}"

  # Question 3: Watcher (macOS only)
  _install_watcher=0
  if [ "$(uname -s)" = "Darwin" ]; then
    if [ "$_is_tty" -eq 1 ]; then
      printf '\n? Enable background watcher? [y/N]\n> '
    else
      printf '? Enable background watcher? [y/N]: '
    fi
    read -r _watcher_choice
    case "${_watcher_choice:-n}" in
      y|Y|yes|YES) _install_watcher=1 ;;
    esac
  fi

  echo ""
  echo "Initializing..."

  # Write profile.yaml to a temp file and delegate to --from-profile logic
  _tmp_profile="/tmp/superharness-profile-$$.yaml"
  cat > "$_tmp_profile" << PYAML
project_name: "${_detected_name}"
created: "${DATE}"
autonomy: ${_autonomy}
primary_agent: claude-code
stack: "${_detected_stack}"
repo: ${_detected_repo}
ci: none
team_size: ${_detected_team}
status: ${_detected_status}
existing_harness: []
PYAML

  FROM_PROFILE="$_tmp_profile"
  _INTERACTIVE_GOAL="$_goal"
  [ "$_install_watcher" -eq 1 ] && WITH_WATCHER=1
  unset _autonomy_choice _goal_input _watcher_choice _is_tty _install_watcher
  unset _detected_name _detected_stack _detected_status _detected_repo _detected_team
  unset _n _s _st _r _t _det_out _det_parsed _det_parsed
fi

# --- Resolve project metadata from profile, detect, or positional args ---
if [ -n "$FROM_PROFILE" ]; then
  # Read from agent-written profile.yaml
  if [ ! -f "$FROM_PROFILE" ]; then
    echo "Profile file not found: $FROM_PROFILE" >&2
    exit 1
  fi
  PROJECT_NAME="$(ruby -ryaml -rdate -e "d=YAML.safe_load(File.read(ARGV[0]),permitted_classes:[Date]); puts d['project_name'] || ''" "$FROM_PROFILE" 2>/dev/null)"
  TECH_STACK="$(ruby -ryaml -rdate -e "d=YAML.safe_load(File.read(ARGV[0]),permitted_classes:[Date]); puts d['stack'] || 'TBD'" "$FROM_PROFILE" 2>/dev/null)"
  STATUS="$(ruby -ryaml -rdate -e "d=YAML.safe_load(File.read(ARGV[0]),permitted_classes:[Date]); puts d['status'] || 'greenfield'" "$FROM_PROFILE" 2>/dev/null)"
  [ -z "$PROJECT_NAME" ] && PROJECT_NAME="$(basename "$PROJECT_DIR")"
  echo "Using profile: $FROM_PROFILE"
elif [ "$DETECT_MODE" -eq 1 ]; then
  # Run detect.rb and parse its output
  DETECT_SCRIPT="$SCRIPT_DIR/engine/detect.rb"
  if [ ! -f "$DETECT_SCRIPT" ]; then
    echo "engine/detect.rb not found. Cannot auto-detect." >&2
    exit 1
  fi
  DETECTED="$(ruby "$DETECT_SCRIPT" --project "$PROJECT_DIR")"
  _parsed="$(echo "$DETECTED" | ruby -ryaml -e "
    d = YAML.safe_load(STDIN.read)
    puts d['project_name'] || ''
    puts d['stack']        || 'TBD'
    puts d['status']       || 'greenfield'
  ")"
  PROJECT_NAME="$(echo "$_parsed" | sed -n '1p')"
  TECH_STACK="$(echo "$_parsed"  | sed -n '2p')"
  STATUS="$(echo "$_parsed"      | sed -n '3p')"
  unset _parsed
  [ -z "$PROJECT_NAME" ] && PROJECT_NAME="$(basename "$PROJECT_DIR")"
  echo "Auto-detected: name=$PROJECT_NAME stack=$TECH_STACK status=$STATUS"
else
  PROJECT_NAME="${1:-$(basename "$PROJECT_DIR")}"
  TECH_STACK="${2:-TBD}"
  STATUS="${3:-greenfield}"
fi

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

# Create heartbeat config
if [ -f "$TEMPLATE_DIR/heartbeat.yaml" ]; then
  cp "$TEMPLATE_DIR/heartbeat.yaml" "$PROJECT_DIR/.superharness/heartbeat.yaml"
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
IDENTITY_SOURCE="$TEMPLATE_DIR/identity-core.md"
if [ ! -f "$IDENTITY_SOURCE" ]; then
  echo "Missing identity template: $IDENTITY_SOURCE" >&2
  exit 1
fi
IDENTITY_CONTENT=$(cat "$IDENTITY_SOURCE")

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
# ${PROJECT_NAME}

## Identity
You are working for the project owner.

## This Project
EOF
    {
      printf '%s\n' "- What: ${PROJECT_NAME}"
      printf '%s\n' "- Stack: ${TECH_STACK}"
      printf '%s\n\n' "- Status: ${STATUS}"
    } >> "$PROJECT_DIR/AGENTS.md"
    cat >> "$PROJECT_DIR/AGENTS.md" << 'EOF'
## Cross-Agent Protocol
- Read `.superharness/contract.yaml` before starting work.
- Keep task status, ledger, and handoff updated before stopping.
EOF
  fi
  echo "Created: AGENTS.md"
else
  echo "Skipped: AGENTS.md (already exists)"
fi

# Generate SOUL.md from template
if [ ! -f "$PROJECT_DIR/SOUL.md" ]; then
  if [ -f "$TEMPLATE_DIR/SOUL.md.template" ]; then
    render_template "$TEMPLATE_DIR/SOUL.md.template" "$PROJECT_DIR/SOUL.md"
  else
    cat > "$PROJECT_DIR/SOUL.md" << EOF
# Soul — $(printf '%s' "$PROJECT_NAME")

## Operating Constraints
- Ship > plan. One focused task per session.
- Keep changes within the current contract scope.

## Guardrails
- Never edit .env, credentials, or secrets.
- Never push directly to main without human review.
- Run required checks before handoff or commit.
EOF
  fi
  echo "Created: SOUL.md"
else
  echo "Skipped: SOUL.md (already exists)"
fi

# Copy profile.yaml into .superharness/ if provided via --from-profile
if [ -n "$FROM_PROFILE" ] && [ -f "$FROM_PROFILE" ]; then
  cp "$FROM_PROFILE" "$PROJECT_DIR/.superharness/profile.yaml"
  echo "Created: .superharness/profile.yaml (from $FROM_PROFILE)"
fi

# Patch contract goal when coming from interactive mode
if [ "$INTERACTIVE_MODE" -eq 1 ] && [ -n "${_INTERACTIVE_GOAL:-}" ]; then
  _contract_file="$PROJECT_DIR/.superharness/contract.yaml"
  if [ -f "$_contract_file" ]; then
    python3 - "$_contract_file" "$_INTERACTIVE_GOAL" <<'PY'
import pathlib, sys, re
path = pathlib.Path(sys.argv[1])
goal = sys.argv[2]
text = path.read_text()
text = re.sub(r'^goal:.*$', f'goal: "{goal}"', text, flags=re.MULTILINE)
path.write_text(text)
PY
  fi
fi

# Clean up interactive temp profile
if [ "$INTERACTIVE_MODE" -eq 1 ] && [ -n "${_tmp_profile:-}" ] && [ -f "${_tmp_profile:-}" ]; then
  rm -f "$_tmp_profile"
fi

# Install launchd watcher only when explicitly requested.
if [ "$WITH_WATCHER" -eq 1 ]; then
  ENSURE_WATCHER="$SCRIPT_DIR/scripts/ensure-launchd-inbox-watcher.sh"
  if [ -x "$ENSURE_WATCHER" ]; then
    if bash "$ENSURE_WATCHER" --project "$PROJECT_DIR" >/dev/null 2>&1; then
      echo "Watcher: launchd inbox watcher is configured."
    else
      echo "Watcher: unable to auto-configure launchd watcher (continuing)."
    fi
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
echo "  0. Run 'superharness doctor --project .' to verify your setup"
echo "  1. Add a task:  superharness task create --project . --id my-task --title \"...\" --owner codex-cli"
echo "  2. Review CLAUDE.md and AGENTS.md — add project-specific context"
echo "  3. Add .superharness/ to .gitignore OR commit it (your choice)"
echo "  4. Start a Claude Code or Codex session — the hooks will pick it up"
echo ""
echo "Tip: To enable a background watcher (macOS only), re-run with --with-watcher"
echo "     or use: superharness watch --foreground --project . --interval 30"
