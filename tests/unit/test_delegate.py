from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.helpers import REPO_ROOT


_REQUIRES_POSIX_FIXTURE = pytest.mark.skipif(
    os.name != "posix",
    reason="Pi delegate integration fixture uses a POSIX shebang executable",
)


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
    return subprocess.run(
        cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False
    )


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
            f"    project_path: '{project.as_posix()}'",
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


def test_delegate_shorthand_preserves_pi_owner(monkeypatch, tmp_path: Path) -> None:
    """A SQLite-owned Pi task reaches the Pi delegate lane in print-only mode."""
    from superharness import cli
    from superharness.engine.db import get_connection, init_db

    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at) VALUES (?, ?, ?, ?, ?)",
        ("pi-task", "Pi task", "pi", "plan_approved", "2026-08-26T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    received: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        cli, "_run_module", lambda module, args: received.append((module, args))
    )

    result = CliRunner().invoke(
        cli.main, ["delegate", "pi-task", "--project", str(project), "--print-only"]
    )

    assert result.exit_code == 0, result.output
    assert received == [
        (
            "superharness.commands.delegate",
            ("--to", "pi", "--task", "pi-task", "--project", str(project), "--print-only"),
        )
    ]


@_REQUIRES_POSIX_FIXTURE
def test_delegate_shorthand_runs_fake_pi_with_target_correct_prompt(
    monkeypatch, tmp_path: Path
) -> None:
    """The real shorthand path reaches Pi through its fixture-only launcher."""
    isolated_home = tmp_path / "isolated-home"
    isolated_config = isolated_home / ".config"
    isolated_state = isolated_home / ".local" / "state"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated_config))
    monkeypatch.setenv("XDG_STATE_HOME", str(isolated_state))
    monkeypatch.setenv("SUPERHARNESS_TEST_OFFLINE", "1")

    from superharness.engine.db import get_connection, init_db

    project = tmp_path / "project"
    (project / ".superharness" / "handoffs").mkdir(parents=True)
    (project / ".git").mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, context, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "pi-task",
            "Pi task",
            "pi",
            "plan_approved",
            "fixture-only task context",
            "2026-08-26T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "pi-record.json"
    fake_pi = fake_bin / "pi"
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"with open({str(record)!r}, 'w', encoding='utf-8') as stream:\n"
        "    json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()}, stream)\n"
        "sys.stdout.write('{\"type\":\"session\",\"version\":3,\"id\":\"fixture-session\"}\\n')\n"
        "sys.stdout.write('{\"type\":\"message_end\",\"message\":{\"role\":\"assistant\",\"content\":[{\"type\":\"text\",\"text\":\"fixture result\"}],\"provider\":\"provider-a\",\"model\":\"model-a\",\"usage\":{},\"cost\":{},\"stopReason\":\"stop\"}}\\n')\n"
        "sys.stdout.write('{\"type\":\"agent_end\",\"messages\":[]}\\n')\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["HOME"] = str(isolated_home)
    env["XDG_CONFIG_HOME"] = str(isolated_config)
    env["XDG_STATE_HOME"] = str(isolated_state)
    env["SUPERHARNESS_TEST_OFFLINE"] = "1"
    env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import superharness.engine.osm as osm; "
            "osm.vault_search = lambda *_args, **_kwargs: []; "
            "from superharness.cli import main; main()",
            "delegate",
            "pi-task",
            "--project",
            str(project),
            "--non-interactive",
            "--no-auto-model",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert record.exists(), result.stdout
    invocation = json.loads(record.read_text(encoding="utf-8"))
    prompt = invocation["argv"][invocation["argv"].index("-p") + 1]
    assert invocation["cwd"] == str(project)
    assert invocation["argv"].count(prompt) == 1
    assert "you are pi" in prompt
    assert "codex-cli" not in prompt
    assert str(isolated_home) not in prompt


def test_pi_prompt_names_pi_not_codex() -> None:
    """The common prompt identifies Pi by its actual target name."""
    from superharness.commands.delegate import _build_task_execution_prompt

    prompt = _build_task_execution_prompt(
        target="pi",
        task_id="pi-task",
        contract_id="contract",
        latest_handoff=False,
        acceptance_criteria="",
        context_hint="",
        user_instructions="",
        auto_directive="",
    )

    assert "you are pi" in prompt
    assert "codex-cli" not in prompt


