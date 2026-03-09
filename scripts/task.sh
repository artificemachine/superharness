#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  task.sh <create|delete> [options]

Create options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --id TASK_ID       Task id
  --title TEXT       Task title
  --owner OWNER      claude-code|codex-cli
  --status STATUS    todo|in_progress|done (default: todo)

Delete options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --id TASK_ID       Task id to remove

If create fields are missing, interactive prompts are shown.
If no subcommand is provided, a guided prompt asks for create/delete.
USAGE
}

SUBCMD="${1:-}"
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then shift; fi
PROJECT_DIR="$(pwd)"
TASK_ID=""
TITLE=""
OWNER=""
STATUS="todo"

while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --id)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
      shift 2
      ;;
    --title)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TITLE="$2"
      shift 2
      ;;
    --owner)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      OWNER="$2"
      shift 2
      ;;
    --status)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      STATUS="$2"
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

if [ -z "$SUBCMD" ]; then
  echo "Task action:"
  echo "  1) create"
  echo "  2) delete"
  printf "Select [1/2]: "
  read -r choice
  case "$choice" in
    1|create|Create) SUBCMD="create" ;;
    2|delete|Delete) SUBCMD="delete" ;;
    *) echo "Invalid selection: $choice" >&2; exit 2 ;;
  esac
fi

case "$SUBCMD" in
  create|delete) ;;
  *)
    usage >&2
    exit 2
    ;;
esac

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
CONTRACT_FILE="$PROJECT_DIR/.superharness/contract.yaml"
[ -f "$CONTRACT_FILE" ] || { echo "Missing contract file: $CONTRACT_FILE" >&2; exit 1; }

if [ "$SUBCMD" = "create" ]; then
  if [ -z "$TASK_ID" ]; then
    printf "Task id: "
    read -r TASK_ID
  fi
  if [ -z "$TITLE" ]; then
    printf "Task title: "
    read -r TITLE
  fi
  if [ -z "$OWNER" ]; then
    printf "Owner (claude-code/codex-cli): "
    read -r OWNER
  fi
  if [ -z "$STATUS" ]; then
    STATUS="todo"
  fi

  case "$OWNER" in
    claude-code|codex-cli) ;;
    *) echo "owner must be claude-code or codex-cli" >&2; exit 2 ;;
  esac
  case "$STATUS" in
    todo|in_progress|done) ;;
    *) echo "status must be todo, in_progress, or done" >&2; exit 2 ;;
  esac

  ruby - "$CONTRACT_FILE" "$TASK_ID" "$TITLE" "$OWNER" "$STATUS" "$PROJECT_DIR" <<'RUBY'
require "psych"
require "time"
require "date"

file, id, title, owner, status, project = ARGV

doc = Psych.safe_load(File.read(file), permitted_classes: [Time, Date], aliases: false) || {}
unless doc.is_a?(Hash)
  abort("contract.yaml must be a mapping")
end

tasks = doc["tasks"]
tasks = [] if tasks.nil?
unless tasks.is_a?(Array)
  abort("contract tasks must be a sequence")
end
if tasks.any? { |t| t.is_a?(Hash) && t["id"].to_s == id }
  abort("task '#{id}' already exists")
end

tasks << {
  "id" => id,
  "title" => title,
  "owner" => owner,
  "status" => status,
  "project_path" => project
}
doc["tasks"] = tasks

tmp = "#{file}.tmp.#{$$}"
File.write(tmp, Psych.dump(doc))
File.rename(tmp, file)
puts "Created task '#{id}' (owner=#{owner}, status=#{status})"
RUBY
else
  if [ -z "$TASK_ID" ]; then
    printf "Task id to delete: "
    read -r TASK_ID
  fi

  ruby - "$CONTRACT_FILE" "$TASK_ID" <<'RUBY'
require "psych"
require "time"
require "date"

file, id = ARGV

doc = Psych.safe_load(File.read(file), permitted_classes: [Time, Date], aliases: false) || {}
unless doc.is_a?(Hash)
  abort("contract.yaml must be a mapping")
end

tasks = doc["tasks"]
tasks = [] if tasks.nil?
unless tasks.is_a?(Array)
  abort("contract tasks must be a sequence")
end

before = tasks.length
tasks = tasks.reject { |t| t.is_a?(Hash) && t["id"].to_s == id }
if tasks.length == before
  abort("task '#{id}' not found")
end

doc["tasks"] = tasks
tmp = "#{file}.tmp.#{$$}"
File.write(tmp, Psych.dump(doc))
File.rename(tmp, file)
puts "Deleted task '#{id}'"
RUBY
fi
