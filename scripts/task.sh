#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  task.sh <create|delete|status> [options]

Create options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --id TASK_ID       Task id
  --title TEXT       Task title
  --owner OWNER      claude-code|codex-cli
  --status STATUS    todo|in_progress|done (default: todo)
  --dependency ID    Optional task id this task depends on

Delete options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --id TASK_ID       Task id to remove

Status options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --id TASK_ID       Task id to update
  --status STATUS    todo|in_progress|done
  --actor ACTOR      Actor updating status (must match task owner)

If create fields are missing, interactive prompts are shown.
If no subcommand is provided, a guided prompt asks for create/delete/status.
USAGE
}

SUBCMD="${1:-}"
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then shift; fi
PROJECT_DIR="$(pwd)"
TASK_ID=""
TITLE=""
OWNER=""
STATUS="todo"
ACTOR=""
DEPENDENCY=""

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
    --actor)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      ACTOR="$2"
      shift 2
      ;;
    --dependency)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      DEPENDENCY="$2"
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
  echo "  3) status"
  printf "Select [1/2/3]: "
  read -r choice
  case "$choice" in
    1|create|Create) SUBCMD="create" ;;
    2|delete|Delete) SUBCMD="delete" ;;
    3|status|Status) SUBCMD="status" ;;
    *) echo "Invalid selection: $choice" >&2; exit 2 ;;
  esac
fi

case "$SUBCMD" in
  create|delete|status) ;;
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
  if [ -z "$DEPENDENCY" ] && [ -t 0 ]; then
    printf "Dependency task id (optional): "
    read -r DEPENDENCY || true
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

  ruby - "$CONTRACT_FILE" "$TASK_ID" "$TITLE" "$OWNER" "$STATUS" "$PROJECT_DIR" "$DEPENDENCY" <<'RUBY'
require "psych"
require "time"
require "date"

file, id, title, owner, status, project, dependency = ARGV

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
if !dependency.to_s.empty?
  abort("task '#{id}' cannot depend on itself") if dependency == id
  unless tasks.any? { |t| t.is_a?(Hash) && t["id"].to_s == dependency }
    abort("dependency task '#{dependency}' not found")
  end
end

task = {
  "id" => id,
  "title" => title,
  "owner" => owner,
  "status" => status,
  "project_path" => project
}
task["dependency"] = dependency unless dependency.to_s.empty?
tasks << task
doc["tasks"] = tasks

tmp = "#{file}.tmp.#{$$}"
File.write(tmp, Psych.dump(doc))
File.rename(tmp, file)
if dependency.to_s.empty?
  puts "Created task '#{id}' (owner=#{owner}, status=#{status})"
else
  puts "Created task '#{id}' (owner=#{owner}, status=#{status}, dependency=#{dependency})"
end
RUBY
elif [ "$SUBCMD" = "delete" ]; then
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
else
  if [ -z "$TASK_ID" ]; then
    printf "Task id to update: "
    read -r TASK_ID
  fi
  if [ -z "$STATUS" ]; then
    printf "New status (todo/in_progress/done): "
    read -r STATUS
  fi
  if [ -z "$ACTOR" ]; then
    printf "Actor (must match task owner): "
    read -r ACTOR
  fi

  case "$STATUS" in
    todo|in_progress|done) ;;
    *) echo "status must be todo, in_progress, or done" >&2; exit 2 ;;
  esac

  ruby - "$CONTRACT_FILE" "$TASK_ID" "$STATUS" "$ACTOR" <<'RUBY'
require "psych"
require "time"
require "date"

file, id, status, actor = ARGV

doc = Psych.safe_load(File.read(file), permitted_classes: [Time, Date], aliases: false) || {}
unless doc.is_a?(Hash)
  abort("contract.yaml must be a mapping")
end

tasks = doc["tasks"]
tasks = [] if tasks.nil?
unless tasks.is_a?(Array)
  abort("contract tasks must be a sequence")
end

task = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == id }
abort("task '#{id}' not found") if task.nil?
owner = task["owner"].to_s
abort("task '#{id}' has no owner set") if owner.empty?
dependency = task["dependency"].to_s

if actor != owner
  abort("forbidden: actor '#{actor}' cannot update task '#{id}' owned by '#{owner}'")
end

if !dependency.empty? && %w[in_progress done].include?(status)
  dep_task = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == dependency }
  if dep_task.nil?
    abort("task '#{id}' dependency '#{dependency}' not found")
  end
  dep_status = dep_task["status"].to_s
  if dep_status != "done"
    abort("blocked: task '#{id}' depends on '#{dependency}' (status=#{dep_status})")
  end
end

task["status"] = status
doc["tasks"] = tasks

tmp = "#{file}.tmp.#{$$}"
File.write(tmp, Psych.dump(doc))
File.rename(tmp, file)
puts "Updated task '#{id}' status=#{status} by actor=#{actor}"
RUBY
fi
