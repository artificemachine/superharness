from __future__ import annotations

import os
from pathlib import Path

from tests.helpers import run_bash


def _write_contract(project: Path) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "handoffs").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: mcp-docs",
                "    owner: codex-cli",
                "    status: todo",
                f'    project_path: "{project}"',
            ]
        )
        + "\n"
    )


def _write_inbox(project: Path, lines: list[str]) -> None:
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text("\n".join(lines) + "\n")


def _fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "claude"):
        f = bin_dir / name
        f.write_text("#!/bin/bash\necho fake-" + name + "\n")
        f.chmod(0o755)
    return bin_dir


def test_dispatch_picks_highest_priority_and_sets_launched_in_print_only_mode(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed",
            "",
            "- id: low-priority",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 3",
            "  retry_count: 0",
            "  max_retries: 3",
            "  created_at: 2026-03-08T18:00:00Z",
            "",
            "- id: high-priority",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 0",
            "  max_retries: 3",
            "  created_at: 2026-03-08T18:00:01Z",
        ],
    )

    bin_dir = _fake_bin(tmp_path)
    script = repo_root / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--print-only"],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 0, result.stderr
    assert "high-priority -> launched" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: high-priority" in inbox_text
    assert "  status: launched" in inbox_text
    assert "  launched_at:" in inbox_text
    assert "  retry_count: 1" in inbox_text
    # Lower priority item remains pending.
    assert "id: low-priority" in inbox_text
    assert "  priority: 3" in inbox_text


def test_dispatch_marks_failed_when_retry_limit_reached(repo_root, tmp_path) -> None:
    project = tmp_path / "proj2"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed",
            "",
            "- id: exhausted-retries",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 3",
            "  max_retries: 3",
            "  created_at: 2026-03-08T18:00:00Z",
        ],
    )

    bin_dir = _fake_bin(tmp_path)
    script = repo_root / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli"],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 1
    assert "retry limit reached" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: exhausted-retries" in inbox_text
    assert "  status: failed" in inbox_text
    assert "  failed_at:" in inbox_text


def test_normalize_archives_only_dropped_rows(repo_root, tmp_path) -> None:
    project = tmp_path / "proj3"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: keep-row",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 2",
            "  retry_count: 0",
            "  max_retries: 3",
            "",
            "- id: drop-row",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: prepared",
            "  priority: 2",
            "  retry_count: 0",
            "  max_retries: 3",
        ],
    )

    script = repo_root / "scripts" / "inbox-normalize.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--archive", "--drop-status", "prepared"],
    )
    assert result.returncode == 0, result.stderr

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: keep-row" in inbox_text
    assert "id: drop-row" not in inbox_text

    archive_text = (project / ".superharness" / "inbox.archive.yaml").read_text()
    assert "id: drop-row" in archive_text
    assert "id: keep-row" not in archive_text


def test_dispatch_fails_on_malformed_inbox_yaml(repo_root, tmp_path) -> None:
    project = tmp_path / "proj4"
    project.mkdir()
    _write_contract(project)
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text(":\n  - invalid\n")

    bin_dir = _fake_bin(tmp_path)
    script = repo_root / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli"],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 1
    assert "Failed to read pending inbox item" in result.stderr


def test_dispatch_non_interactive_reconciles_stuck_launched_to_failed(repo_root, tmp_path) -> None:
    project = tmp_path / "proj5"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: reconcile-item",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 0",
            "  max_retries: 3",
            "  created_at: 2026-03-08T18:00:00Z",
        ],
    )

    bin_dir = _fake_bin(tmp_path)
    script = repo_root / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "non-interactive launch exited without done/failed" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: reconcile-item" in inbox_text
    assert "  status: failed" in inbox_text
    assert "  failed_at:" in inbox_text


def test_dispatch_non_interactive_reconciles_to_done_from_contract(repo_root, tmp_path) -> None:
    project = tmp_path / "proj6"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: reconcile-done-item",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 0",
            "  max_retries: 3",
            "  created_at: 2026-03-08T18:00:00Z",
        ],
    )

    bin_dir = _fake_bin(tmp_path)
    codex_path = bin_dir / "codex"
    codex_path.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                'proj=""',
                "while [ $# -gt 0 ]; do",
                '  if [ \"$1\" = \"-C\" ] && [ $# -ge 2 ]; then',
                '    proj=\"$2\"',
                "    shift 2",
                "    continue",
                "  fi",
                "  shift",
                "done",
                'if [ -n \"$proj\" ] && [ -f \"$proj/.superharness/contract.yaml\" ]; then',
                "  perl -0pi -e 's/(id:\\s*mcp-docs\\s*\\n(?:[^\\n]*\\n)*?\\s*status:\\s*)(?:todo|in_progress|running|failed|done)/${1}done/s' \"$proj/.superharness/contract.yaml\"",
                "fi",
                "echo fake-codex",
            ]
        )
        + "\n"
    )
    codex_path.chmod(0o755)

    script = repo_root / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 0
    assert "reconciled from contract task status" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: reconcile-done-item" in inbox_text
    assert "  status: done" in inbox_text
    assert "  done_at:" in inbox_text
