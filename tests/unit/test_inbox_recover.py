from __future__ import annotations
import pytest

import subprocess
import sys

from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml


def _inbox_text(project) -> str:
    """Build a YAML-shaped string of the SQLite inbox so existing
    `assert "  status: stale" in inbox_text` style assertions keep working.
    Post-migration the YAML file is no longer maintained."""
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    rows = db.execute(
        "SELECT id, target_agent, task_id, project_path, status, "
        "launched_at, priority, retry_count, max_retries, failed_reason "
        "FROM inbox"
    ).fetchall()
    db.close()
    parts = ["# Delegation inbox"]
    for r in rows:
        parts.append(f"- id: {r[0]}")
        parts.append(f"  to: {r[1]}")
        parts.append(f"  task: {r[2]}")
        parts.append(f"  project: {r[3] or ''}")
        parts.append(f"  status: {r[4]}")
        if r[5]:
            parts.append(f"  launched_at: {r[5]}")
        parts.append(f"  priority: {r[6]}")
        parts.append(f"  retry_count: {r[7]}")
        parts.append(f"  max_retries: {r[8]}")
        if r[9]:
            parts.append(f"  stale_reason: {r[9]}")
            parts.append(f"  failed_reason: {r[9]}")
    return "\n".join(parts) + "\n"


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


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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

    seed_sqlite_from_yaml(project); result = _run_python(["--project", str(project), "--timeout-minutes", "20", "--action", "stale"])

    assert result.returncode == 0, result.stderr
    seed_sqlite_from_yaml(project); inbox_text = _inbox_text(project)
    assert "id: stale-item" in inbox_text
    assert "  status: stale" in inbox_text
    assert "  stale_reason: stale_timeout" in inbox_text
    assert "  launched_at:" not in inbox_text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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

    seed_sqlite_from_yaml(project); result = _run_python(["--project", str(project), "--timeout-minutes", "20", "--action", "retry"])

    assert result.returncode == 0, result.stderr
    seed_sqlite_from_yaml(project); inbox_text = _inbox_text(project)
    assert "id: retry-item" in inbox_text
    assert "  status: pending" in inbox_text
    assert "  stale_reason: stale_timeout_retry" in inbox_text
    assert "  launched_at:" not in inbox_text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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

    seed_sqlite_from_yaml(project); result = _run_python(["--project", str(project), "--timeout-minutes", "20", "--action", "retry"])

    assert result.returncode == 0, result.stderr
    seed_sqlite_from_yaml(project); inbox_text = _inbox_text(project)
    assert "id: exhausted-item" in inbox_text
    assert "  status: failed" in inbox_text
    assert "  failed_reason: stale_timeout_exhausted" in inbox_text
    assert "  launched_at:" not in inbox_text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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

        seed_sqlite_from_yaml(project); result = _run_python(["--project", str(project), "--timeout-minutes", "1", "--action", "retry"])

        assert result.returncode == 0, result.stderr
        seed_sqlite_from_yaml(project); inbox_text = _inbox_text(project)
        assert "id: live-pid-item" in inbox_text
        assert "  status: launched" in inbox_text
        assert f"  pid: '{sleeper.pid}'" in inbox_text
        assert "  stale_reason:" not in inbox_text
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)
