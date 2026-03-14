"""
Tests for superharness.commands.heartbeat — proactive watcher check runner.

Security: check IDs map to hardcoded Python function calls in heartbeat.py.
The 'command:' field in heartbeat.yaml is documentation only and NEVER executed.
"""
from __future__ import annotations

import subprocess
import sys
import time
import textwrap
from pathlib import Path

import yaml

from tests.helpers import REPO_ROOT


def _run_init_py(cwd, args: list[str] | None = None):
    """Run init_project Python module."""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.init_project"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_heartbeat_py(project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run heartbeat Python module with --project PROJECT_DIR."""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.heartbeat",
           "--project", str(project_dir)]
    return subprocess.run(cmd, cwd=str(cwd or project_dir), text=True, capture_output=True, env=env, check=False)


def _make_project(tmp_path: Path, heartbeat_yaml: str | None = None,
                  state_yaml: str | None = None, ledger_lines: list[str] | None = None) -> Path:
    """Create a minimal .superharness layout for heartbeat tests."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()

    if heartbeat_yaml is not None:
        (sh / "heartbeat.yaml").write_text(heartbeat_yaml)

    if state_yaml is not None:
        (sh / "heartbeat-state.yaml").write_text(state_yaml)

    # Write ledger.md (used by idle-warning check)
    ledger = sh / "ledger.md"
    lines = ledger_lines or []
    ledger.write_text("# Ledger\n" + "\n".join(lines) + "\n")

    return tmp_path


# ---------------------------------------------------------------------------
# 1. Module exists
# ---------------------------------------------------------------------------

def test_heartbeat_module_exists() -> None:
    module = REPO_ROOT / "src/superharness/commands/heartbeat.py"
    assert module.exists(), f"src/superharness/commands/heartbeat.py not found at {module}"


# ---------------------------------------------------------------------------
# 2. No config → exits 0 silently
# ---------------------------------------------------------------------------

def test_heartbeat_no_config_exits_0(tmp_path: Path) -> None:
    """When .superharness/heartbeat.yaml is absent, exits 0 with no error."""
    project = _make_project(tmp_path)
    # No heartbeat.yaml created
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, f"Expected exit 0 when no heartbeat.yaml:\n{result.stderr}"


# ---------------------------------------------------------------------------
# 3. Disabled check is not run
# ---------------------------------------------------------------------------

def test_heartbeat_skips_disabled_check(tmp_path: Path) -> None:
    """A check with enabled: false must not be executed."""
    heartbeat_cfg = textwrap.dedent("""\
        checks:
          - id: hygiene-check
            description: Run hygiene
            interval_minutes: 1
            enabled: false
    """)
    project = _make_project(tmp_path, heartbeat_yaml=heartbeat_cfg)
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, result.stderr
    # Should not print "running check"
    assert "running check" not in result.stdout.lower()


# ---------------------------------------------------------------------------
# 4. Unknown ID is logged and skipped, not executed
# ---------------------------------------------------------------------------

def test_heartbeat_unknown_id_skipped(tmp_path: Path) -> None:
    """An id not in the allowlist is logged with 'unknown check id' and skipped."""
    heartbeat_cfg = textwrap.dedent("""\
        checks:
          - id: evil-arbitrary-command
            description: "rm -rf /"
            interval_minutes: 1
            enabled: true
    """)
    project = _make_project(tmp_path, heartbeat_yaml=heartbeat_cfg)
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, f"Should not error-exit on unknown id:\n{result.stderr}"
    assert "unknown check id" in result.stdout.lower() or "unknown check id" in result.stderr.lower(), \
        f"Expected 'unknown check id' in output:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# 5. Enabled check runs when interval has elapsed
# ---------------------------------------------------------------------------

def test_heartbeat_runs_enabled_check_when_interval_elapsed(tmp_path: Path) -> None:
    """idle-warning check fires when interval has elapsed (last_run far in past)."""
    heartbeat_cfg = textwrap.dedent("""\
        checks:
          - id: idle-warning
            description: Warn if no ledger activity in 48 hours
            interval_minutes: 60
            enabled: true
    """)
    # Set last_run to a long time ago (epoch 1 = 1970)
    state_yaml = textwrap.dedent("""\
        idle-warning:
          last_run: 1
    """)
    # Write a recent ledger entry so idle-warning does NOT warn (we just want to verify it ran)
    ledger_lines = ["- 2026-01-01T00:00:00Z | claude-code | some task"]
    project = _make_project(tmp_path, heartbeat_yaml=heartbeat_cfg,
                            state_yaml=state_yaml, ledger_lines=ledger_lines)
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, result.stderr
    assert "running check 'idle-warning'" in result.stdout or \
           "running check \"idle-warning\"" in result.stdout, \
        f"Expected 'running check idle-warning' in output:\n{result.stdout}"


# ---------------------------------------------------------------------------
# 6. Check is skipped when interval has NOT elapsed
# ---------------------------------------------------------------------------

def test_heartbeat_skips_check_before_interval(tmp_path: Path) -> None:
    """When last_run is recent (within interval), the check is NOT run."""
    heartbeat_cfg = textwrap.dedent("""\
        checks:
          - id: idle-warning
            description: Warn if no ledger activity
            interval_minutes: 1440
            enabled: true
    """)
    # Set last_run to NOW (interval: 1440 minutes = 24h, so not elapsed)
    now_epoch = int(time.time())
    state_yaml = f"idle-warning:\n  last_run: {now_epoch}\n"
    project = _make_project(tmp_path, heartbeat_yaml=heartbeat_cfg, state_yaml=state_yaml)
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, result.stderr
    assert "running check" not in result.stdout.lower(), \
        f"Check should NOT run before interval:\n{result.stdout}"


# ---------------------------------------------------------------------------
# 7. State file is updated after a check runs
# ---------------------------------------------------------------------------

def test_heartbeat_updates_state_after_run(tmp_path: Path) -> None:
    """After running a check, heartbeat-state.yaml is updated with a recent last_run."""
    heartbeat_cfg = textwrap.dedent("""\
        checks:
          - id: idle-warning
            description: Warn if no ledger activity
            interval_minutes: 60
            enabled: true
    """)
    state_yaml = "idle-warning:\n  last_run: 1\n"
    project = _make_project(tmp_path, heartbeat_yaml=heartbeat_cfg, state_yaml=state_yaml)
    before_run = int(time.time())
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, result.stderr

    state_file = project / ".superharness" / "heartbeat-state.yaml"
    assert state_file.exists(), "heartbeat-state.yaml should be created after a run"
    state = yaml.safe_load(state_file.read_text())
    last_run = state.get("idle-warning", {}).get("last_run", 0)
    assert last_run >= before_run, \
        f"last_run ({last_run}) should be >= before_run ({before_run})"


# ---------------------------------------------------------------------------
# 8. Check with unexpired interval: state is NOT updated
# ---------------------------------------------------------------------------

def test_heartbeat_never_runs_when_interval_not_elapsed(tmp_path: Path) -> None:
    """When interval has not elapsed, state file is unchanged."""
    heartbeat_cfg = textwrap.dedent("""\
        checks:
          - id: idle-warning
            description: Warn if no ledger activity
            interval_minutes: 1440
            enabled: true
    """)
    now_epoch = int(time.time())
    original_last_run = now_epoch - 60  # 1 minute ago, interval is 1440 min
    state_yaml = f"idle-warning:\n  last_run: {original_last_run}\n"
    project = _make_project(tmp_path, heartbeat_yaml=heartbeat_cfg, state_yaml=state_yaml)
    result = _run_heartbeat_py(project)
    assert result.returncode == 0, result.stderr

    state_file = project / ".superharness" / "heartbeat-state.yaml"
    if state_file.exists():
        state = yaml.safe_load(state_file.read_text())
        last_run = state.get("idle-warning", {}).get("last_run", 0)
        assert last_run == original_last_run, \
            f"State should be unchanged when interval not elapsed: expected {original_last_run}, got {last_run}"


# ---------------------------------------------------------------------------
# 9. Default heartbeat template exists
# ---------------------------------------------------------------------------

def test_default_heartbeat_template_exists() -> None:
    template = REPO_ROOT / "protocol/templates/heartbeat.yaml"
    assert template.exists(), f"protocol/templates/heartbeat.yaml not found at {template}"


# ---------------------------------------------------------------------------
# 10. Default template has stale-recovery enabled
# ---------------------------------------------------------------------------

def test_default_heartbeat_has_stale_recovery_enabled() -> None:
    template = REPO_ROOT / "protocol/templates/heartbeat.yaml"
    assert template.exists(), "protocol/templates/heartbeat.yaml not found"
    data = yaml.safe_load(template.read_text())
    checks = {c["id"]: c for c in data.get("checks", [])}
    assert "stale-recovery" in checks, "stale-recovery check not found in template"
    assert checks["stale-recovery"].get("enabled") is True, \
        "stale-recovery should be enabled: true in template"


# ---------------------------------------------------------------------------
# 11. init_project.py creates .superharness/heartbeat.yaml
# ---------------------------------------------------------------------------

def test_init_creates_heartbeat_yaml(tmp_path: Path) -> None:
    """init_project.py should copy heartbeat.yaml template into .superharness/."""
    result = _run_init_py(tmp_path, args=["TestProject", "Shell", "active"])
    assert result.returncode == 0, f"init_project.py failed:\n{result.stderr}"
    hb_file = tmp_path / ".superharness" / "heartbeat.yaml"
    assert hb_file.exists(), \
        f".superharness/heartbeat.yaml not created by init_project.py:\n{result.stdout}"
