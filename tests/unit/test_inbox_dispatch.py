from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import run_bash, REPO_ROOT
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_normalize(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.inbox_normalize"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _write_contract(project: Path, *, status: str = "plan_approved") -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "handoffs").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: mcp-docs",
                "    owner: codex-cli",
                f"    status: {status}",
                f"    project_path: '{project.as_posix()}'" ,
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
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--print-only"],
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "SUPERHARNESS_PYTHON": sys.executable,
            "PYTHONPATH": str(repo_root / "src"),
        },
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
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
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


def test_dispatch_allows_review_requested_items_for_review_launch(repo_root, tmp_path) -> None:
    project = tmp_path / "proj_review"
    project.mkdir()
    _write_contract(project, status="review_requested")
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed",
            "",
            "- id: review-item",
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
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--print-only"],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 0, result.stderr
    assert "review-item -> launched" in result.stdout


def test_normalize_archives_only_dropped_rows(repo_root, tmp_path) -> None:
    project = tmp_path / "proj3"
    project.mkdir()
    _write_contract(project, status="done")
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

    result = _run_normalize(["--project", str(project), "--archive", "--drop-status", "prepared"])
    assert result.returncode == 0, result.stderr

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: keep-row" in inbox_text
    assert "id: drop-row" not in inbox_text

    archive_text = (project / ".superharness" / "inbox.archive.yaml").read_text()
    assert "id: drop-row" in archive_text
    assert "id: keep-row" not in archive_text


def test_normalize_re_enqueues_failed_dispatch_ready_tasks(repo_root, tmp_path) -> None:
    project = tmp_path / "proj_reenqueue"
    project.mkdir()
    _write_contract(project, status="plan_approved")
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: failed-but-ready",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: failed",
            "  priority: 2",
            "  retry_count: 2",
            "  max_retries: 3",
            "  failed_at: 2026-04-05T10:00:00Z",
        ],
    )

    result = _run_normalize(["--project", str(project), "--drop-status", "failed"])
    assert result.returncode == 0, result.stderr
    assert "re-enqueued" in result.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: failed-but-ready" in inbox_text
    assert "status: pending" in inbox_text
    assert "retry_count: 0" in inbox_text
    assert "failed_at" not in inbox_text


def test_normalize_drops_rows_by_id_prefix(repo_root, tmp_path) -> None:
    project = tmp_path / "proj3-prefix"
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
            "- id: 20260312T010101Z-prefixed",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {project}",
            "  status: pending",
            "  priority: 2",
            "  retry_count: 0",
            "  max_retries: 3",
        ],
    )

    result = _run_normalize(["--project", str(project), "--drop-id-prefix", "20260312T"])
    assert result.returncode == 0, result.stderr

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: keep-row" in inbox_text
    assert "id: 20260312T010101Z-prefixed" not in inbox_text


def test_dispatch_fails_on_malformed_inbox_yaml(repo_root, tmp_path) -> None:
    project = tmp_path / "proj4"
    project.mkdir()
    _write_contract(project)
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text(":\n  - invalid\n")

    bin_dir = _fake_bin(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
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
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
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


def test_dispatch_non_interactive_codex_pauses_when_worktree_dirty(repo_root, tmp_path) -> None:
    project = tmp_path / "proj_dirty"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale|paused",
            "",
            "- id: dirty-item",
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

    run_cmd = subprocess.run
    run_cmd(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=project, check=True, capture_output=True, text=True)
    run_cmd(["git", "config", "user.name", "tester"], cwd=project, check=True, capture_output=True, text=True)
    run_cmd(["git", "config", "core.hooksPath", "/dev/null"], cwd=project, check=True, capture_output=True, text=True)
    tracked = project / "tracked.txt"
    tracked.write_text("base\n")
    run_cmd(["git", "add", "tracked.txt"], cwd=project, check=True, capture_output=True, text=True)
    run_cmd(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True, text=True)
    tracked.write_text("changed\n")

    bin_dir = _fake_bin(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
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
    assert "dirty-item -> paused" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: dirty-item" in inbox_text
    assert "  status: paused" in inbox_text
    assert "  pause_reason: dirty_worktree_requires_user_confirmation" in inbox_text
    assert "  retry_count: 0" in inbox_text


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
                "  perl -0pi -e 's/(id:\\s*mcp-docs\\s*\\n(?:[^\\n]*\\n)*?\\s*status:\\s*)(?:todo|plan_approved|in_progress|running|failed|done)/${1}done/s' \"$proj/.superharness/contract.yaml\"",
                "fi",
                "echo fake-codex",
            ]
        )
        + "\n"
    )
    codex_path.chmod(0o755)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
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


