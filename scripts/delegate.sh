#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  delegate.sh --to claude-code|codex-cli [--project DIR] [--task TASK_ID] [--print-only] [--non-interactive] [--codex-bypass]

Options:
      --to TARGET     Required: claude-code or codex-cli
  -p, --project DIR   Project directory containing .superharness/ (default: current dir)
  -t, --task TASK_ID  Specific task id to run (otherwise read from latest handoff for target)
      --print-only    Print generated prompt and exit (do not launch CLI)
      --non-interactive  Launch target in non-interactive mode where supported
      --codex-bypass  For codex-cli only: use dangerous bypass in non-interactive mode
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR="$(pwd)"
TARGET=""
TASK_ID=""
PRINT_ONLY=0
NON_INTERACTIVE=0
CODEX_BYPASS=0

confirm_non_interactive_risk() {
  local risk_msg
  if [ "$TARGET" = "codex-cli" ] && [ "$CODEX_BYPASS" -eq 1 ]; then
    risk_msg="Risk: non-interactive Codex bypass disables sandbox and approval prompts. Continue?"
  else
    risk_msg="Risk: non-interactive mode runs without live user supervision. Continue?"
  fi

  if [ -n "${SUPERHARNESS_CONFIRM_NON_INTERACTIVE:-}" ]; then
    case "${SUPERHARNESS_CONFIRM_NON_INTERACTIVE}" in
      YES|yes|Y|y) return 0 ;;
    esac
  fi

  if [ ! -t 0 ]; then
    echo "Refusing non-interactive launch without explicit confirmation." >&2
    echo "Set SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES to allow unattended launch." >&2
    exit 1
  fi

  printf '%s [y/N]: ' "$risk_msg" >&2
  read -r ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *)
      echo "Aborted by user." >&2
      exit 1
      ;;
  esac
}

confirm_dangerous_flag_risk() {
  local env_name="$1"
  local risk_msg="$2"

  if [ -n "${!env_name:-}" ]; then
    case "${!env_name}" in
      YES|yes|Y|y) return 0 ;;
    esac
  fi

  if [ ! -t 0 ]; then
    echo "Refusing dangerous launch without explicit confirmation." >&2
    echo "Set ${env_name}=YES to allow this specific bypass." >&2
    exit 1
  fi

  printf '%s [y/N]: ' "$risk_msg" >&2
  read -r ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *)
      echo "Aborted by user." >&2
      exit 1
      ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --to)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TARGET="$2"
      shift 2
      ;;
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -t|--task)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
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

case "$TARGET" in
  claude-code|codex-cli) ;;
  *)
    echo "--to must be claude-code or codex-cli" >&2
    exit 2
    ;;
esac

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

# Read autonomy from profile.yaml if present
if [ -f "$PROJECT_DIR/.superharness/profile.yaml" ]; then
  _PROFILE_ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/engine/profile.rb"
  PROFILE_AUTONOMY="$(ruby "$_PROFILE_ENGINE" --project "$PROJECT_DIR" autonomy 2>/dev/null || echo 'approval-gated')"
  case "$PROFILE_AUTONOMY" in
    autonomous)
      export SUPERHARNESS_CONFIRM_NON_INTERACTIVE="${SUPERHARNESS_CONFIRM_NON_INTERACTIVE:-YES}"
      export SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS="${SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS:-YES}"
      ;;
    supervised)
      export SUPERHARNESS_CONFIRM_NON_INTERACTIVE="${SUPERHARNESS_CONFIRM_NON_INTERACTIVE:-YES}"
      ;;
  esac
fi

HARNESS_DIR="$PROJECT_DIR/.superharness"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
ENGINE_CONTRACT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/engine/contract.rb"

[ -f "$ENGINE_CONTRACT" ] || { echo "Missing contract engine: $ENGINE_CONTRACT" >&2; exit 1; }
[ -f "$CONTRACT_FILE" ] || { echo "Missing contract file: $CONTRACT_FILE" >&2; exit 1; }
[ -d "$HANDOFF_DIR" ] || { echo "Missing handoff directory: $HANDOFF_DIR" >&2; exit 1; }

CONTRACT_ID="$(ruby "$ENGINE_CONTRACT" contract_id --file "$CONTRACT_FILE" | tr -d '\"')"
[ -n "$CONTRACT_ID" ] || CONTRACT_ID="unknown-contract"

LATEST_HANDOFF=""
if [ -z "$TASK_ID" ]; then
  RES="$(ruby "$ENGINE_CONTRACT" latest_handoff_task --dir "$HANDOFF_DIR" --to "$TARGET")"
  if [ -n "$RES" ]; then
    TASK_ID="$(printf '%s' "$RES" | cut -d'|' -f1)"
    LATEST_HANDOFF="$(printf '%s' "$RES" | cut -d'|' -f2-)"
  fi
fi

if [ -z "$TASK_ID" ]; then
  echo "Could not determine task id. Provide --task TASK_ID or create a $TARGET handoff in $HANDOFF_DIR" >&2
  exit 1
fi

