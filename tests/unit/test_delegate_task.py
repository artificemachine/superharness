from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash
import sys
import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

def _setup_project(tmp_path: Path, owner: str = "codex-cli") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: mcp-docs",
                f"    owner: {owner}",
                "    status: plan_approved",
                f"    project_path: '{project.as_posix()}'" ,
            ]
        )
        + "\n"
    )
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)
    return project


def _fake_bin(tmp_path: Path, *names: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        binary = bin_dir / name
        binary.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
        binary.chmod(0o755)
    return bin_dir


# ── Argument validation ──


def test_delegate_task_requires_task_id(repo_root, tmp_path) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(tmp_path)])
    assert result.returncode == 2
    assert "task-id is required" in result.stderr


def test_delegate_task_rejects_unknown_option(repo_root, tmp_path) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(script, cwd=repo_root, args=["--bogus"])
    assert result.returncode == 2
    assert "Unknown option" in result.stderr


def test_delegate_task_rejects_extra_positional(repo_root, tmp_path) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(script, cwd=repo_root, args=["task1", "task2"])
    assert result.returncode == 2
    assert "Unexpected argument" in result.stderr


# ── Missing files ──


def test_delegate_task_fails_missing_project_dir(repo_root, tmp_path) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["mcp-docs", "--project", str(tmp_path / "nonexistent")],
    )
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_delegate_task_fails_missing_contract(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["mcp-docs", "--project", str(project)],
    )
    assert result.returncode == 1
    assert "Missing contract file" in result.stderr


def test_delegate_task_fails_unknown_task_id(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["nonexistent-task", "--project", str(project)],
    )
    assert result.returncode == 1
    assert "not found in contract" in result.stderr


def test_delegate_task_fails_unsupported_owner(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, owner="human")
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["mcp-docs", "--project", str(project)],
    )
    assert result.returncode == 1
    assert "unsupported" in result.stderr


# ── Functional: print-only delegates to delegate.sh ──


def test_delegate_task_print_only_succeeds(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["mcp-docs", "--project", str(project), "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "Generated prompt:" in result.stdout
    assert "mcp-docs" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_task_non_interactive_passes_flag(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "codex")
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["mcp-docs", "--project", str(project), "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "--skip-git-repo-check" in result.stdout


def test_delegate_task_help_exits_zero(repo_root, tmp_path) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(script, cwd=repo_root, args=["--help"])
    assert result.returncode == 0
    assert "delegate-task.sh" in result.stdout


def test_delegate_task_claude_owner_routes_correctly(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, owner="claude-code")
    script = repo_root / "src" / "superharness" / "scripts" / "delegate-task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["mcp-docs", "--project", str(project), "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "Generated prompt:" in result.stdout


# ── requires: gate — capability preflight blocks dispatch end-to-end ──


def _set_task_requires(project: Path, task_id: str, requires: dict) -> None:
    """Inject a `requires:` block into the task's extras_json (SQLite source of truth)."""
    import json as _j
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = conn.execute("SELECT extras_json FROM tasks WHERE id = ?", (task_id,)).fetchone()
        extras = _j.loads(row[0]) if row and row[0] else {}
        extras["requires"] = requires
        conn.execute("UPDATE tasks SET extras_json = ? WHERE id = ?", (_j.dumps(extras), task_id))
        conn.commit()
    finally:
        conn.close()


def test_delegate_blocks_dispatch_on_unmet_requires(tmp_path, monkeypatch) -> None:
    """End-to-end: a task whose `requires:` block is unsatisfied must NOT dispatch.

    The preflight gate returns before any model resolution, orchestration, or
    launch, so this runs fully offline. `_launch_agent` is patched to raise, so if
    the gate ever fails to block we get a clear failure instead of a spawned agent.
    """
    monkeypatch.delenv("SHUX_E2E_UNSET_REQ_VAR_4242", raising=False)
    project = _setup_project(tmp_path, owner="claude-code")
    _set_task_requires(
        project, "mcp-docs",
        {"fail_mode": "block", "env": [{"name": "SHUX_E2E_UNSET_REQ_VAR_4242", "reason": "needed"}]},
    )

    from superharness.commands import delegate as deleg

    def _boom(*a, **k):
        raise AssertionError("reached launch — requires gate did NOT block dispatch")

    monkeypatch.setattr(deleg, "_launch_agent", _boom)

    rc = deleg.delegate(
        project_dir=str(project),
        target="claude-code",
        task_id="mcp-docs",
        print_only=False,
        non_interactive=False,
        codex_bypass=False,
        no_auto_model=True,
        no_orchestrate=True,
        skip_preflight=False,
        via_sdk=False,
    )
    assert rc == 1


def test_delegate_proceeds_when_no_requires_block(tmp_path, monkeypatch) -> None:
    """Control: a task with no `requires:` block is not blocked by the requires gate.

    We stop at the launch boundary (patched) so the test stays offline — reaching
    `_launch_agent` proves the preflight requires gate did not block.
    """
    project = _setup_project(tmp_path, owner="claude-code")

    from superharness.commands import delegate as deleg

    class _Reached(Exception):
        pass

    def _reached(*a, **k):
        raise _Reached()

    monkeypatch.setattr(deleg, "_launch_agent", _reached)

    with pytest.raises(_Reached):
        deleg.delegate(
            project_dir=str(project),
            target="claude-code",
            task_id="mcp-docs",
            print_only=False,
            non_interactive=False,
            codex_bypass=False,
            no_auto_model=True,
            no_orchestrate=True,
            skip_preflight=False,
            via_sdk=False,
        )
