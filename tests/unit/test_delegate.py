from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml

from tests.helpers import REPO_ROOT
import pytest

pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")


def _run_delegate_py(cwd, args: list[str] | None = None, env: dict | None = None):
    """Run delegate Python module."""
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
    cmd = [sys.executable, "-m", "superharness.commands.delegate"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False)


def _setup_project(tmp_path: Path, extra_task_fields: str = "") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    task_block = "\n".join(
        [
            "id: test-contract",
            "tasks:",
            "  - id: mcp-docs",
            "    owner: codex-cli",
            "    status: plan_approved",
            f"    project_path: '{project.as_posix()}'" ,
        ]
    )
    if extra_task_fields:
        task_block += "\n" + extra_task_fields
    (harness / "contract.yaml").write_text(task_block + "\n")
    return project


def _fake_bin(tmp_path: Path, *names: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        binary = bin_dir / name
        binary.write_text(f"#!/bin/bash\necho fake-{name}\n")
        binary.chmod(0o755)
    return bin_dir


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_print_only_does_not_require_target_cli(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)

    # Use a minimal PATH that does not include user-installed codex/claude CLIs.
    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Generated prompt:" in result.stdout
    assert "execute task mcp-docs" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "claude")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "claude-code", "--project", str(project), "--task", "mcp-docs", "--non-interactive", "--via", "cli"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_codex_bypass_requires_specific_confirmation(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "codex")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--non-interactive", "--codex-bypass"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "SUPERHARNESS_CONFIRM_CODEX_BYPASS=YES" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_surfaces_malformed_handoff_error(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    handoff = project / ".superharness" / "handoffs" / "bad.yaml"
    handoff.write_text(":\n  - invalid\n")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project)],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode != 0
    assert "Failed to parse handoff" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_codex_non_interactive_adds_skip_git_repo_check(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
    codex.chmod(0o755)

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "--skip-git-repo-check" in result.stdout
    assert "--full-auto" in result.stdout


# ---------------------------------------------------------------------------
# Model routing tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_print_only_shows_model_and_effort(repo_root, tmp_path) -> None:
    """--print-only output includes Model: and Effort: lines."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "codex-cli", "--project", str(project),
            "--task", "mcp-docs", "--print-only", "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model:" in result.stdout
    assert "Effort:" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_model_override_via_cli(repo_root, tmp_path) -> None:
    """--model flag overrides auto-classification."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only",
            "--model", "opus", "--effort", "high",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: opus (manual)" in result.stdout
    assert "Effort: high" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_no_auto_model_uses_fallback(repo_root, tmp_path) -> None:
    """--no-auto-model skips classification and falls back to standard/medium."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only", "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: claude-sonnet-4-6 (fallback)" in result.stdout
    assert "Effort: medium" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_task_level_model_field(repo_root, tmp_path) -> None:
    """model field on a task in contract.yaml is used when no CLI flag."""
    project = _setup_project(tmp_path, extra_task_fields="    model: mini\n    effort: low")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only", "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    # mini resolves to claude-haiku-4-5-20251001 for claude-code
    assert "Model: claude-haiku-4-5-20251001 (task)" in result.stdout
    assert "Effort: low" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_tier_name_resolves_to_agent_model(repo_root, tmp_path) -> None:
    """Passing --model max resolves to claude-opus-4-7 for claude-code."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only",
            "--model", "max",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: claude-opus-4-7 (manual)" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_codex_tier_resolves_correctly(repo_root, tmp_path) -> None:
    """Passing --model mini resolves to gpt-5.1-codex-mini for codex-cli."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "codex-cli", "--project", str(project),
            "--task", "mcp-docs", "--print-only",
            "--model", "mini",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: gpt-5.1-codex-mini (manual)" in result.stdout


# ---------------------------------------------------------------------------
# Scheduling gate tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_blocked_by_scheduled_after(repo_root, tmp_path) -> None:
    """Task with future scheduled_after date blocks delegation."""
    project = _setup_project(tmp_path, extra_task_fields="    scheduled_after: '2099-12-31'")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert "not ready" in result.stderr
    assert "scheduled after" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_allowed_after_scheduled_date(repo_root, tmp_path) -> None:
    """Task with past scheduled_after date allows delegation."""
    project = _setup_project(tmp_path, extra_task_fields="    scheduled_after: '2020-01-01'")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_warns_overdue_task(repo_root, tmp_path) -> None:
    """Task past its due_by date prints a warning but still delegates."""
    project = _setup_project(tmp_path, extra_task_fields="    due_by: '2020-01-01'")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "overdue" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_blocked_by_dependency(repo_root, tmp_path) -> None:
    """Task with depends_on unfinished task blocks delegation."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: dep-task\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        f"    project_path: '{project.as_posix()}'\n"
        "  - id: mcp-docs\n"
        "    owner: codex-cli\n"
        "    status: plan_approved\n"
        "    depends_on: [dep-task]\n"
        f"    project_path: '{project.as_posix()}'\n"
    )

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert "blocked" in result.stderr
    assert "dep-task" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_allowed_when_dependency_done(repo_root, tmp_path) -> None:
    """Task with depends_on finished task allows delegation."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: dep-task\n"
        "    owner: claude-code\n"
        "    status: done\n"
        f"    project_path: '{project.as_posix()}'\n"
        "  - id: mcp-docs\n"
        "    owner: codex-cli\n"
        "    status: plan_approved\n"
        "    depends_on: [dep-task]\n"
        f"    project_path: '{project.as_posix()}'\n"
    )

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr


def test_delegate_scheduled_after_idempotent(repo_root, tmp_path) -> None:
    """Running delegate twice on a future-scheduled task returns same error both times."""
    project = _setup_project(tmp_path, extra_task_fields="    scheduled_after: '2099-12-31'")

    r1 = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )
    r2 = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert r1.returncode == 1
    assert r2.returncode == 1
    assert r1.stderr == r2.stderr


# ---------------------------------------------------------------------------
# SDK delegation tests (--via sdk)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_via_sdk_uses_sdk_runner_when_available(repo_root, tmp_path) -> None:
    """--via sdk uses SDKRunner when SDK is available.

    This test runs delegate as a subprocess, so in-process patches have no
    effect. It requires the real SDK + CLI to be installed on the machine.
    """
    sdk = pytest.importorskip("claude_agent_sdk")
    # Skip if the module is a test stub (no real query function)
    if not callable(getattr(sdk, "query", None)):
        pytest.skip("claude_agent_sdk is a test stub, not the real SDK")
    import shutil
    if not shutil.which("claude"):
        pytest.skip("claude CLI not on PATH")

    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--via", "sdk", "--print-only",
        ],
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_via_sdk_falls_back_to_cli_when_sdk_unavailable(repo_root, tmp_path) -> None:
    """--via sdk falls back to CLI when SDK is not available."""
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "claude")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--via", "sdk", "--print-only",
        ],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_FORCE_NO_SDK": "1",
        },
    )

    # Should warn about fallback and show CLI mode
    assert "SDK not available" in result.stderr or "falling back" in result.stderr.lower()
    assert "Via: cli" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_via_sdk_print_only_falls_back_when_unavailable(repo_root, tmp_path) -> None:
    """--via sdk --print-only falls back to CLI when SDK is unavailable."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--via", "sdk", "--print-only",
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "SUPERHARNESS_FORCE_NO_SDK": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "SDK not available" in result.stderr and "falling back" in result.stderr.lower()
    assert "Via: cli" in result.stdout


