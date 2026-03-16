from __future__ import annotations

import platform
from pathlib import Path

import pytest

from tests.helpers import run_bash


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text("id: demo\n")
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused|stopped",
                "",
                "- id: retry-item",
                "  to: codex-cli",
                "  task: demo-task",
                f"  project: {project}",
                "  status: launched",
                "  retry_count: 4",
                "  max_retries: 6",
                "  created_at: 2026-03-12T00:00:00Z",
            ]
        )
        + "\n"
    )
    return project


def _fake_bin(tmp_path: Path, *, darwin: bool, launchctl_ok: bool) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    uname = bin_dir / "uname"
    uname.write_text("#!/bin/bash\n" + ("echo Darwin\n" if darwin else "echo Linux\n"))
    uname.chmod(0o755)

    launchctl = bin_dir / "launchctl"
    if launchctl_ok:
        launchctl.write_text(
            "#!/bin/bash\n"
            "if [ \"$1\" = \"print\" ]; then\n"
            "  cat <<'OUT'\n"
            "state = running\n"
            "last exit code = 0\n"
            "run interval = 15 seconds\n"
            "OUT\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        )
    else:
        launchctl.write_text("#!/bin/bash\nexit 1\n")
    launchctl.chmod(0o755)
    return bin_dir


@pytest.mark.skipif(platform.system() != "Darwin", reason="launchctl-based watcher check is Darwin-only")
def test_status_reports_retry_alert_and_watcher_problem(repo_root: Path, tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    fake_bin = _fake_bin(tmp_path, darwin=True, launchctl_ok=False)
    wrapper = repo_root / "superharness"

    result = run_bash(
        wrapper,
        cwd=repo_root,
        args=["status", "--project", str(project), "--retry-threshold", "3"],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "watcher: level=bad" in result.stdout
    assert "retry-alert: threshold=3 high=1" in result.stdout

    check = run_bash(
        wrapper,
        cwd=repo_root,
        args=["status", "--project", str(project), "--retry-threshold", "3", "--check"],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert check.returncode == 1


def test_notify_retry_threshold_alert_and_cooldown(repo_root: Path, tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    fake_bin = _fake_bin(tmp_path, darwin=True, launchctl_ok=True)
    wrapper = repo_root / "superharness"
    state_file = tmp_path / "notify.state"

    first = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "notify",
            "--project",
            str(project),
            "--retry-threshold",
            "3",
            "--watcher-down-streak",
            "3",
            "--cooldown-minutes",
            "60",
            "--state-file",
            str(state_file),
            "--dry-run",
        ],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert first.returncode == 10, first.stderr
    assert "retry_threshold:1 item(s) >= 3" in first.stdout
    assert state_file.exists()

    second = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "notify",
            "--project",
            str(project),
            "--retry-threshold",
            "3",
            "--watcher-down-streak",
            "3",
            "--cooldown-minutes",
            "60",
            "--state-file",
            str(state_file),
            "--dry-run",
        ],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert second.returncode == 11, second.stderr
    assert "suppressed by cooldown/fingerprint" in second.stdout


def test_status_shows_heartbeat_missing(repo_root: Path, tmp_path: Path) -> None:
    """status.sh must report heartbeat=missing when no heartbeat file exists."""
    project = _setup_project(tmp_path)
    fake_bin = _fake_bin(tmp_path, darwin=True, launchctl_ok=True)

    result = run_bash(
        repo_root / "superharness",
        cwd=repo_root,
        args=["status", "--project", str(project)],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "heartbeat: missing" in result.stdout.lower(), (
        f"status must show heartbeat=missing, got: {result.stdout}"
    )


def test_status_shows_heartbeat_stale(repo_root: Path, tmp_path: Path) -> None:
    """status.sh must report heartbeat=stale when heartbeat is old."""
    project = _setup_project(tmp_path)
    fake_bin = _fake_bin(tmp_path, darwin=True, launchctl_ok=True)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    import time
    from datetime import datetime, timezone

    stale_time = time.time() - 600
    stale_ts = datetime.fromtimestamp(stale_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(stale_ts + "\n")

    result = run_bash(
        repo_root / "superharness",
        cwd=repo_root,
        args=["status", "--project", str(project)],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "heartbeat: stale" in result.stdout.lower(), (
        f"status must show heartbeat=stale, got: {result.stdout}"
    )


def test_status_shows_heartbeat_ok(repo_root: Path, tmp_path: Path) -> None:
    """status.sh must report heartbeat=ok when heartbeat is fresh."""
    project = _setup_project(tmp_path)
    fake_bin = _fake_bin(tmp_path, darwin=True, launchctl_ok=True)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    from datetime import datetime, timezone
import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

    fresh_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(fresh_ts + "\n")

    result = run_bash(
        repo_root / "superharness",
        cwd=repo_root,
        args=["status", "--project", str(project)],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "heartbeat: ok" in result.stdout.lower(), (
        f"status must show heartbeat=ok, got: {result.stdout}"
    )
