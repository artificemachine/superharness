from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tests.helpers import run_bash


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    contract = harness / "contract.yaml"
    contract.write_text(
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
    return project


def _write_inbox(project: Path, lines: list[str]) -> Path:
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text("\n".join(lines) + "\n")
    return inbox


def _fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("codex", "claude"):
        f = bin_dir / name
        f.write_text(f"#!/bin/bash\necho fake-{name}\n")
        f.chmod(0o755)
    return bin_dir


# Skip if running as root (Unix only) — chmod won't restrict root. Skip entirely on Windows.
_skip_if_root = pytest.mark.skipif(
    not hasattr(os, "getuid") or os.getuid() == 0,
    reason="root bypasses permissions or Windows does not support Unix chmod",
)


# ── Read-only contract ──


@_skip_if_root
def test_enqueue_fails_on_readonly_harness_dir(repo_root, tmp_path) -> None:
    """Enqueue must fail when .superharness/ directory is not writable (atomic write blocked)."""
    project = _setup_project(tmp_path)
    _write_inbox(
        project,
        [
            "# inbox",
            "- id: existing",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 0",
            "  max_retries: 3",
        ],
    )
    harness = project / ".superharness"
    harness.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read + execute only, no write

    script = repo_root / "scripts" / "inbox-enqueue.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"],
    )

    harness.chmod(stat.S_IRWXU)

    assert result.returncode != 0, "enqueue should fail on read-only .superharness dir"


@_skip_if_root
def test_dispatch_fails_on_readonly_harness_dir(repo_root, tmp_path) -> None:
    """Dispatch must fail when .superharness/ directory is not writable (atomic write blocked)."""
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path)
    _write_inbox(
        project,
        [
            "# inbox",
            "- id: item-1",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 0",
            "  max_retries: 3",
        ],
    )
    harness = project / ".superharness"
    harness.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read + execute only, no write

    script = repo_root / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--print-only"],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )

    harness.chmod(stat.S_IRWXU)

    # Dispatch treats lock-creation failure as "another dispatcher active" and skips gracefully.
    assert "skipping" in result.stdout.lower() or result.returncode != 0, \
        "dispatch should either skip or fail on read-only .superharness dir"


@_skip_if_root
def test_delegate_fails_on_readonly_contract(repo_root, tmp_path) -> None:
    """Delegate --print-only reads the contract; this tests a fully unreadable contract."""
    project = _setup_project(tmp_path)
    contract = project / ".superharness" / "contract.yaml"
    contract.chmod(0)  # no access

    script = repo_root / "scripts" / "delegate.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    contract.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert result.returncode != 0, "delegate should fail on unreadable contract"


@_skip_if_root
def test_contract_hygiene_fails_on_unreadable_contract(repo_root, tmp_path) -> None:
    """Contract hygiene check must fail if contract.yaml is unreadable."""
    project = _setup_project(tmp_path)
    contract = project / ".superharness" / "contract.yaml"
    contract.chmod(0)

    script = repo_root / "scripts" / "check-contract-hygiene.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project)],
    )

    contract.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert result.returncode != 0, "hygiene should fail on unreadable contract"


@_skip_if_root
def test_doctor_reports_missing_superharness_directory(repo_root, tmp_path) -> None:
    """Doctor should fail when .superharness does not exist (permission-adjacent: missing dir)."""
    project = tmp_path / "empty-proj"
    project.mkdir()

    script = repo_root / "scripts" / "doctor.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project)],
    )

    assert result.returncode != 0


@_skip_if_root
def test_watch_fails_on_readonly_project_dir(repo_root, tmp_path) -> None:
    """Watch must fail when the project directory's .superharness is not writable."""
    project = _setup_project(tmp_path)
    _write_inbox(project, ["# empty inbox"])
    harness = project / ".superharness"
    harness.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read + execute only

    script = repo_root / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--once"],
    )

    harness.chmod(stat.S_IRWXU)

    # Watch should fail or report an error when it can't create lock dir
    assert result.returncode != 0 or "permission" in result.stderr.lower() or "error" in result.stderr.lower(), \
        f"watch should fail on read-only .superharness (rc={result.returncode})"