@pytest.mark.parametrize("target", ["claude-code", "codex-cli", "gemini-cli", "opencode"])
def test_task_prompt_names_each_existing_target(target: str) -> None:
    """Existing harnesses retain target-correct task prompt addressing."""
    from superharness.commands.delegate import _build_task_execution_prompt

    prompt = _build_task_execution_prompt(
        target=target,
        task_id="existing-task",
        contract_id="contract",
        latest_handoff=True,
        acceptance_criteria="",
        context_hint="",
        user_instructions="",
        auto_directive="",
    )

    assert f"addressed to {target}" in prompt


def test_inbox_watch_accepts_pi_target(monkeypatch, tmp_path: Path) -> None:
    """The watcher CLI accepts Pi without launching it."""
    from superharness.commands import inbox_watch

    watch_kwargs: dict[str, object] = {}
    monkeypatch.setattr(
        inbox_watch, "watch", lambda **kwargs: watch_kwargs.update(kwargs) or 0
    )

    monkeypatch.setattr(sys, "argv", ["inbox_watch", "--project", str(tmp_path), "--to", "pi"])
    with pytest.raises(SystemExit) as exc_info:
        inbox_watch.main()

    assert exc_info.value.code == 0
    assert watch_kwargs["target"] == "pi"


def test_inbox_watch_both_targets_known_harnesses_once() -> None:
    """The ordinary polling expansion follows the harness registry exactly once."""
    from superharness.commands.inbox_watch import _watcher_targets
    from superharness.harnesses import KNOWN_HARNESSES

    assert _watcher_targets("both") == KNOWN_HARNESSES
    assert _watcher_targets("both").count("pi") == 1


