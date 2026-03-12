#!/usr/bin/env ruby
# frozen_string_literal: true

# detect.rb — Environment detection for superharness agent-install.
#
# Scans the project directory and local environment, outputs a YAML blob
# that an installing agent (or init --from-profile) can use.
#
# Usage:
#   ruby engine/detect.rb --project /path/to/project
#   ruby engine/detect.rb --project . --output /path/to/detected.yaml
#
# Output goes to stdout by default, or to --output file.

require "optparse"
require "json"
require "time"

SCRIPT_DIR = File.expand_path(File.dirname(__FILE__))

# --- Stack detection table ---
# Maps file/dir patterns to stack labels.
STACK_SIGNALS = [
  { glob: "package.json",          label: "Node" },
  { glob: "tsconfig.json",         label: "TypeScript" },
  { glob: "pyproject.toml",        label: "Python" },
  { glob: "requirements.txt",      label: "Python" },
  { glob: "setup.py",              label: "Python" },
  { glob: "Gemfile",               label: "Ruby" },
  { glob: "go.mod",                label: "Go" },
  { glob: "Cargo.toml",            label: "Rust" },
  { glob: "pom.xml",               label: "Java" },
  { glob: "build.gradle",          label: "Kotlin/Java" },
  { glob: "build.gradle.kts",      label: "Kotlin" },
  { glob: "docker-compose.yml",    label: "Docker" },
  { glob: "docker-compose.yaml",   label: "Docker" },
  { glob: "Dockerfile",            label: "Docker" },
  { glob: "Makefile",              label: "Make" },
  { glob: "Justfile",              label: "Just" },
  { glob: "serverless.yml",        label: "Serverless" },
  { glob: "serverless.yaml",       label: "Serverless" },
].freeze

TERRAFORM_GLOB = "*.tf"

# --- CI detection ---
CI_SIGNALS = [
  { path: ".github/workflows", label: "github-actions" },
  { path: ".gitlab-ci.yml",    label: "gitlab-ci" },
  { path: "Jenkinsfile",       label: "jenkins" },
  { path: ".circleci",         label: "circleci" },
].freeze

# --- Harness artifact detection ---
HARNESS_SIGNALS = [
  { path: "CLAUDE.md",                          label: "claude-md" },
  { path: "AGENTS.md",                          label: "agents-md" },
  { path: ".cursor/rules",                      label: "cursor-rules" },
  { path: ".github/copilot-instructions.md",    label: "copilot-instructions" },
].freeze

def detect_stack(project_dir)
  labels = []
  STACK_SIGNALS.each do |sig|
    full = File.join(project_dir, sig[:glob])
    labels << sig[:label] if File.exist?(full)
  end
  # Terraform: check for any .tf files
  labels << "Terraform" unless Dir.glob(File.join(project_dir, TERRAFORM_GLOB)).empty?
  labels.uniq
end

def detect_agents
  agents = []
  agents << "claude-code" if system("command -v claude >/dev/null 2>&1")
  agents << "codex-cli"   if system("command -v codex >/dev/null 2>&1")
  agents
end

def git_repo?(project_dir)
  File.directory?(File.join(project_dir, ".git"))
end

def detect_repo(project_dir)
  return "none" unless git_repo?(project_dir)
  Dir.chdir(project_dir) do
    url = `git remote get-url origin 2>/dev/null`.strip
    return "none" if url.empty?
    return "github"    if url.include?("github.com")
    return "gitlab"    if url.include?("gitlab")
    return "bitbucket" if url.include?("bitbucket")
    "other"
  end
end

def detect_ci(project_dir)
  CI_SIGNALS.each do |sig|
    full = File.join(project_dir, sig[:path])
    return sig[:label] if File.exist?(full) || File.directory?(full)
  end
  "none"
end

