"""Python port of engine/detect.rb.

Scans a project directory and local environment, outputs a YAML blob
that an installing agent (or init --from-profile) can use.

Usage:
    python3 -m superharness.engine.detect --project /path/to/project
    python3 -m superharness.engine.detect --project . --output /path/to/detected.yaml
"""
from __future__ import annotations

import glob as glob_mod
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from superharness.engine.errors import SuperharnessError, UsageError, handle_cli_error

import logging
logger = logging.getLogger(__name__)

# --- Stack detection table ---
STACK_SIGNALS = [
    ("package.json",       "Node"),
    ("tsconfig.json",      "TypeScript"),
    ("pyproject.toml",     "Python"),
    ("requirements.txt",   "Python"),
    ("setup.py",           "Python"),
    ("Gemfile",            "Ruby"),
    ("go.mod",             "Go"),
    ("Cargo.toml",         "Rust"),
    ("pom.xml",            "Java"),
    ("build.gradle",       "Kotlin/Java"),
    ("build.gradle.kts",   "Kotlin"),
    ("docker-compose.yml", "Docker"),
    ("docker-compose.yaml","Docker"),
    ("Dockerfile",         "Docker"),
    ("Makefile",           "Make"),
    ("Justfile",           "Just"),
    ("serverless.yml",     "Serverless"),
    ("serverless.yaml",    "Serverless"),
]

CI_SIGNALS = [
    (".github/workflows", "github-actions"),
    (".gitlab-ci.yml",    "gitlab-ci"),
    ("Jenkinsfile",       "jenkins"),
    (".circleci",         "circleci"),
]

HARNESS_SIGNALS = [
    ("CLAUDE.md",                       "claude-md"),
    ("AGENTS.md",                       "agents-md"),
    (".cursor/rules",                   "cursor-rules"),
    (".github/copilot-instructions.md", "copilot-instructions"),
]


def _git_repo(project_dir: Path) -> bool:
    return (project_dir / ".git").is_dir()


def detect_stack(project_dir: Path) -> list[str]:
    labels = []
    for filename, label in STACK_SIGNALS:
        if (project_dir / filename).exists():
            if label not in labels:
                labels.append(label)
    if glob_mod.glob(str(project_dir / "*.tf")):
        labels.append("Terraform")
    return labels


def detect_agents() -> list[str]:
    agents = []
    if _which("claude"):
        agents.append("claude-code")
    if _which("codex"):
        agents.append("codex-cli")
    return agents


def _which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def detect_repo(project_dir: Path) -> str:
    if not _git_repo(project_dir):
        return "none"
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_dir, capture_output=True, text=True, check=False,
        )
        url = result.stdout.strip()
        if not url:
            return "none"
        if "github.com" in url:
            return "github"
        if "gitlab" in url:
            return "gitlab"
        if "bitbucket" in url:
            return "bitbucket"
        return "other"
    except Exception as e:
        logger.warning("detect.py unexpected error: %s", e, exc_info=True)
        return "none"


def detect_ci(project_dir: Path) -> str:
    for path_str, label in CI_SIGNALS:
        full = project_dir / path_str
        if full.exists():
            return label
    return "none"


def detect_team_size(project_dir: Path) -> str:
    if not _git_repo(project_dir):
        return "solo"
    try:
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        result = subprocess.run(
            ["git", "log", "--format=%ae", f"--since={since}"],
            cwd=project_dir, capture_output=True, text=True, check=False,
        )
        authors = list({a for a in result.stdout.strip().splitlines() if a})
        count = len(authors)
        if count <= 1:
            return "solo"
        if count <= 5:
            return "small"
        return "team"
    except Exception as e:
        logger.warning("detect.py unexpected error: %s", e, exc_info=True)
        return "solo"


def detect_harness(project_dir: Path) -> list[str]:
    found = []
    for path_str, label in HARNESS_SIGNALS:
        if (project_dir / path_str).exists():
            found.append(label)
    return found


def detect_status(project_dir: Path) -> str:
    if not _git_repo(project_dir):
        readme = project_dir / "README.md"
        if readme.exists():
            content = readme.read_text(errors="replace").lower()
            if "maintenance" in content or "deprecated" in content:
                return "maintenance"
        return "greenfield"
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=project_dir, capture_output=True, text=True, check=False,
        )
        commits = int(result.stdout.strip() or "0")
        if commits <= 1:
            return "greenfield"
        readme = project_dir / "README.md"
        if readme.exists():
            content = readme.read_text(errors="replace").lower()
            if "maintenance" in content or "deprecated" in content:
                return "maintenance"
        return "active"
    except Exception as e:
        logger.warning("detect.py unexpected error: %s", e, exc_info=True)
        return "greenfield"


def detect_project_name(project_dir: Path) -> str:
    # package.json
    pkg = project_dir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            name = data.get("name", "")
            if name:
                return name
        except (json.JSONDecodeError, OSError):
            pass

    # pyproject.toml — [project] name = "..."
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(errors="replace")
        m = re.search(r"^\[project\].*?^name\s*=\s*\"([^\"]+)\"", content, re.MULTILINE | re.DOTALL)
        if m:
            return m.group(1)

    # Cargo.toml — [package] name = "..."
    cargo = project_dir / "Cargo.toml"
    if cargo.exists():
        content = cargo.read_text(errors="replace")
        m = re.search(r"^\[package\].*?^name\s*=\s*\"([^\"]+)\"", content, re.MULTILINE | re.DOTALL)
        if m:
            return m.group(1)

    return project_dir.resolve().name


def run(project_dir: Path, output_path: Path | None = None) -> None:
    stack = detect_stack(project_dir)
    agents = detect_agents()
    repo = detect_repo(project_dir)
    ci = detect_ci(project_dir)
    team_size = detect_team_size(project_dir)
    harness = detect_harness(project_dir)
    status = detect_status(project_dir)
    name = detect_project_name(project_dir)
    already_initialized = (project_dir / ".superharness").is_dir()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _list(items: list[str]) -> str:
        if not items:
            return "  []"
        return "\n".join(f"  - {i}" for i in items)

    yaml_output = (
        f"# Detected by superharness engine/detect.py\n"
        f"# {now}\n"
        f'detected_at: "{now}"\n'
        f'project_name: "{name}"\n'
        f'project_dir: "{Path(project_dir).as_posix()}"\n'
        f"already_initialized: {str(already_initialized).lower()}\n"
        f'stack: "{"/".join(stack)}"\n'
        f"agents_available:\n{_list(agents)}\n"
        f"repo: {repo}\n"
        f"ci: {ci}\n"
        f"team_size: {team_size}\n"
        f"status: {status}\n"
        f"existing_harness:\n{_list(harness)}\n"
    )

    if output_path:
        output_path.write_text(yaml_output)
        print(f"Wrote: {output_path}", file=sys.stderr)
    else:
        print(yaml_output, end="")


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(
        prog="detect",
        description="Environment detection for superharness agent-install.",
    )
    p.add_argument("-p", "--project", default=os.getcwd(), help="Project directory (default: cwd)")
    p.add_argument("-o", "--output", default=None, help="Write YAML to file instead of stdout")
    opts = p.parse_args(argv)

    project_dir = Path(opts.project).resolve()
    if not project_dir.is_dir():
        raise UsageError(f"Not a directory: {project_dir}", exit_code=1)

    output_path = Path(opts.output) if opts.output else None
    run(project_dir, output_path)


if __name__ == "__main__":
    try:
        main()
    except SuperharnessError as e:
        handle_cli_error(e)