def test_inbox_watch_both_dispatches_each_known_harness_once(
    monkeypatch, tmp_path: Path
) -> None:
    """A watcher cycle dispatches the registry lanes once, without a launcher."""
    from superharness.commands import inbox_watch
    from superharness.engine import agent_memory, behavioral
    from superharness.harnesses import KNOWN_HARNESSES

    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    dispatched: list[str] = []

    # Counter-driven maintenance may write user-global behavioral and memory
    # files. Keep this fixture cycle out of those branches and stub the
    # imported call targets as a second fence against future control-flow edits.
    monkeypatch.setattr(inbox_watch, "_watcher_cycle_count", [1])
    monkeypatch.setattr(behavioral, "refresh_behavioral_profile", lambda *_: False)
    monkeypatch.setattr(behavioral, "evaluate_all_open_trials", lambda *_: 0)
    monkeypatch.setattr(agent_memory, "promote_all_project_memory", lambda *_: 0)

    for name in (
        "_self_diagnosis",
        "_rotate_launcher_logs_if_needed",
        "_sqlite_tick",
        "_poll_operator_commands",
        "_run_scripts_heartbeat",
        "_auto_advance_orphaned_rounds",
        "_auto_close_consensus_discussions",
        "_auto_archive_stale_tasks",
        "_reconcile_zombies",
        "_analyze_task_logs",
        "_run_transcript_tail_if_enabled",
        "_run_gc_if_due",
        "_auto_delete_stale_inbox",
        "_comprehensive_gc",
        "_cancel_undispatchable_agents",
    ):
        monkeypatch.setattr(inbox_watch, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(inbox_watch, "_find_scripts_dir", lambda: str(tmp_path))
    monkeypatch.setattr(inbox_watch, "_should_run", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        inbox_watch,
        "_run_dispatch_cmd",
        lambda **kwargs: dispatched.append(kwargs["target"]),
    )

    inbox_watch._run_scripts(
        str(project),
        target="both",
        print_only=True,
        non_interactive=True,
        codex_bypass=False,
        launcher_timeout=0,
        recover_timeout_minutes=20,
        recover_action="stale",
    )

    assert dispatched == KNOWN_HARNESSES
    assert dispatched.count("pi") == 1


def test_watcher_peer_fallback_health_and_retry_order_are_unchanged() -> None:
    """Pi does not perturb established peer, fallback, health, or retry policy."""
    from superharness.commands.inbox_watch import (
        _AGENT_CLI_BINARY,
        _AGENT_FALLBACK,
        _FALLBACK_ORDER,
        _PEER_AGENTS,
    )

    assert _PEER_AGENTS == {
        "claude-code": "gemini-cli",
        "gemini-cli": "codex-cli",
        "codex-cli": "claude-code",
    }
    assert _FALLBACK_ORDER == ["claude-code", "codex-cli", "gemini-cli", "opencode"]
    assert _AGENT_FALLBACK["codex-cli"] == ["claude-code", "gemini-cli", "opencode"]
    assert _AGENT_CLI_BINARY == {
        "claude-code": "claude",
        "codex-cli": "codex",
        "gemini-cli": "gemini",
    }


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_print_only_does_not_require_target_cli(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)

    # Use a minimal PATH that does not include user-installed codex/claude CLIs.
    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Generated prompt:" in result.stdout
    assert "execute task mcp-docs" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation(
    repo_root, tmp_path
) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "claude")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--non-interactive",
            "--via",
            "cli",
        ],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_codex_bypass_requires_specific_confirmation(
    repo_root, tmp_path
) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "codex")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--non-interactive",
            "--codex-bypass",
        ],
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
def test_delegate_codex_non_interactive_adds_skip_git_repo_check(
    repo_root, tmp_path
) -> None:
    project = _setup_project(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
    codex.chmod(0o755)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--non-interactive",
        ],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "--skip-git-repo-check" in result.stdout
    # Codex CLI deprecated --full-auto; replaced with --sandbox workspace-write.
    # See tests/unit/test_codex_launcher_modernize.py for the live pin.
    assert "--sandbox" in result.stdout
    assert "workspace-write" in result.stdout
    assert "--full-auto" not in result.stdout


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
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
            "--no-auto-model",
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
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
            "--model",
            "opus",
            "--effort",
            "high",
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
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
            "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: claude-sonnet-4-6 (fallback)" in result.stdout
    assert "Effort: medium" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_task_level_model_field(repo_root, tmp_path) -> None:
    """model field on a task in contract.yaml is used when no CLI flag."""
    project = _setup_project(
        tmp_path, extra_task_fields="    model: mini\n    effort: low"
    )

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
            "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    # mini resolves to claude-haiku-4-5-20251001 for claude-code
    assert "Model: claude-haiku-4-5-20251001 (task)" in result.stdout
    assert "Effort: low" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_tier_name_resolves_to_agent_model(repo_root, tmp_path) -> None:
    """Passing --model max resolves to claude-opus-4-8 for claude-code."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
            "--model",
            "max",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: claude-opus-4-8 (manual)" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_codex_tier_resolves_correctly(repo_root, tmp_path) -> None:
    """Passing --model mini resolves to gpt-5.1-codex-mini for codex-cli."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
            "--model",
            "mini",
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
    project = _setup_project(
        tmp_path, extra_task_fields="    scheduled_after: '2099-12-31'"
    )

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert "not ready" in result.stderr
    assert "scheduled after" in result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_allowed_after_scheduled_date(repo_root, tmp_path) -> None:
    """Task with past scheduled_after date allows delegation."""
    project = _setup_project(
        tmp_path, extra_task_fields="    scheduled_after: '2020-01-01'"
    )

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_warns_overdue_task(repo_root, tmp_path) -> None:
    """Task past its due_by date prints a warning but still delegates."""
    project = _setup_project(tmp_path, extra_task_fields="    due_by: '2020-01-01'")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
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
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
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
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr


