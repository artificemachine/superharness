#!/bin/bash
# superharness demo — zero-config walkthrough of the full task lifecycle.
# Creates a temporary project, runs a task through init → enqueue → dispatch
# (print-only) → hygiene → teardown. No agent CLIs required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat << 'USAGE'
Usage:
  superharness demo [--keep]

Run a self-contained walkthrough of the superharness task lifecycle using a
temporary directory. Nothing is installed; the temp dir is removed at exit.

Options:
  --keep      Keep the temporary project directory after the demo (prints path)
  -h, --help  Show this help message and exit
USAGE
}

KEEP=0
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

DEMO_DIR="$(mktemp -d "${TMPDIR:-/tmp}/superharness-demo-XXXXXX")"
cleanup() {
  if [ "$KEEP" -eq 0 ]; then
    rm -rf "$DEMO_DIR"
  else
    echo ""
    echo "Demo directory kept at: $DEMO_DIR"
  fi
}
trap cleanup EXIT

_step() {
  echo ""
  echo "── $1"
}

_run() {
  echo "  \$ $*"
  "$@"
}

echo ""
echo "superharness demo — task lifecycle walkthrough"
echo "==============================================="
echo "Temp project: $DEMO_DIR"

# ── Step 1: init ──────────────────────────────────────────────────────────────
_step "1 / 5  init"
cd "$DEMO_DIR"
_run bash "$ROOT_DIR/scripts/init-project.sh" --dry-run "Demo Project" "Bash" "greenfield"
_run bash "$ROOT_DIR/scripts/init-project.sh" "Demo Project" "Bash" "greenfield"

# ── Step 2: task create ───────────────────────────────────────────────────────
_step "2 / 5  task create"
_run bash "$ROOT_DIR/scripts/task.sh" create \
  --project "$DEMO_DIR" \
  --id demo-task \
  --title "Hello from superharness demo" \
  --owner codex-cli

# ── Step 3: enqueue ───────────────────────────────────────────────────────────
_step "3 / 5  enqueue"
_run bash "$ROOT_DIR/scripts/inbox-enqueue.sh" \
  --project "$DEMO_DIR" \
  --to codex-cli \
  --task demo-task \
  --priority 1

# ── Step 4: dispatch --print-only ────────────────────────────────────────────
_step "4 / 5  dispatch (print-only — no agent CLI needed)"
_run bash "$ROOT_DIR/scripts/inbox-dispatch.sh" \
  --project "$DEMO_DIR" \
  --to codex-cli \
  --print-only

# ── Step 5: hygiene ───────────────────────────────────────────────────────────
_step "5 / 5  hygiene check"
_run bash "$ROOT_DIR/scripts/check-contract-hygiene.sh" \
  --project "$DEMO_DIR" 2>/dev/null || true

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "==============================================="
echo "Demo complete. What just happened:"
echo ""
echo "  1. init      Created .superharness/ protocol files"
echo "  2. task      Added 'demo-task' to contract.yaml"
echo "  3. enqueue   Placed task in inbox.yaml queue"
echo "  4. dispatch  Generated the agent prompt (print-only)"
echo "  5. hygiene   Validated protocol state"
echo ""
echo "Next steps to try on a real project:"
echo "  superharness init \"My Project\" \"Python\" \"active\""
echo "  superharness doctor --project ."
echo "  superharness monitor-ui --project .   # browser dashboard"
echo ""
echo "To run real (non-print-only) dispatch you'll need an agent CLI:"
echo "  Claude Code:  npm install -g @anthropic-ai/claude-code"  # shipguard:ignore SC-003
echo "  Codex CLI:    npm install -g @openai/codex"  # shipguard:ignore SC-003
echo ""
echo "Full guide: docs/GUIDE.md"
