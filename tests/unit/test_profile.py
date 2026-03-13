from __future__ import annotations

"""Tests for engine/profile.rb — Phase 1c"""

import stat


from tests.helpers import run_cmd, REPO_ROOT


PROFILE_RB = REPO_ROOT / "engine" / "profile.rb"


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

def test_profile_rb_exists(repo_root) -> None:
    assert PROFILE_RB.exists(), "engine/profile.rb not found"


def test_profile_rb_is_executable(repo_root) -> None:
    assert PROFILE_RB.stat().st_mode & stat.S_IXUSR, "engine/profile.rb is not executable"


# ── reads fields from profile.yaml ───────────────────────────────────────────

def test_profile_reads_autonomy(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="autonomous")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "autonomy"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "autonomous"


def test_profile_reads_supervised(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "autonomy"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "supervised"


def test_profile_reads_primary_agent(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", primary_agent="codex-cli")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "primary_agent"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "codex-cli"


def test_profile_reads_team_size(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", team_size="small")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "team_size"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "small"


def test_profile_reads_team_size_team(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", team_size="team")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "team_size"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "team"


# ── defaults when profile.yaml missing ───────────────────────────────────────

def test_profile_default_autonomy_when_no_profile(repo_root, tmp_path) -> None:
    # No .superharness/profile.yaml created
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "autonomy"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "approval-gated"


def test_profile_default_primary_agent_when_no_profile(repo_root, tmp_path) -> None:
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "primary_agent"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_profile_default_team_size_when_no_profile(repo_root, tmp_path) -> None:
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "team_size"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "solo"


# ── defaults when field missing from profile ─────────────────────────────────

def test_profile_default_autonomy_when_field_missing(repo_root, tmp_path) -> None:
    # Write profile without autonomy key
    _write_profile(tmp_path / ".superharness", team_size="small")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "autonomy"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "approval-gated"


def test_profile_default_primary_agent_when_field_missing(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "primary_agent"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_profile_default_team_size_when_field_missing(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "team_size"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "solo"


# ── unknown field returns empty string ────────────────────────────────────────

def test_profile_unknown_field_returns_empty(repo_root, tmp_path) -> None:
    _write_profile(tmp_path / ".superharness", autonomy="supervised")
    result = run_cmd(
        ["ruby", str(PROFILE_RB), "--project", str(tmp_path), "nonexistent_field"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