# Fetch acceptance criteria for the task (one per line, may be empty)
ACCEPTANCE_CRITERIA=""
if [ -n "$TASK_ID" ]; then
  AC_RAW="$(ruby "$ENGINE_CONTRACT" task_acceptance_criteria --file "$CONTRACT_FILE" --task "$TASK_ID" 2>/dev/null)" || true
  if [ -n "$AC_RAW" ]; then
    ACCEPTANCE_CRITERIA="

Acceptance criteria for this task:
$(printf '%s\n' "$AC_RAW" | while IFS= read -r line; do echo "- $line"; done)"
  fi
fi

AUTO_DIRECTIVE=""
if [ "$NON_INTERACTIVE" -eq 1 ]; then
  AUTO_DIRECTIVE="
This is an automated non-interactive run. Do not ask for confirmation or approval. Proceed and apply all changes immediately."
fi

# Discussion-round detection: task format is {discussion-id}/round-{N}
DISCUSSION_ID=""
DISCUSSION_ROUND=""
if [[ "$TASK_ID" =~ ^(discuss-[^/]+)/round-([0-9]+)$ ]]; then
  DISCUSSION_ID="${BASH_REMATCH[1]}"
  DISCUSSION_ROUND="${BASH_REMATCH[2]}"
fi

DISCUSSION_ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/engine/discussion.rb"
DISCUSSIONS_DIR="$HARNESS_DIR/discussions"

if [ -n "$DISCUSSION_ID" ] && [ -n "$DISCUSSION_ROUND" ]; then
  DISC_DIR="$DISCUSSIONS_DIR/$DISCUSSION_ID"
  if [ ! -d "$DISC_DIR" ]; then
    echo "Discussion directory not found: $DISC_DIR" >&2
    exit 1
  fi

  # Get round context (topic, prior positions)
  CONTEXT_JSON="$(ruby "$DISCUSSION_ENGINE" round_context \
    --discussion-dir "$DISC_DIR" \
    --round "$DISCUSSION_ROUND" \
    --agent "$TARGET" 2>/dev/null)" || { echo "Failed to get discussion context" >&2; exit 1; }

  DISC_TOPIC="$(printf '%s' "$CONTEXT_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["topic"]')"
  DISC_MAX="$(printf '%s' "$CONTEXT_JSON" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["max_rounds"]')"

  # Build prior round context for round 2+
  PRIOR_CONTEXT=""
  if [ "$DISCUSSION_ROUND" -gt 1 ]; then
    PRIOR_CONTEXT="$(printf '%s' "$CONTEXT_JSON" | ruby -rjson -e '
      ctx = JSON.parse(STDIN.read)
      ctx["prior_rounds"].each do |r|
        puts "--- Round #{r["round"]} ---"
        r["positions"].each do |p|
          puts "Agent: #{p["agent"]}"
          puts "Verdict: #{p["verdict"]}"
          puts "Position: #{p["position"]}"
          if p["points"].is_a?(Array) && !p["points"].empty?
            puts "Points:"
            p["points"].each do |pt|
              puts "  - #{pt["id"]}: #{pt["verdict"]} — #{pt["rationale"]}"
            end
          end
          puts ""
        end
      end
    ')"
  fi

  SUBMIT_PATH="$DISC_DIR/round-${DISCUSSION_ROUND}-${TARGET}.yaml"

  if [ "$DISCUSSION_ROUND" -eq 1 ]; then
    PROMPT="You are participating in a multi-agent discussion.
Topic: ${DISC_TOPIC}
You are: ${TARGET}
This is round ${DISCUSSION_ROUND} of ${DISC_MAX}.

Review the topic and write your position. Be specific about what you agree or disagree with.

When done, write a YAML file to: ${SUBMIT_PATH}
The file must have these fields:
  discussion_id: ${DISCUSSION_ID}
  round: ${DISCUSSION_ROUND}
  agent: ${TARGET}
  verdict: agree OR disagree OR partial
  position: your free-form analysis
  points: list of {id, verdict, rationale} for each sub-point
  submitted_at: (current UTC ISO 8601 timestamp)

If you agree with everything, set verdict: agree. Otherwise set verdict: disagree or partial and explain in points.
Read .superharness/discussions/${DISCUSSION_ID}/state.yaml for the full discussion context.
Read the handoff referenced in .superharness/contract.yaml for the task details.${AUTO_DIRECTIVE}"
  else
    PROMPT="You are participating in a multi-agent discussion.
Topic: ${DISC_TOPIC}
You are: ${TARGET}
This is round ${DISCUSSION_ROUND} of ${DISC_MAX}.

Here are the positions from prior rounds:
${PRIOR_CONTEXT}

Consider the other agent's position carefully. If you now agree with all points, set verdict: agree.
If you still disagree, explain specifically what remains unresolved.

Write your response to: ${SUBMIT_PATH}
The file must have these fields:
  discussion_id: ${DISCUSSION_ID}
  round: ${DISCUSSION_ROUND}
  agent: ${TARGET}
  verdict: agree OR disagree OR partial
  position: your free-form analysis
  points: list of {id, verdict, rationale} for each sub-point
  submitted_at: (current UTC ISO 8601 timestamp)