def detect_team_size(project_dir)
  return "solo" unless git_repo?(project_dir)
  Dir.chdir(project_dir) do
    since = (Time.now - (90 * 86400)).strftime("%Y-%m-%d")
    authors = `git log --format='%ae' --since='#{since}' 2>/dev/null`.strip.split("\n").uniq
    count = authors.length
    return "solo"  if count <= 1
    return "small" if count <= 5
    "team"
  end
end

def detect_harness(project_dir)
  found = []
  HARNESS_SIGNALS.each do |sig|
    full = File.join(project_dir, sig[:path])
    found << sig[:label] if File.exist?(full)
  end
  found
end

def detect_status(project_dir)
  unless git_repo?(project_dir)
    readme = File.join(project_dir, "README.md")
    if File.exist?(readme)
      content = File.read(readme).downcase
      return "maintenance" if content.include?("maintenance") || content.include?("deprecated")
    end
    return "greenfield"
  end
  Dir.chdir(project_dir) do
    commits = `git rev-list --count HEAD 2>/dev/null`.strip.to_i
    return "greenfield" if commits <= 1
    readme = File.join(project_dir, "README.md")
    if File.exist?(readme)
      content = File.read(readme).downcase
      return "maintenance" if content.include?("maintenance") || content.include?("deprecated")
    end
    "active"
  end
end

def detect_project_name(project_dir)
  # package.json
  pkg = File.join(project_dir, "package.json")
  if File.exist?(pkg)
    begin
      data = JSON.parse(File.read(pkg))
      return data["name"] if data["name"] && !data["name"].empty?
    rescue JSON::ParserError
      # fall through
    end
  end
  # pyproject.toml — [project] name = "..."
  pyproject = File.join(project_dir, "pyproject.toml")
  if File.exist?(pyproject)
    content = File.read(pyproject)
    if (m = content.match(/^\[project\].*?^name\s*=\s*"([^"]+)"/m))
      return m[1]
    end
  end
  # Cargo.toml — [package] name = "..."
  cargo = File.join(project_dir, "Cargo.toml")
  if File.exist?(cargo)
    content = File.read(cargo)
    if (m = content.match(/^\[package\].*?^name\s*=\s*"([^"]+)"/m))
      return m[1]
    end
  end
  File.basename(File.expand_path(project_dir))
end

# --- Main ---

project_dir = Dir.pwd
output_path = nil

OptionParser.new do |opts|
  opts.banner = "Usage: detect.rb [--project DIR] [--output FILE]"
  opts.on("-p", "--project DIR", "Project directory (default: cwd)") { |v| project_dir = v }
  opts.on("-o", "--output FILE", "Write YAML to file instead of stdout") { |v| output_path = v }
  opts.on("-h", "--help", "Show help") { puts opts; exit }
end.parse!

project_dir = File.expand_path(project_dir)
unless File.directory?(project_dir)
  $stderr.puts "Not a directory: #{project_dir}"
  exit 1
end

already_initialized = File.directory?(File.join(project_dir, ".superharness"))

stack = detect_stack(project_dir)
agents = detect_agents
repo = detect_repo(project_dir)
ci = detect_ci(project_dir)
team_size = detect_team_size(project_dir)
harness = detect_harness(project_dir)
status = detect_status(project_dir)
name = detect_project_name(project_dir)

yaml_output = <<~YAML
  # Detected by superharness engine/detect.rb
  # #{Time.now.utc.iso8601}
  detected_at: "#{Time.now.utc.iso8601}"
  project_name: "#{name}"
  project_dir: "#{project_dir}"
  already_initialized: #{already_initialized}
  stack: "#{stack.join("/")}"
  agents_available:
  #{agents.empty? ? "  []" : agents.map { |a| "  - #{a}" }.join("\n")}
  repo: #{repo}
  ci: #{ci}
  team_size: #{team_size}
  status: #{status}
  existing_harness:
  #{harness.empty? ? "  []" : harness.map { |h| "  - #{h}" }.join("\n")}
YAML

if output_path
  File.write(output_path, yaml_output)
  $stderr.puts "Wrote: #{output_path}"
else
  puts yaml_output
end
