from __future__ import annotations

"""Tests for engine/profile.py"""

import sys

from tests.helpers import run_cmd, REPO_ROOT


def _run_profile(tmp_path, *args):
    return run_cmd(
        [sys.executable, "-m", "superharness.engine.profile"] + list(args),
        cwd=tmp_path,
    )


def _write_profile(harness_dir, **fields):
    harness_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, v in fields.items():
        if isinstance(v, str):
            lines.append(f"{k}: '{v}'")
        else:
            lines.append(f"{k}: {v}")
    (harness_dir / "profile.yaml").write_text("\n".join(lines) + "\n")


# ── script basics ─────────────────────────────────────────────────────────────

def test_profile_py_exists(repo_root) -> None:
    assert (REPO_ROOT / "src/superharness/engine/profile.py").exists()


# ── reads fields from profile.yaml ───────────────────────────────────────────

def test_profile_reads_autonomy(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="autonomous")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "autonomy")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "autonomous"


def test_profile_reads_supervised(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "autonomy")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "supervised"


def test_profile_reads_primary_agent(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", primary_agent="codex-cli")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "primary_agent")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "codex-cli"


def test_profile_reads_team_size(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", team_size="small")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "team_size")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "small"


def test_profile_reads_team_size_team(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", team_size="team")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "team_size")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "team"


# ── defaults when profile.yaml missing ───────────────────────────────────────

def test_profile_default_autonomy_when_no_profile(repo_root, tmp_path) -> None:
    result = _run_profile(tmp_path, "--project", str(tmp_path), "autonomy")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "approval-gated"


def test_profile_default_primary_agent_when_no_profile(repo_root, tmp_path) -> None:
    result = _run_profile(tmp_path, "--project", str(tmp_path), "primary_agent")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_profile_default_team_size_when_no_profile(repo_root, tmp_path) -> None:
    result = _run_profile(tmp_path, "--project", str(tmp_path), "team_size")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "solo"


# ── defaults when field missing from profile ─────────────────────────────────

def test_profile_default_autonomy_when_field_missing(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", team_size="small")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "autonomy")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "approval-gated"


def test_profile_default_primary_agent_when_field_missing(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "primary_agent")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_profile_default_team_size_when_field_missing(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "team_size")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "solo"


# ── unknown field returns empty string ────────────────────────────────────────

def test_profile_unknown_field_returns_empty(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = _run_profile(tmp_path, "--project", str(tmp_path), "nonexistent_field")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
