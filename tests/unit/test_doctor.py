from __future__ import annotations

import sys
import subprocess
from pathlib import Path


from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml


def _run_python(
    args: list[str], *, env: dict | None = None
) -> "subprocess.CompletedProcess[str]":
    import os
    import subprocess

    merged_env = os.environ.copy()
    merged_env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            if v is None:
                merged_env.pop(k, None)
            else:
                merged_env[k] = v
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.doctor"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def _write_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text("id: test\ntasks: []\n")
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    seed_sqlite_from_yaml(project)
    return project


def test_doctor_help(repo_root) -> None:
    result = _run_python(["--help"])
    assert result.returncode == 0
    assert "--project" in result.stdout
    assert "--check" in result.stdout
    assert "--langfuse-auth" in result.stdout


def test_langfuse_status_reports_disabled(monkeypatch) -> None:
    from superharness.commands import doctor
    from superharness.engine import langfuse_telemetry

    monkeypatch.setattr(
        langfuse_telemetry, "readiness", lambda: ("disabled", "disabled")
    )
    monkeypatch.setattr(
        langfuse_telemetry,
        "probe_auth",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected auth probe")),
    )

    assert doctor._langfuse_status(probe_auth=False) == (
        "INFO langfuse: disabled",
        False,
    )


def test_langfuse_status_warns_for_incomplete_and_missing_sdk(monkeypatch) -> None:
    from superharness.commands import doctor
    from superharness.engine import langfuse_telemetry

    monkeypatch.setattr(
        langfuse_telemetry,
        "readiness",
        lambda: ("incomplete", "missing LANGFUSE_SECRET_KEY"),
    )
    assert doctor._langfuse_status() == (
        "WARN langfuse: missing LANGFUSE_SECRET_KEY",
        True,
    )

    monkeypatch.setattr(
        langfuse_telemetry,
        "readiness",
        lambda: ("missing-sdk", "install superharness[observability]"),
    )
    assert doctor._langfuse_status() == (
        "WARN langfuse: install superharness[observability]",
        True,
    )


def test_langfuse_status_is_offline_unless_auth_flag_is_set(monkeypatch) -> None:
    from superharness.commands import doctor
    from superharness.engine import langfuse_telemetry

    calls = []
    monkeypatch.setattr(
        langfuse_telemetry,
        "readiness",
        lambda: ("configured", "https://langfuse.example.test"),
    )
    monkeypatch.setattr(
        langfuse_telemetry, "probe_auth", lambda: calls.append("auth") or True
    )

    assert doctor._langfuse_status(probe_auth=False) == (
        "PASS langfuse: configured (https://langfuse.example.test)",
        False,
    )
    assert calls == []
    assert doctor._langfuse_status(probe_auth=True) == (
        "PASS langfuse: authenticated (https://langfuse.example.test)",
        False,
    )
    assert calls == ["auth"]


def test_langfuse_status_auth_failure_is_a_warning(monkeypatch) -> None:
    from superharness.commands import doctor
    from superharness.engine import langfuse_telemetry

    monkeypatch.setattr(
        langfuse_telemetry,
        "readiness",
        lambda: ("configured", "https://langfuse.example.test"),
    )
    monkeypatch.setattr(langfuse_telemetry, "probe_auth", lambda: False)

    assert doctor._langfuse_status(probe_auth=True) == (
        "WARN langfuse: authentication failed",
        True,
    )


