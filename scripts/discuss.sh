#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/../engine/discuss.rb"
DISCUSSION_ENGINE="$SCRIPT_DIR/../engine/discussion.rb"
INBOX_ENGINE="$SCRIPT_DIR/../engine/inbox.rb"

usage() {
  cat << 'USAGE'
Usage:
  discuss.sh <subcommand> [options]

Subcommands:
  status       Show pending approval gates
  approve      Approve a pending task
  start        Start a multi-agent discussion
  rounds       Show discussion round status
  consensus    Check consensus for a discussion
  list         List all discussions

Status options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --task TASK_ID     Optional task id filter

Approve options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --task TASK_ID     Required task id to approve
  --by ACTOR         Approver identity (default: owner)
  --note TEXT        Optional approval note

Start options:
  --project DIR      Project directory (default: current dir)
  --topic TEXT       Discussion topic (required)
  --task TASK_ID     Link to contract task (optional)
  --max-rounds N     Max deliberation rounds (default: 3)
  --exclude OWNER    Exclude an owner from the discussion (repeatable)

Rounds options:
  --project DIR      Project directory (default: current dir)
  --id DISC_ID       Discussion id (required)

Consensus options:
  --project DIR      Project directory (default: current dir)
  --id DISC_ID       Discussion id (required)

Examples:
  discuss.sh status --project .
  discuss.sh approve --project . --task <task-id> --by owner --note "Approved"
  discuss.sh start --project . --topic "Review watcher fixes" --max-rounds 3
  discuss.sh start --project . --topic "Review watcher fixes" --exclude codex-cli
  discuss.sh rounds --project . --id discuss-20260311T200000Z-1234-567
  discuss.sh consensus --project . --id discuss-20260311T200000Z-1234-567
  discuss.sh list --project .
USAGE
}

SUBCMD="${1:-}"
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  shift
fi

if [ -z "$SUBCMD" ] || [ "$SUBCMD" = "help" ] || [ "$SUBCMD" = "-h" ] || [ "$SUBCMD" = "--help" ]; then
  usage
  exit 0
fi

# Check Ruby availability
command -v ruby >/dev/null 2>&1 || { echo "Error: ruby is required but not found in PATH" >&2; exit 1; }

PROJECT_DIR="$(pwd)"
TASK_ID=""
ACTOR="owner"
NOTE=""
TOPIC=""
MAX_ROUNDS=3
DISC_ID=""
EXCLUDE_OWNERS=()  # owners to exclude from discussion

while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --task)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
      shift 2
      ;;
    --by)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      ACTOR="$2"
      shift 2
      ;;
    --note)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      NOTE="$2"
      shift 2
      ;;
    --topic)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TOPIC="$2"
      shift 2
      ;;
    --max-rounds)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      MAX_ROUNDS="$2"
      shift 2
      ;;
    --id)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      DISC_ID="$2"
      shift 2
      ;;
    --exclude)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      EXCLUDE_OWNERS+=("$2")
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

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
HARNESS_DIR="$PROJECT_DIR/.superharness"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
INBOX_FILE="$HARNESS_DIR/inbox.yaml"
DISCUSSIONS_DIR="$HARNESS_DIR/discussions"

[ -d "$HARNESS_DIR" ] || { echo "Missing .superharness directory: $HARNESS_DIR" >&2; exit 1; }