def test_delegate_scheduled_after_idempotent(repo_root, tmp_path) -> None:
    """Running delegate twice on a future-scheduled task returns same error both times."""
    project = _setup_project(
        tmp_path, extra_task_fields="    scheduled_after: '2099-12-31'"
    )

    r1 = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )
    r2 = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--print-only",
        ],
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
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--via",
            "sdk",
            "--print-only",
        ],
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_via_sdk_falls_back_to_cli_when_sdk_unavailable(
    repo_root, tmp_path
) -> None:
    """--via sdk falls back to CLI when SDK is not available."""
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "claude")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--via",
            "sdk",
            "--print-only",
        ],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_FORCE_NO_SDK": "1",
        },
    )

    # Should warn about fallback and show CLI mode
    assert (
        "SDK not available" in result.stderr or "falling back" in result.stderr.lower()
    )
    assert "Via: cli" in result.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_via_sdk_print_only_falls_back_when_unavailable(
    repo_root, tmp_path
) -> None:
    """--via sdk --print-only falls back to CLI when SDK is unavailable."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "mcp-docs",
            "--via",
            "sdk",
            "--print-only",
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "SUPERHARNESS_FORCE_NO_SDK": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (
        "SDK not available" in result.stderr and "falling back" in result.stderr.lower()
    )
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
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "feat.wip",
            "--print-only",
        ],
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "plan must be approved" in r.stderr or "blocked" in r.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_plan_only_accepts_todo_implementation(tmp_path):
    """--plan-only relaxes gate 4 for todo + implementation."""
    project = _setup_project_todo(tmp_path)
    r = _run_delegate_py(
        project,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "feat.wip",
            "--plan-only",
            "--print-only",
        ],
    )
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_plan_only_injects_directive_into_prompt(tmp_path):
    """The plan-only directive appears verbatim in the agent prompt."""
    project = _setup_project_todo(tmp_path)
    r = _run_delegate_py(
        project,
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "feat.wip",
            "--plan-only",
            "--print-only",
        ],
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
        args=["--to", "claude-code", "--project", str(project), "--task", "feat.wip"],
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
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "feat.ship-me",
            "--print-only",
        ],
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
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "feat.wip",
            "--print-only",
        ],
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
        args=[
            "--to",
            "claude-code",
            "--project",
            str(project),
            "--task",
            "feat.wip",
            "--ship-on-complete",
            "--print-only",
        ],
    )
    assert r.returncode == 0, r.stderr
    assert "SHIP-ON-COMPLETE" in r.stdout


class TestSaveContextSnapshotTaskUsage:
    """_save_context_snapshot must persist SDK dispatch cost/tokens to task_usage
    (source='sdk') in addition to the existing YAML sidecar cache."""

    def _setup(self, tmp_path: Path) -> Path:
        project = tmp_path / "proj"
        project.mkdir()
        (project / ".superharness").mkdir()
        from superharness.engine.db import get_connection, init_db

        conn = get_connection(str(project))
        init_db(conn)
        conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) "
            "VALUES ('t1', 'T', 'in_progress', 1, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        conn.close()
        return project

    def test_save_context_snapshot_writes_task_usage_row(self, tmp_path: Path) -> None:
        from superharness.commands.delegate import _save_context_snapshot
        from superharness.engine import usage_dao
        from superharness.engine.db import get_connection, init_db

        project = self._setup(tmp_path)
        result = {
            "output": "done",
            "input_tokens": 200,
            "output_tokens": 80,
            "cost_usd": 0.02,
        }
        _save_context_snapshot(str(project), "t1", result, model="claude-sonnet-5")

        conn = get_connection(str(project))
        init_db(conn)
        rows = usage_dao.list_for_task(conn, "t1")
        conn.close()

        assert len(rows) == 1
        assert rows[0].source == "sdk"
        assert rows[0].agent == "claude-code"
        assert rows[0].model == "claude-sonnet-5"
        assert rows[0].input_tokens == 200
        assert rows[0].output_tokens == 80
        assert rows[0].cost_usd == 0.02

    def test_save_context_snapshot_still_writes_yaml_cache(
        self, tmp_path: Path
    ) -> None:
        from superharness.commands.delegate import _save_context_snapshot
        import yaml

        project = self._setup(tmp_path)
        result = {
            "output": "done",
            "input_tokens": 200,
            "output_tokens": 80,
            "cost_usd": 0.02,
        }
        _save_context_snapshot(str(project), "t1", result, model="claude-sonnet-5")

        cache_file = project / ".superharness" / "context-cache" / "t1.yaml"
        assert cache_file.exists()
        snapshot = yaml.safe_load(cache_file.read_text())
        assert snapshot["task_id"] == "t1"
        assert snapshot["input_tokens"] == 200
        assert snapshot["output_tokens"] == 80
        assert snapshot["cost_usd"] == 0.02

    def test_save_context_snapshot_handles_missing_cost_data_gracefully(
        self, tmp_path: Path
    ) -> None:
        from superharness.commands.delegate import _save_context_snapshot
        from superharness.engine import usage_dao
        from superharness.engine.db import get_connection, init_db

        project = self._setup(tmp_path)
        result = {
            "output": "done",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": None,
        }
        _save_context_snapshot(str(project), "t1", result, model="unknown-model")

        conn = get_connection(str(project))
        init_db(conn)
        rows = usage_dao.list_for_task(conn, "t1")
        conn.close()

        assert len(rows) == 1
        assert rows[0].cost_usd is None
