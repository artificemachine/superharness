from __future__ import annotations

"""TDD tests for `superharness status` (Phase 4c)."""

import os
import stat
import time


from tests.helpers import run_bash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_status(repo_root, project_dir):
    """Run cli/status.sh --project <project_dir>."""
    return run_bash(
        repo_root / "cli/status.sh",
        cwd=project_dir,
        args=["--project", str(project_dir)],
    )


def _write_contract(project_dir, *, contract_id="initial-setup", status="active",
                    goal="TBD — describe the current objective", tasks=None):
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(parents=True, exist_ok=True)
    if tasks:
        tasks_block = "tasks:\n"
        for t in tasks:
            tasks_block += (
                f"  - id: {t['id']}\n"
                f"    title: {t['title']}\n"
                f"    status: {t['status']}\n"
                f"    owner: {t.get('owner', 'claude-code')}\n"
            )
    else:
        tasks_block = "tasks: []\n"

    content = (
        f"id: {contract_id}\n"
        f'created: "2026-01-01"\n'
        f"created_by: owner\n"
        f"status: {status}\n"
        f'goal: "{goal}"\n'
        f"{tasks_block}"
        f"decisions: []\n"
        f"failures: []\n"
    )
    (sh_dir / "contract.yaml").write_text(content)


def _write_ledger(project_dir, lines):
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(parents=True, exist_ok=True)
    text = "# Ledger\n\n" + "\n".join(lines) + "\n"
    (sh_dir / "ledger.md").write_text(text)


def _write_heartbeat(project_dir, *, seconds_ago=5):
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(parents=True, exist_ok=True)
    hb = sh_dir / "watcher.heartbeat"
    hb.write_text("2026-03-12T00:00:00Z\n")
    # Set mtime to the desired age
    mtime = time.time() - seconds_ago
    os.utime(hb, (mtime, mtime))


def _write_profile(project_dir, *, autonomy="supervised", primary_agent="claude-code",
                   team_size="solo"):
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"autonomy: {autonomy}\n"
        f"primary_agent: {primary_agent}\n"
        f"team_size: {team_size}\n"
    )
    (sh_dir / "profile.yaml").write_text(content)


# ---------------------------------------------------------------------------
# 1. cli/status.sh is executable
# ---------------------------------------------------------------------------

def test_status_script_is_executable(repo_root) -> None:
    script = repo_root / "cli/status.sh"
    assert script.exists(), "cli/status.sh not found"
    assert script.stat().st_mode & stat.S_IXUSR, "cli/status.sh is not executable"


# ---------------------------------------------------------------------------
# 2. No contract.yaml → shows fallback message
# ---------------------------------------------------------------------------

def test_status_no_contract(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    combined = result.stdout + result.stderr
    assert "none" in combined.lower() or "run superharness init" in combined.lower(), (
        f"Expected fallback message, got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# 3. Contract id and goal appear in output
# ---------------------------------------------------------------------------

def test_status_shows_contract_id_and_goal(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, contract_id="my-contract", goal="Build the rocket")

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "my-contract" in result.stdout
    assert "Build the rocket" in result.stdout


# ---------------------------------------------------------------------------
# 4. Task counts are correct
# ---------------------------------------------------------------------------

def test_status_task_counts(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, tasks=[
        {"id": "task-a", "title": "First", "status": "todo"},
        {"id": "task-b", "title": "Second", "status": "todo"},
        {"id": "task-c", "title": "Third", "status": "done"},
    ])

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "2 pending" in result.stdout
    assert "0 running" in result.stdout
    assert "1 done" in result.stdout


# ---------------------------------------------------------------------------
# 5. Next task shown
# ---------------------------------------------------------------------------

def test_status_next_task(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, tasks=[
        {"id": "first-task", "title": "Do this first", "status": "todo", "owner": "codex-cli"},
        {"id": "second-task", "title": "Do this second", "status": "todo"},
    ])

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "first-task" in result.stdout
    assert "Next:" in result.stdout


# ---------------------------------------------------------------------------
# 6. No ledger → "(none)"
# ---------------------------------------------------------------------------

def test_status_no_ledger(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "(none)" in result.stdout


# ---------------------------------------------------------------------------
# 7. Ledger last entry appears in output
# ---------------------------------------------------------------------------

def test_status_ledger_last_entry(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)
    _write_ledger(project, [
        "2026-01-01 | did the first thing",
        "2026-01-02 | finished the second thing",
    ])

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "finished the second thing" in result.stdout


# ---------------------------------------------------------------------------
# 8. No watcher heartbeat → "unknown"
# ---------------------------------------------------------------------------

def test_status_no_watcher_heartbeat(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "unknown" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 9. Fresh heartbeat → "running"
# ---------------------------------------------------------------------------

def test_status_fresh_watcher(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)
    _write_heartbeat(project, seconds_ago=5)

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "running" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 10. Stale heartbeat (> 90s old) → "stale"
# ---------------------------------------------------------------------------

def test_status_stale_watcher(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)
    _write_heartbeat(project, seconds_ago=600)  # 10 minutes

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "stale" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 11. No profile.yaml → "(default" in output
# ---------------------------------------------------------------------------

def test_status_no_profile(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "(default" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 12. profile.yaml shows autonomy, primary_agent, team_size
# ---------------------------------------------------------------------------

def test_status_with_profile(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project)
    _write_profile(project, autonomy="autonomous", primary_agent="codex-cli", team_size="small")

    result = _run_status(repo_root, project)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "autonomous" in result.stdout
    assert "codex-cli" in result.stdout
    assert "small" in result.stdout