def test_dispatch_non_interactive_pauses_when_contract_waits_user_approval(repo_root, tmp_path) -> None:
    project = tmp_path / "proj6b"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale|paused",
            "",
            "- id: reconcile-approval-item",
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
                "  perl -0pi -e 's/(id:\\s*mcp-docs\\s*\\n(?:[^\\n]*\\n)*?\\s*status:\\s*)(?:todo|plan_approved|in_progress|running|failed|done|pending_user_approval)/${1}pending_user_approval/s' \"$proj/.superharness/contract.yaml\"",
                "fi",
                "echo fake-codex",
            ]
        )
        + "\n"
    )
    codex_path.chmod(0o755)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
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
    assert "paused (awaiting_user_approval)" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: reconcile-approval-item" in inbox_text
    assert "  status: paused" in inbox_text
    assert "  pause_reason: awaiting_user_approval" in inbox_text
    assert "  paused_at:" in inbox_text


def test_dispatch_worker_mode_uses_dispatch_project_for_execution(repo_root, tmp_path) -> None:
    source = tmp_path / "source_proj"
    source.mkdir()
    _write_contract(source)
    _write_inbox(
        source,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale|paused",
            "",
            "- id: worker-mode-item",
            "  to: codex-cli",
            "  task: mcp-docs",
            f"  project: {source}",
            "  status: pending",
            "  priority: 1",
            "  retry_count: 0",
            "  max_retries: 3",
            "  created_at: 2026-03-08T18:00:00Z",
        ],
    )
    worker = tmp_path / "worker_proj"
    worker.mkdir()
    (worker / ".superharness").symlink_to(source / ".superharness", target_is_directory=True)

    bin_dir = _fake_bin(tmp_path)
    codex_path = bin_dir / "codex"
    capture_path = tmp_path / "captured_exec_project.txt"
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
                f'printf \"%s\" \"$proj\" > "{capture_path}"',
                'if [ -n \"$proj\" ] && [ -f \"$proj/.superharness/contract.yaml\" ]; then',
                "  perl -0pi -e 's/(id:\\s*mcp-docs\\s*\\n(?:[^\\n]*\\n)*?\\s*status:\\s*)(?:todo|plan_approved|in_progress|running|failed|done)/${1}done/s' \"$proj/.superharness/contract.yaml\"",
                "fi",
                "echo fake-codex",
            ]
        )
        + "\n"
    )
    codex_path.chmod(0o755)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(worker), "--to", "codex-cli", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 0
    assert capture_path.read_text() == str(worker)
    inbox_text = (source / ".superharness" / "inbox.yaml").read_text()
    assert "id: worker-mode-item" in inbox_text
    assert "  status: done" in inbox_text


def test_dispatch_handles_pipe_character_in_item_id(repo_root, tmp_path) -> None:
    project = tmp_path / "proj7"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: id|with|pipe",
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
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--print-only"],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 0, result.stderr
    assert "id|with|pipe -> launched" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: id|with|pipe" in inbox_text
    assert "  status: launched" in inbox_text


def test_dispatch_marks_failed_after_transient_lock_contention(repo_root, tmp_path) -> None:
    project = tmp_path / "proj8"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: lock-race-item",
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
    codex_path.write_text("#!/bin/bash\nsleep 0.2\nexit 1\n")
    codex_path.chmod(0o755)

    inbox_path = project / ".superharness" / "inbox.yaml"
    lock_dir = project / ".superharness" / "inbox.yaml.lock.d"
    locker = tmp_path / "locker.sh"
    locker.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                f'inbox="{inbox_path}"',
                f'lock_dir="{lock_dir}"',
                "while ! grep -q 'status: launched' \"$inbox\"; do sleep 0.02; done",
                "mkdir \"$lock_dir\"",
                "sleep 0.5",
                "rmdir \"$lock_dir\"",
            ]
        )
        + "\n"
    )
    locker.chmod(0o755)
    locker_proc = subprocess.Popen(["bash", str(locker)], cwd=repo_root)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    try:
        result = run_bash(
            script,
            cwd=repo_root,
            args=["--project", str(project), "--to", "codex-cli", "--non-interactive"],
            env={
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
            },
        )
    finally:
        locker_proc.wait(timeout=5)

    assert result.returncode == 1
    assert "lock-race-item -> failed" in result.stdout
    inbox_text = inbox_path.read_text()
    assert "id: lock-race-item" in inbox_text
    assert "  status: failed" in inbox_text