Read .superharness/discussions/${DISCUSSION_ID}/state.yaml for full context.${AUTO_DIRECTIVE}"
  fi

  echo "Project: $PROJECT_DIR"
  echo "Discussion: $DISCUSSION_ID"
  echo "Round: $DISCUSSION_ROUND"
  echo "Agent: $TARGET"
  echo "Topic: $DISC_TOPIC"
fi

if [ "$TARGET" = "claude-code" ] && [ -z "$DISCUSSION_ID" ]; then
  if [ -n "$LATEST_HANDOFF" ]; then
    PROMPT="continue contract
Read the latest handoff addressed to claude-code and execute task ${TASK_ID}.
Use scope, commands, and acceptance criteria from the handoff.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and refresh the handoff with outcomes.
Contract id: ${CONTRACT_ID}.${ACCEPTANCE_CRITERIA}${AUTO_DIRECTIVE}"
  else
    PROMPT="continue contract
No handoff exists yet for task ${TASK_ID}.
Read .superharness/contract.yaml directly and execute task ${TASK_ID}.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and create a new handoff with outcomes.
Contract id: ${CONTRACT_ID}.${ACCEPTANCE_CRITERIA}${AUTO_DIRECTIVE}"
  fi
else
  if [ -n "$LATEST_HANDOFF" ]; then
    PROMPT="continue contract
Read the latest handoff addressed to codex-cli and execute task ${TASK_ID}.
Use scope, commands, and acceptance criteria from the handoff.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and refresh the handoff with outcomes.
Contract id: ${CONTRACT_ID}.${ACCEPTANCE_CRITERIA}"
  else
    PROMPT="continue contract
No handoff exists yet for task ${TASK_ID}.
Read .superharness/contract.yaml directly and execute task ${TASK_ID}.
Update .superharness/contract.yaml task status, append .superharness/ledger.md, and create a new handoff with outcomes.
Contract id: ${CONTRACT_ID}.${ACCEPTANCE_CRITERIA}"
  fi
fi

if [ -z "$DISCUSSION_ID" ]; then
  echo "Project: $PROJECT_DIR"
  echo "Contract: $CONTRACT_ID"
  echo "Task: $TASK_ID"
  if [ -n "$LATEST_HANDOFF" ]; then
    echo "Handoff: $LATEST_HANDOFF"
  fi
fi

if [ "$PRINT_ONLY" -eq 1 ]; then
  echo ""
  echo "Generated prompt:"
  echo "-----------------"
  printf '%s\n' "$PROMPT"
  exit 0
fi

if [ "$NON_INTERACTIVE" -eq 1 ]; then
  confirm_non_interactive_risk
fi

# ---------------------------------------------------------------------------
# launch_agent TARGET LABEL
#   Launches $TARGET (claude-code or codex-cli) with $PROMPT.
#   LABEL is appended to the "Launching …" message (pass "" for the plain case).
# ---------------------------------------------------------------------------
launch_agent() {
  local target="$1"
  local label="${2:-}"
  local display_label=""
  [ -n "$label" ] && display_label=" $label"

  if [ "$target" = "claude-code" ]; then
    if ! command -v claude >/dev/null 2>&1; then
      echo "claude CLI is not installed or not on PATH" >&2
      exit 1
    fi
    echo ""
    if [ "$NON_INTERACTIVE" -eq 1 ]; then
      confirm_dangerous_flag_risk \
        "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS" \
        "Risk: Claude --dangerously-skip-permissions disables permission prompts. Continue?"
      echo "Launching Claude${display_label}..."
      cd "$PROJECT_DIR"
      exec claude -p --dangerously-skip-permissions "$PROMPT"
    fi
    echo "Launching Claude${display_label}..."
    cd "$PROJECT_DIR"
    exec claude "$PROMPT"
  else
    if ! command -v codex >/dev/null 2>&1; then
      echo "codex CLI is not installed or not on PATH" >&2
      exit 1
    fi
    echo ""
    if [ "$NON_INTERACTIVE" -eq 1 ]; then
      echo "Launching Codex${display_label}..."
      CODEX_COMMON_ARGS=(exec --skip-git-repo-check -C "$PROJECT_DIR")
      if [ "$CODEX_BYPASS" -eq 1 ]; then
        confirm_dangerous_flag_risk \
          "SUPERHARNESS_CONFIRM_CODEX_BYPASS" \
          "Risk: Codex bypass disables sandbox and approval prompts. Continue?"
        exec codex "${CODEX_COMMON_ARGS[@]}" --dangerously-bypass-approvals-and-sandbox "$PROMPT"
      fi
      exec codex "${CODEX_COMMON_ARGS[@]}" --full-auto "$PROMPT"
    fi
    echo "Launching Codex${display_label}..."
    exec codex -C "$PROJECT_DIR" "$PROMPT"
  fi
}

if [ -n "$DISCUSSION_ID" ]; then
  launch_agent "$TARGET" "for discussion round $DISCUSSION_ROUND"
fi

launch_agent "$TARGET" ""
