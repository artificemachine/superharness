#!/usr/bin/env ruby
# frozen_string_literal: true

# Multi-round discussion engine for agent-to-agent deliberation.
# Two agents review a topic, read each other's positions, and iterate
# until they reach consensus or hit the max round limit.
#
# State lives in .superharness/discussions/{id}/state.yaml
# Per-round positions: .superharness/discussions/{id}/round-{N}-{agent}.yaml

require "optparse"
require "yaml"
require "json"
require "time"
require "fileutils"
require_relative "file_utils"

# Convenience delegates to shared FileUtils_SH module.
def with_file_lock(path, timeout: 5, &block)
  FileUtils_SH.with_file_lock(path, timeout: timeout, &block)
end

def load_yaml(path, expected_class)
  FileUtils_SH.load_yaml(path, expected_class)
end

def atomic_write(path, content)
  FileUtils_SH.atomic_write(path, content)
end

def generate_id
  "discuss-#{Time.now.utc.strftime('%Y%m%dT%H%M%SZ')}-#{$$}-#{rand(1_000_000_000)}"
end

def round_file(discussion_dir, round, agent)
  File.join(discussion_dir, "round-#{round}-#{agent}.yaml")
end

def state_file(discussion_dir)
  File.join(discussion_dir, "state.yaml")
end

# --- Commands ---

def cmd_start(discussions_dir:, topic:, participants:, max_rounds:, task_id:, project:, created_by:)
  id = generate_id
  discussion_dir = File.join(discussions_dir, id)
  FileUtils.mkdir_p(discussion_dir)

  state = {
    "id" => id,
    "topic" => topic,
    "participants" => participants,
    "max_rounds" => max_rounds,
    "current_round" => 1,
    "status" => "active",
    "created_at" => Time.now.utc.iso8601,
    "created_by" => created_by,
    "project" => project,
    "task_id" => task_id.to_s.empty? ? nil : task_id
  }

  sf = state_file(discussion_dir)
  atomic_write(sf, YAML.dump(state))

  puts JSON.generate({
    "id" => id,
    "discussion_dir" => discussion_dir,
    "status" => "active",
    "current_round" => 1,
    "participants" => participants
  })
  0
end

