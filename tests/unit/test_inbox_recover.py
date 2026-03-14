from __future__ import annotations

import subprocess
import sys

from tests.helpers import REPO_ROOT


def _run_python(args: list[str]) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.inbox_recover"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_recover_marks_old_launched_items_stale(repo_root, tmp_path) -> None:
    project = tmp_path / "proj-recover"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: stale-item",
                "  to: codex-cli",
                "  task: demo",
                f"  project: {project}",
                "  status: launched",
                "  launched_at: 2026-01-01T00:00:00Z",
                "  priority: 1",
                "  retry_count: 1",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )

    result = _run_python(["--project", str(project), "--timeout-minutes", "20", "--action", "stale"])

    assert result.returncode == 0, result.stderr
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: stale-item" in inbox_text
    assert "  status: stale" in inbox_text
    assert "  stale_reason: stale_timeout" in inbox_text
    assert "  launched_at:" not in inbox_text


def test_recover_retries_old_launched_items_when_budget_available(repo_root, tmp_path) -> None:
    project = tmp_path / "proj-recover-retry"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: retry-item",
                "  to: codex-cli",
                "  task: demo",
                f"  project: {project}",
                "  status: launched",
                "  launched_at: 2026-01-01T00:00:00Z",
                "  priority: 1",
                "  retry_count: 1",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )

    result = _run_python(["--project", str(project), "--timeout-minutes", "20", "--action", "retry"])

    assert result.returncode == 0, result.stderr
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: retry-item" in inbox_text
    assert "  status: pending" in inbox_text
    assert "  stale_reason: stale_timeout_retry" in inbox_text
    assert "  launched_at:" not in inbox_text


def test_recover_fails_old_launched_items_when_retry_exhausted(repo_root, tmp_path) -> None:
    project = tmp_path / "proj-recover-exhausted"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: exhausted-item",
                "  to: codex-cli",
                "  task: demo",
                f"  project: {project}",
                "  status: launched",
                "  launched_at: 2026-01-01T00:00:00Z",
                "  priority: 1",
                "  retry_count: 3",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )

    result = _run_python(["--project", str(project), "--timeout-minutes", "20", "--action", "retry"])

    assert result.returncode == 0, result.stderr
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: exhausted-item" in inbox_text
    assert "  status: failed" in inbox_text
    assert "  failed_reason: stale_timeout_exhausted" in inbox_text
    assert "  launched_at:" not in inbox_text


def test_recover_keeps_launched_item_when_pid_is_still_alive(repo_root, tmp_path) -> None:
    project = tmp_path / "proj-recover-live-pid"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)

    sleeper = subprocess.Popen(["sleep", "30"])  # noqa: S603,S607
    try:
        (harness / "inbox.yaml").write_text(
            "\n".join(
                [
                    "# Delegation inbox",
                    "# status: pending|launched|running|done|failed|stale",
                    "",
                    "- id: live-pid-item",
                    "  to: codex-cli",
                    "  task: demo",
                    f"  project: {project}",
                    "  status: launched",
                    "  launched_at: 2026-01-01T00:00:00Z",
                    f"  pid: '{sleeper.pid}'",
                    "  priority: 1",
                    "  retry_count: 1",
                    "  max_retries: 3",
                ]
            )
            + "\n"
        )

        result = _run_python(["--project", str(project), "--timeout-minutes", "1", "--action", "retry"])

        assert result.returncode == 0, result.stderr
        inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
        assert "id: live-pid-item" in inbox_text
        assert "  status: launched" in inbox_text
        assert f"  pid: '{sleeper.pid}'" in inbox_text
        assert "  stale_reason:" not in inbox_text
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)