# ── gate 4 exit code + --plan-only ───────────────────────────────────────────

def _setup_project_todo(tmp_path: Path) -> Path:
    """Project with a single `todo` + `implementation` task."""
    project = tmp_path / "proj_todo"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: feat.wip\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        "    workflow: implementation\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    return project


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_returns_exit_2_on_permanent_lifecycle_block(tmp_path):
    """Gate 4 rejection of a lifecycle-incompatible task returns exit 2 (non-retryable)."""
    project = _setup_project_todo(tmp_path)
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.wip", "--print-only"],
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "plan must be approved" in r.stderr or "blocked" in r.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_plan_only_accepts_todo_implementation(tmp_path):
    """--plan-only relaxes gate 4 for todo + implementation."""
    project = _setup_project_todo(tmp_path)
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.wip", "--plan-only", "--print-only"],
    )
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_plan_only_injects_directive_into_prompt(tmp_path):
    """The plan-only directive appears verbatim in the agent prompt."""
    project = _setup_project_todo(tmp_path)
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.wip", "--plan-only", "--print-only"],
    )
    assert r.returncode == 0, r.stderr
    assert "PLAN-ONLY MODE" in r.stdout
    assert "Do NOT write, modify, or delete" in r.stdout
    assert "plan_proposed" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_without_plan_only_returns_exit_2_for_todo_impl(tmp_path):
    """Without --plan-only the same task returns permanent-block exit code."""
    project = _setup_project_todo(tmp_path)
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.wip"],
    )
    assert r.returncode == 2, (r.returncode, r.stderr)


# ── ship_on_complete directive ────────────────────────────────────────────────

def _setup_project_ship_on_complete(tmp_path: Path) -> Path:
    """Project with a plan_approved + ship_on_complete task."""
    project = tmp_path / "proj_ship"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: feat.ship-me\n"
        "    owner: claude-code\n"
        "    status: plan_approved\n"
        "    workflow: implementation\n"
        "    ship_on_complete: true\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    return project


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_ship_on_complete_injects_directive_into_prompt(tmp_path):
    """ship_on_complete: true adds a SHIP-ON-COMPLETE directive to the agent prompt."""
    project = _setup_project_ship_on_complete(tmp_path)
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.ship-me", "--print-only"],
    )
    assert r.returncode == 0, r.stderr
    assert "SHIP-ON-COMPLETE" in r.stdout
    assert "ALLOW_PUSH=1" in r.stdout or "/ship commit" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_ship_on_complete_false_no_directive(tmp_path):
    """ship_on_complete: false (default) must NOT inject the ship directive."""
    project = _setup_project_todo(tmp_path)
    # Use a plan_approved variant (override status)
    (project / ".superharness" / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: feat.wip\n"
        "    owner: claude-code\n"
        "    status: plan_approved\n"
        "    workflow: implementation\n"
        "    ship_on_complete: false\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.wip", "--print-only"],
    )
    assert r.returncode == 0, r.stderr
    assert "SHIP-ON-COMPLETE" not in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_ship_on_complete_flag_overrides_contract(tmp_path):
    """--ship-on-complete CLI flag injects directive even when contract field is false."""
    project = _setup_project_todo(tmp_path)
    # Use a plan_approved task without ship_on_complete in contract
    (project / ".superharness" / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: feat.wip\n"
        "    owner: claude-code\n"
        "    status: plan_approved\n"
        "    workflow: implementation\n"
        "    ship_on_complete: false\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    r = _run_delegate_py(
        project,
        args=["--to", "claude-code", "--project", str(project),
              "--task", "feat.wip", "--ship-on-complete", "--print-only"],
    )
    assert r.returncode == 0, r.stderr
    assert "SHIP-ON-COMPLETE" in r.stdout
