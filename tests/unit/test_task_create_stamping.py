"""Iteration 1: per-task policy stamping at `shux task create`.

Verifies that `shux task create` reads the project profile.yaml and stamps
`autonomy` + `require_tdd` onto the task record. Explicit CLI flags override.
Existing tasks are never mutated.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

PYTHON = sys.executable


def _make_project(tmp_path: Path, profile: dict | None = None) -> Path:
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text("id: test\ntasks:\n")
    if profile is not None:
        (project / ".superharness" / "profile.yaml").write_text(yaml.dump(profile))
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)
    return project


def _run_task(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.task"] + args,
        capture_output=True, text=True, check=False,
    )


def _read_task(project: Path, task_id: str) -> dict:
    doc = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    for t in doc.get("tasks", []):
        if isinstance(t, dict) and t.get("id") == task_id:
            return t
    raise AssertionError(f"task {task_id} not in contract")


def test_create_stamps_ai_driven_when_profile_absent(tmp_path: Path) -> None:
    """No profile.yaml → task stamps safe defaults (ai_driven + require_tdd)."""
    project = _make_project(tmp_path, profile=None)
    r = _run_task(["create", "--project", str(project), "--id", "t1",
                   "--title", "x", "--owner", "claude-code"])
    assert r.returncode == 0, r.stderr
    task = _read_task(project, "t1")
    assert task["autonomy"] == "ai_driven"
    assert task["require_tdd"] is True


def test_create_stamps_profile_autonomy(tmp_path: Path) -> None:
    """profile.autonomy=oversight → task.autonomy=oversight."""
    project = _make_project(tmp_path, profile={"autonomy": "oversight"})
    r = _run_task(["create", "--project", str(project), "--id", "t1",
                   "--title", "x", "--owner", "claude-code"])
    assert r.returncode == 0, r.stderr
    task = _read_task(project, "t1")
    assert task["autonomy"] == "oversight"


def test_create_stamps_profile_require_tdd_false(tmp_path: Path) -> None:
    """profile.workflow.require_tdd=false → task.require_tdd=false."""
    project = _make_project(tmp_path, profile={
        "workflow": {"require_tdd": False},
    })
    r = _run_task(["create", "--project", str(project), "--id", "t1",
                   "--title", "x", "--owner", "claude-code"])
    assert r.returncode == 0, r.stderr
    task = _read_task(project, "t1")
    assert task["require_tdd"] is False


def test_explicit_autonomy_flag_overrides_profile(tmp_path: Path) -> None:
    """CLI --autonomy hands_on overrides profile.autonomy."""
    project = _make_project(tmp_path, profile={"autonomy": "ai_driven"})
    r = _run_task(["create", "--project", str(project), "--id", "t1",
                   "--title", "x", "--owner", "claude-code",
                   "--autonomy", "hands_on"])
    assert r.returncode == 0, r.stderr
    task = _read_task(project, "t1")
    assert task["autonomy"] == "hands_on"


def test_explicit_no_require_tdd_overrides_profile(tmp_path: Path) -> None:
    """CLI --no-require-tdd overrides profile.workflow.require_tdd=true."""
    project = _make_project(tmp_path, profile={"workflow": {"require_tdd": True}})
    r = _run_task(["create", "--project", str(project), "--id", "t1",
                   "--title", "x", "--owner", "claude-code",
                   "--no-require-tdd"])
    assert r.returncode == 0, r.stderr
    task = _read_task(project, "t1")
    assert task["require_tdd"] is False


def test_invalid_autonomy_rejected(tmp_path: Path) -> None:
    """--autonomy garbage → exit 2, error mentions valid values."""
    project = _make_project(tmp_path, profile=None)
    r = _run_task(["create", "--project", str(project), "--id", "t1",
                   "--title", "x", "--owner", "claude-code",
                   "--autonomy", "garbage"])
    assert r.returncode == 2
    err = (r.stderr + r.stdout).lower()
    assert "ai_driven" in err or "autonomy" in err


def test_existing_tasks_unchanged_after_second_create(tmp_path: Path) -> None:
    """Creating t2 under a different profile does not mutate t1."""
    project = _make_project(tmp_path, profile={"autonomy": "ai_driven"})
    _run_task(["create", "--project", str(project), "--id", "t1",
               "--title", "x", "--owner", "claude-code"])
    # Change profile
    (project / ".superharness" / "profile.yaml").write_text(
        yaml.dump({"autonomy": "oversight"})
    )
    _run_task(["create", "--project", str(project), "--id", "t2",
               "--title", "y", "--owner", "claude-code"])
    t1 = _read_task(project, "t1")
    t2 = _read_task(project, "t2")
    assert t1["autonomy"] == "ai_driven"
    assert t2["autonomy"] == "oversight"


def test_autonomy_enum_values(tmp_path: Path) -> None:
    """All three autonomy values are accepted."""
    project = _make_project(tmp_path, profile=None)
    for i, val in enumerate(["ai_driven", "oversight", "hands_on"]):
        r = _run_task(["create", "--project", str(project), "--id", f"t{i}",
                       "--title", "x", "--owner", "claude-code",
                       "--autonomy", val])
        assert r.returncode == 0, r.stderr
        assert _read_task(project, f"t{i}")["autonomy"] == val