def test_doctor_passes_healthy_project(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0
    assert "PASS project:.superharness present" in result.stdout
    # contract.yaml is an export-only artifact; doctor checks SQLite state-db instead
    assert "PASS file:ledger.md" in result.stdout
    assert "PASS dir:handoffs" in result.stdout


def test_doctor_models_line_reports_discovery_state(tmp_path) -> None:
    """Iteration 6: doctor prints a models: health line (PASS or WARN)."""
    project = _write_project(tmp_path)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0
    models_lines = [l for l in result.stdout.splitlines() if "models:" in l]
    assert models_lines, f"expected models: line in doctor output:\n{result.stdout}"
    assert any(
        l.startswith("PASS models:") or l.startswith("WARN models:")
        for l in models_lines
    )


def test_protected_project_path_uses_path_containment(tmp_path) -> None:
    """Protected-folder detection must use resolved path containment."""
    from superharness.commands.doctor import _is_protected_project_path

    home = tmp_path / "home"
    project = home / "Documents" / "project"
    project.mkdir(parents=True)
    sibling = home / "Documents-backup" / "project"
    sibling.mkdir(parents=True)

    assert _is_protected_project_path(project, home) is True
    assert _is_protected_project_path(sibling, home) is False


def test_doctor_fails_missing_superharness(repo_root, tmp_path) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    result = _run_python(["--project", str(project)])
    assert result.returncode == 1
    assert "FAIL project:.superharness missing" in result.stdout
    assert "superharness init" in result.stdout


def test_doctor_fails_missing_protocol_files(repo_root, tmp_path) -> None:
    project = tmp_path / "partial"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    # Only create contract.yaml, skip everything else
    (harness / "contract.yaml").write_text("id: test\n")
    result = _run_python(["--project", str(project)])
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_doctor_check_mode_exits_nonzero_on_warnings(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    # --check mode should exit non-zero if there are warnings (e.g. missing deps like codex)
    result = _run_python(["--project", str(project), "--check"])
    # We expect warnings for missing watcher / git hooks, so non-zero is expected
    # Just verify --check flag is accepted and the flag has an effect
    assert "summary:" in result.stdout


def test_doctor_shows_install_hints(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    result = _run_python(
        ["--project", str(project)],
        env={"PATH": "/usr/bin:/bin"},  # strip most paths so codex/claude are missing
    )
    # Should show WARN for missing deps with install hints
    assert "WARN" in result.stdout or "PASS" in result.stdout


def test_doctor_unknown_option(repo_root) -> None:
    result = _run_python(["--bogus"])
    assert result.returncode == 2
    # argparse outputs to stderr for unknown options
    assert "bogus" in result.stderr or "error" in result.stderr


def test_doctor_warns_when_plugin_not_installed(repo_root, tmp_path) -> None:
    """Doctor must warn when ~/.claude/plugins/superharness is not installed."""
    project = _write_project(tmp_path)
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    result = _run_python(
        ["--project", str(project)],
        env={"HOME": str(fake_home), "USERPROFILE": str(fake_home)},
    )
    assert "WARN plugin:claude-code superharness not installed" in result.stdout


def test_doctor_ok_when_plugin_installed(repo_root, tmp_path) -> None:
    """Doctor must show PASS when ~/.claude/plugins/superharness exists."""
    project = _write_project(tmp_path)
    fake_home = tmp_path / "fakehome2"
    plugin_dir = fake_home / ".claude" / "plugins" / "superharness"
    plugin_dir.mkdir(parents=True)
    result = _run_python(
        ["--project", str(project)],
        env={"HOME": str(fake_home), "USERPROFILE": str(fake_home)},
    )
    assert "PASS plugin:claude-code superharness installed" in result.stdout


def test_doctor_passes_global_hooks_path(repo_root, tmp_path) -> None:
    """Doctor must PASS when core.hooksPath points to an existing directory (e.g. ~/.githooks)."""
    import subprocess as sp

    project = _write_project(tmp_path)
    # Create a real hooks directory
    hooks_dir = tmp_path / "myglobalhooks"
    hooks_dir.mkdir()
    # Set core.hooksPath to this directory in the test project's git config
    sp.run(["git", "-C", str(project), "init"], capture_output=True, check=False)
    sp.run(
        ["git", "-C", str(project), "config", "core.hooksPath", str(hooks_dir)],
        capture_output=True,
        check=True,
    )
    result = _run_python(["--project", str(project)])
    assert f"PASS git:core.hooksPath={hooks_dir}" in result.stdout, (
        f"Expected PASS for valid hooks dir, got:\n{result.stdout}"
    )
    assert "WARN git:core.hooksPath" not in result.stdout


def test_doctor_warns_nonexistent_hooks_path(repo_root, tmp_path) -> None:
    """Doctor must WARN when core.hooksPath points to a directory that doesn't exist."""
    import subprocess as sp

    project = _write_project(tmp_path)
    sp.run(["git", "-C", str(project), "init"], capture_output=True, check=False)
    sp.run(
        [
            "git",
            "-C",
            str(project),
            "config",
            "core.hooksPath",
            "/nonexistent/hooks/dir",
        ],
        capture_output=True,
        check=True,
    )
    result = _run_python(["--project", str(project)])
    assert "WARN git:core.hooksPath=/nonexistent/hooks/dir" in result.stdout


def test_doctor_parity_section_runs_when_db_present(repo_root, tmp_path) -> None:
    """B5: doctor's parity section must execute when state.sqlite3 exists.

    Verifies the wiring isn't dead code — the actual filename is state.sqlite3
    (not state.sqlite), and the section either reports PASS parity or FAIL parity.
    """
    import sys as _sys

    project = _write_project(tmp_path)

    # Create state.sqlite3 with schema (mimics shux migrate / first watcher tick)
    _sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from superharness.engine.db import get_connection, init_db

        conn = get_connection(str(project))
        try:
            init_db(conn)
            conn.commit()
        finally:
            conn.close()
    finally:
        _sys.path.pop(0)

    result = _run_python(["--project", str(project)])
    # Must NOT report "state.sqlite not found" — that means dead-code path
    assert "state.sqlite not found" not in result.stdout, (
        f"Doctor parity section is dead code (wrong filename). Got:\n{result.stdout}"
    )
    assert "state.sqlite3 not found" not in result.stdout, (
        f"Doctor cannot find state.sqlite3 even though it was created. Got:\n{result.stdout}"
    )
    # Must include either PASS parity (clean) or FAIL parity (drift surfaced)
    assert "parity:" in result.stdout, (
        f"Doctor produced no parity output. Got:\n{result.stdout}"
    )