def test_dispatch_launcher_timeout_kills_hung_process(repo_root, tmp_path) -> None:
    project = tmp_path / "proj_timeout"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: timeout-item",
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
    # Create a launcher that sleeps forever (simulates a hung process)
    codex_path = bin_dir / "codex"
    codex_path.write_text("#!/bin/bash\nsleep 300\n")
    codex_path.chmod(0o755)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "codex-cli",
            "--non-interactive",
            "--launcher-timeout", "2",
        ],
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "timed out after 2s" in result.stderr
    assert "timeout-item -> failed" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "  status: failed" in inbox_text
    assert "  failed_at:" in inbox_text


def test_dispatch_launcher_timeout_zero_means_no_timeout(repo_root, tmp_path) -> None:
    project = tmp_path / "proj_no_timeout"
    project.mkdir()
    _write_contract(project)
    _write_inbox(
        project,
        [
            "# Delegation inbox",
            "# status: pending|launched|running|done|failed|stale",
            "",
            "- id: no-timeout-item",
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
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "codex-cli",
            "--print-only",
            "--launcher-timeout", "0",
        ],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 0, result.stderr
    assert "no-timeout-item -> launched" in result.stdout


def test_dispatch_rejects_invalid_launcher_timeout(repo_root, tmp_path) -> None:
    project = tmp_path / "proj_bad_timeout"
    project.mkdir()
    (project / ".superharness").mkdir(parents=True)
    (project / ".superharness" / "inbox.yaml").write_text("- id: x\n  status: pending\n")

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-dispatch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--launcher-timeout", "abc"],
    )

    assert result.returncode == 2
    assert "non-negative integer" in result.stderr


# ---------------------------------------------------------------------------
# _MkdirLock PID-based orphan detection tests
# ---------------------------------------------------------------------------

def test_dispatch_lock_writes_owner_pid(tmp_path) -> None:
    from superharness.commands.inbox_dispatch import _MkdirLock

    lock_path = str(tmp_path / "test.lock.d")
    lock = _MkdirLock(lock_path)
    assert lock.acquire() is True

    pid_file = Path(lock_path) / "owner.pid"
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()
    lock.release()
    assert not Path(lock_path).exists()


def test_dispatch_lock_breaks_dead_pid(tmp_path) -> None:
    from superharness.commands.inbox_dispatch import _MkdirLock

    lock_path = tmp_path / "test.lock.d"
    lock_path.mkdir()
    (lock_path / "owner.pid").write_text("999999\n")

    lock = _MkdirLock(str(lock_path))
    assert lock.acquire() is True
    assert int((lock_path / "owner.pid").read_text().strip()) == os.getpid()
    lock.release()


def test_dispatch_lock_respects_live_pid(tmp_path) -> None:
    from superharness.commands.inbox_dispatch import _MkdirLock

    lock_path = tmp_path / "test.lock.d"
    lock_path.mkdir()
    (lock_path / "owner.pid").write_text(f"{os.getpid()}\n")

    lock = _MkdirLock(str(lock_path))
    assert lock.acquire() is False

    # cleanup
    (lock_path / "owner.pid").unlink()
    lock_path.rmdir()


def test_dispatch_lock_breaks_stale_pidless(tmp_path) -> None:
    import time as _time
    from superharness.commands.inbox_dispatch import _MkdirLock

    lock_path = tmp_path / "test.lock.d"
    lock_path.mkdir()
    stale_time = _time.time() - 600
    os.utime(str(lock_path), (stale_time, stale_time))

    lock = _MkdirLock(str(lock_path), stale_seconds=300)
    assert lock.acquire() is True
    lock.release()