def cmd_submit_round(discussion_dir:, round:, agent:, verdict:, position:, points_file:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  with_file_lock(sf) do
    state = load_yaml(sf, Hash)
    abort("Discussion is not active (status=#{state['status']})") unless state["status"] == "active"
    abort("Agent '#{agent}' is not a participant") unless state["participants"].include?(agent)
    abort("Round #{round} != current round #{state['current_round']}") unless round == state["current_round"]

    rf = round_file(discussion_dir, round, agent)
    abort("Round #{round} already submitted by #{agent}") if File.exist?(rf)

    points = []
    if points_file && File.exist?(points_file)
      raw = load_yaml(points_file, Array)
      points = raw if raw.is_a?(Array)
    end

    doc = {
      "discussion_id" => state["id"],
      "round" => round,
      "agent" => agent,
      "verdict" => verdict,
      "position" => position,
      "points" => points,
      "submitted_at" => Time.now.utc.iso8601
    }

    atomic_write(rf, YAML.dump(doc))
  end

  puts JSON.generate({"submitted" => true, "round" => round, "agent" => agent, "verdict" => verdict})
  0
end

def cmd_check_round(discussion_dir:, round:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  state = load_yaml(sf, Hash)
  participants = state["participants"] || []
  done = []
  pending = []

  participants.each do |agent|
    rf = round_file(discussion_dir, round, agent)
    if File.exist?(rf)
      done << agent
    else
      pending << agent
    end
  end

  puts JSON.generate({
    "complete" => pending.empty?,
    "round" => round,
    "agents_done" => done,
    "agents_pending" => pending
  })
  0
end

def cmd_check_consensus(discussion_dir:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  state = load_yaml(sf, Hash)
  round = state["current_round"]
  participants = state["participants"] || []

  verdicts = {}
  participants.each do |agent|
    rf = round_file(discussion_dir, round, agent)
    if File.exist?(rf)
      doc = load_yaml(rf, Hash)
      verdicts[agent] = doc["verdict"].to_s.downcase
    end
  end

  all_submitted = verdicts.size == participants.size
  consensus = all_submitted && verdicts.values.all? { |v| v == "agree" }

  puts JSON.generate({
    "consensus" => consensus,
    "round" => round,
    "verdicts" => verdicts,
    "all_submitted" => all_submitted
  })
  0
end

def cmd_advance(discussion_dir:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  result = nil
  with_file_lock(sf) do
    state = load_yaml(sf, Hash)
    abort("Discussion is not active (status=#{state['status']})") unless state["status"] == "active"

    round = state["current_round"]
    participants = state["participants"] || []
    max_rounds = state["max_rounds"] || 3

    # Check all submitted
    all_done = participants.all? { |a| File.exist?(round_file(discussion_dir, round, a)) }
    abort("Round #{round} is not complete yet") unless all_done

    # Check consensus
    verdicts = {}
    participants.each do |agent|
      doc = load_yaml(round_file(discussion_dir, round, agent), Hash)
      verdicts[agent] = doc["verdict"].to_s.downcase
    end
    consensus = verdicts.values.all? { |v| v == "agree" }

    if consensus
      state["status"] = "consensus"
      state["closed_at"] = Time.now.utc.iso8601
      state["consensus_round"] = round
      atomic_write(sf, YAML.dump(state))
      result = {"action" => "closed", "reason" => "consensus", "round" => round}
    elsif round >= max_rounds
      state["status"] = "no_consensus"
      state["closed_at"] = Time.now.utc.iso8601
      atomic_write(sf, YAML.dump(state))
      result = {"action" => "closed", "reason" => "max_rounds_reached", "round" => round}
    else
      state["current_round"] = round + 1
      atomic_write(sf, YAML.dump(state))
      result = {"action" => "advanced", "next_round" => round + 1}
    end
  end

  puts JSON.generate(result) if result
  0
end

def cmd_status(discussion_dir:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  state = load_yaml(sf, Hash)
  rounds_info = []
  (1..state["current_round"]).each do |r|
    round_data = {"round" => r, "submissions" => []}
    (state["participants"] || []).each do |agent|
      rf = round_file(discussion_dir, r, agent)
      if File.exist?(rf)
        doc = load_yaml(rf, Hash)
        round_data["submissions"] << {
          "agent" => agent,
          "verdict" => doc["verdict"],
          "submitted_at" => doc["submitted_at"]
        }
      end
    end
    rounds_info << round_data
  end

  output = state.merge("rounds" => rounds_info)
  puts JSON.generate(output)
  0
end

def cmd_list(discussions_dir:)
  unless File.directory?(discussions_dir)
    puts "[]"
    return 0
  end

  discussions = []
  Dir.glob(File.join(discussions_dir, "*/state.yaml")).sort.each do |sf|
    state = load_yaml(sf, Hash)
    discussions << {
      "id" => state["id"],
      "topic" => state["topic"],
      "status" => state["status"],
      "current_round" => state["current_round"],
      "max_rounds" => state["max_rounds"],
      "participants" => state["participants"],
      "dir" => File.dirname(sf)
    }
  end

  puts JSON.generate(discussions)
  0
end

def cmd_close(discussion_dir:, outcome:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  with_file_lock(sf) do
    state = load_yaml(sf, Hash)
    state["status"] = outcome
    state["closed_at"] = Time.now.utc.iso8601
    atomic_write(sf, YAML.dump(state))
  end

  puts JSON.generate({"closed" => true, "outcome" => outcome})
  0
end

def cmd_round_context(discussion_dir:, round:, agent:)
  sf = state_file(discussion_dir)
  abort("Discussion not found: #{discussion_dir}") unless File.exist?(sf)

  state = load_yaml(sf, Hash)
  participants = state["participants"] || []
  other_agents = participants.reject { |a| a == agent }

  context = {
    "discussion_id" => state["id"],
    "topic" => state["topic"],
    "round" => round,
    "max_rounds" => state["max_rounds"],
    "agent" => agent,
    "other_agents" => other_agents,
    "prior_rounds" => []
  }

  # Include all prior round files
  (1...round).each do |r|
    round_data = {"round" => r, "positions" => []}
    participants.each do |a|
      rf = round_file(discussion_dir, r, a)
      if File.exist?(rf)
        doc = load_yaml(rf, Hash)
        round_data["positions"] << doc
      end
    end
    context["prior_rounds"] << round_data
  end

  puts JSON.generate(context)
  0
end

# --- CLI ---

cmd = ARGV.shift
case cmd
when "start"
  opts = {participants: [], max_rounds: 3, created_by: "owner"}
  OptionParser.new do |o|
    o.on("--discussions-dir DIR") { |v| opts[:discussions_dir] = v }
    o.on("--topic TEXT") { |v| opts[:topic] = v }
    o.on("--participant AGENT") { |v| opts[:participants] << v }
    o.on("--max-rounds N", Integer) { |v| opts[:max_rounds] = v }
    o.on("--task TASK_ID") { |v| opts[:task_id] = v }
    o.on("--project DIR") { |v| opts[:project] = v }
    o.on("--created-by ACTOR") { |v| opts[:created_by] = v }
  end.parse!(ARGV)
  abort("--discussions-dir is required") unless opts[:discussions_dir]
  abort("--topic is required") unless opts[:topic]
  abort("Need at least 2 --participant flags") if opts[:participants].size < 2
  abort("--project is required") unless opts[:project]
  exit cmd_start(
    discussions_dir: opts[:discussions_dir],
    topic: opts[:topic],
    participants: opts[:participants],
    max_rounds: opts[:max_rounds],
    task_id: opts[:task_id],
    project: opts[:project],
    created_by: opts[:created_by]
  )

when "submit_round"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
    o.on("--round N", Integer) { |v| opts[:round] = v }
    o.on("--agent AGENT") { |v| opts[:agent] = v }
    o.on("--verdict TEXT") { |v| opts[:verdict] = v }
    o.on("--position TEXT") { |v| opts[:position] = v }
    o.on("--points-file FILE") { |v| opts[:points_file] = v }
  end.parse!(ARGV)
  %i[discussion_dir round agent verdict position].each do |k|
    abort("--#{k.to_s.tr('_', '-')} is required") if opts[k].nil?
  end
  exit cmd_submit_round(
    discussion_dir: opts[:discussion_dir],
    round: opts[:round],
    agent: opts[:agent],
    verdict: opts[:verdict],
    position: opts[:position],
    points_file: opts[:points_file]
  )

when "check_round"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
    o.on("--round N", Integer) { |v| opts[:round] = v }
  end.parse!(ARGV)
  abort("--discussion-dir is required") unless opts[:discussion_dir]
  abort("--round is required") unless opts[:round]
  exit cmd_check_round(discussion_dir: opts[:discussion_dir], round: opts[:round])

when "check_consensus"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
  end.parse!(ARGV)
  abort("--discussion-dir is required") unless opts[:discussion_dir]
  exit cmd_check_consensus(discussion_dir: opts[:discussion_dir])

when "advance"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
  end.parse!(ARGV)
  abort("--discussion-dir is required") unless opts[:discussion_dir]
  exit cmd_advance(discussion_dir: opts[:discussion_dir])

when "status"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
  end.parse!(ARGV)
  abort("--discussion-dir is required") unless opts[:discussion_dir]
  exit cmd_status(discussion_dir: opts[:discussion_dir])

when "list"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussions-dir DIR") { |v| opts[:discussions_dir] = v }
  end.parse!(ARGV)
  abort("--discussions-dir is required") unless opts[:discussions_dir]
  exit cmd_list(discussions_dir: opts[:discussions_dir])

when "close"
  opts = {outcome: "cancelled"}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
    o.on("--outcome TEXT") { |v| opts[:outcome] = v }
  end.parse!(ARGV)
  abort("--discussion-dir is required") unless opts[:discussion_dir]
  exit cmd_close(discussion_dir: opts[:discussion_dir], outcome: opts[:outcome])

when "round_context"
  opts = {}
  OptionParser.new do |o|
    o.on("--discussion-dir DIR") { |v| opts[:discussion_dir] = v }
    o.on("--round N", Integer) { |v| opts[:round] = v }
    o.on("--agent AGENT") { |v| opts[:agent] = v }
  end.parse!(ARGV)
  %i[discussion_dir round agent].each do |k|
    abort("--#{k.to_s.tr('_', '-')} is required") if opts[k].nil?
  end
  exit cmd_round_context(discussion_dir: opts[:discussion_dir], round: opts[:round], agent: opts[:agent])

else
  abort("Usage: discussion.rb <start|submit_round|check_round|check_consensus|advance|status|list|close|round_context> [options]")
end