case "$SUBCMD" in
  status)
    [ -d "$HANDOFF_DIR" ] || { echo "No handoffs directory" >&2; exit 0; }
    ruby "$ENGINE" status \
      --handoff-dir "$HANDOFF_DIR" \
      ${TASK_ID:+--task "$TASK_ID"}
    ;;

  approve)
    [ -d "$HANDOFF_DIR" ] || { echo "No handoffs directory" >&2; exit 1; }
    [ -n "$TASK_ID" ] || { echo "--task is required for approve" >&2; exit 2; }
    ruby "$ENGINE" approve \
      --handoff-dir "$HANDOFF_DIR" \
      --contract-file "$CONTRACT_FILE" \
      --inbox-file "$INBOX_FILE" \
      --task "$TASK_ID" \
      --project-dir "$PROJECT_DIR" \
      --by "$ACTOR" \
      --note "$NOTE"
    ;;

  start)
    [ -n "$TOPIC" ] || { echo "--topic is required for start" >&2; exit 2; }

    # Read distinct owners from contract
    mapfile -t ALL_OWNERS < <(ruby -rpsych -rdate -e '
      doc = Psych.safe_load(File.read(ARGV[0]), permitted_classes: [Time, Date], aliases: false) || {}
      tasks = doc["tasks"] || []
      owners = tasks.select { |t| t.is_a?(Hash) }.map { |t| t["owner"] }.compact.uniq
      owners.each { |o| puts o }
    ' "$CONTRACT_FILE" 2>/dev/null)

    # Apply exclusions
    PARTICIPANTS=()
    for OWNER in "${ALL_OWNERS[@]}"; do
      EXCLUDED=false
      for EX in "${EXCLUDE_OWNERS[@]}"; do
        if [ "$OWNER" = "$EX" ]; then
          EXCLUDED=true
          break
        fi
      done
      if [ "$EXCLUDED" = false ]; then
        PARTICIPANTS+=("$OWNER")
      fi
    done

    if [ "${#PARTICIPANTS[@]}" -lt 2 ]; then
      echo "Error: discussions require at least 2 distinct task owners in contract (found: ${#PARTICIPANTS[@]} after exclusions)." >&2
      if [ "${#EXCLUDE_OWNERS[@]}" -gt 0 ]; then
        echo "Excluded: ${EXCLUDE_OWNERS[*]}" >&2
      fi
      echo "Add tasks for both claude-code and codex-cli before starting a discussion." >&2
      exit 2
    fi

    mkdir -p "$DISCUSSIONS_DIR"

    # Build participant args dynamically
    PARTICIPANT_ARGS=()
    for P in "${PARTICIPANTS[@]}"; do
      PARTICIPANT_ARGS+=(--participant "$P")
    done

    RESULT="$(ruby "$DISCUSSION_ENGINE" start \
      --discussions-dir "$DISCUSSIONS_DIR" \
      --topic "$TOPIC" \
      "${PARTICIPANT_ARGS[@]}" \
      --max-rounds "$MAX_ROUNDS" \
      --project "$PROJECT_DIR" \
      --created-by "$ACTOR" \
      ${TASK_ID:+--task "$TASK_ID"})"

    DISC_ID_NEW="$(printf '%s' "$RESULT" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["id"]')"
    DISC_DIR="$(printf '%s' "$RESULT" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["discussion_dir"]')"

    echo "Discussion started: $DISC_ID_NEW"
    echo "  Topic: $TOPIC"
    echo "  Max rounds: $MAX_ROUNDS"
    echo "  Participants: ${PARTICIPANTS[*]}"
    echo "  Directory: $DISC_DIR"

    # Create contract task for round 1
    TASK_SH="$SCRIPT_DIR/task.sh"
    ROUND_TASK_ID="${DISC_ID_NEW}/round-1"
    bash "$TASK_SH" create \
      --project "$PROJECT_DIR" \
      --id "$ROUND_TASK_ID" \
      --title "Discussion round 1: ${TOPIC}" \
      --owner "${PARTICIPANTS[0]}" \
      --status in_progress

    # Enqueue round 1 inbox items for each participant
    for AGENT in "${PARTICIPANTS[@]}"; do
      NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      ITEM_ID="$(date -u +%Y%m%dT%H%M%SZ)-${DISC_ID_NEW}-r1-${AGENT}-$$-$(( RANDOM * RANDOM ))"
      ruby "$INBOX_ENGINE" enqueue \
        --file "$INBOX_FILE" \
        --id "$ITEM_ID" \
        --to "$AGENT" \
        --task "${DISC_ID_NEW}/round-1" \
        --project "$PROJECT_DIR" \
        --priority 1 \
        --created-at "$NOW"
      echo "  Enqueued round 1 for $AGENT: $ITEM_ID"
    done
    ;;

  rounds)
    [ -n "$DISC_ID" ] || { echo "--id is required for rounds" >&2; exit 2; }
    DISC_DIR="$DISCUSSIONS_DIR/$DISC_ID"
    [ -d "$DISC_DIR" ] || { echo "Discussion not found: $DISC_ID" >&2; exit 1; }

    STATUS_JSON="$(ruby "$DISCUSSION_ENGINE" status --discussion-dir "$DISC_DIR")"
    printf '%s' "$STATUS_JSON" | ruby -rjson -e '
      d = JSON.parse(STDIN.read)
      puts "Discussion: #{d["id"]}"
      puts "  Topic: #{d["topic"]}"
      puts "  Status: #{d["status"]}"
      puts "  Round: #{d["current_round"]}/#{d["max_rounds"]}"
      puts "  Participants: #{d["participants"].join(", ")}"
      puts ""
      d["rounds"].each do |r|
        puts "  Round #{r["round"]}:"
        if r["submissions"].empty?
          puts "    (no submissions yet)"
        else
          r["submissions"].each do |s|
            puts "    #{s["agent"]}: verdict=#{s["verdict"]} (#{s["submitted_at"]})"
          end
        end
      end
    '
    ;;

  consensus)
    [ -n "$DISC_ID" ] || { echo "--id is required for consensus" >&2; exit 2; }
    DISC_DIR="$DISCUSSIONS_DIR/$DISC_ID"
    [ -d "$DISC_DIR" ] || { echo "Discussion not found: $DISC_ID" >&2; exit 1; }

    ruby "$DISCUSSION_ENGINE" check_consensus --discussion-dir "$DISC_DIR" | ruby -rjson -e '
      r = JSON.parse(STDIN.read)
      if r["consensus"]
        puts "CONSENSUS reached at round #{r["round"]}"
      else
        puts "No consensus at round #{r["round"]}"
        r["verdicts"].each { |a, v| puts "  #{a}: #{v}" }
      end
    '
    ;;

  list)
    mkdir -p "$DISCUSSIONS_DIR"
    RESULT="$(ruby "$DISCUSSION_ENGINE" list --discussions-dir "$DISCUSSIONS_DIR")"
    printf '%s' "$RESULT" | ruby -rjson -e '
      ds = JSON.parse(STDIN.read)
      if ds.empty?
        puts "No discussions."
      else
        ds.each do |d|
          puts "#{d["id"]}  status=#{d["status"]}  round=#{d["current_round"]}/#{d["max_rounds"]}  topic=#{d["topic"]}"
        end
      end
    '
    ;;

  *)
    echo "Unknown discuss subcommand: $SUBCMD" >&2
    usage >&2
    exit 2
    ;;
esac
