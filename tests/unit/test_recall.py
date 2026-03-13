"""
Tests for engine/recall.rb — keyword search over handoffs and ledger.

Multi-keyword logic: OR — any term matching in a file produces a result.
This is documented here as the canonical choice.
"""
from __future__ import annotations

import stat
import textwrap
from datetime import date, timedelta


from tests.helpers import run_cmd, REPO_ROOT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RECALL_RB = str(REPO_ROOT / "engine/recall.rb")
SUPERHARNESS = str(REPO_ROOT / "superharness")


def _make_project(tmp_path, handoffs: list[dict], ledger_lines: list[str] | None = None):
    """
    Create a minimal .superharness layout in tmp_path.
    handoffs: list of dicts with keys: filename, content (yaml string)
    ledger_lines: list of lines to write to ledger.md
    """
    sh = tmp_path / ".superharness"
    sh.mkdir()
    hdir = sh / "handoffs"
    hdir.mkdir()

    for h in handoffs:
        (hdir / h["filename"]).write_text(h["content"])

    ledger = sh / "ledger.md"
    lines = ledger_lines or []
    ledger.write_text("# Ledger\n" + "\n".join(lines) + "\n")

    return tmp_path


# ---------------------------------------------------------------------------
# 1. recall.rb is executable
# ---------------------------------------------------------------------------

def test_recall_script_is_executable(repo_root) -> None:
    script = repo_root / "engine/recall.rb"
    assert script.exists(), "engine/recall.rb not found"
    assert script.stat().st_mode & stat.S_IXUSR, "engine/recall.rb is not executable"


# ---------------------------------------------------------------------------
# 2. --help exits 0 and mentions "Usage"
# ---------------------------------------------------------------------------

def test_recall_help(repo_root, tmp_path) -> None:
    result = run_cmd(["ruby", RECALL_RB, "--help"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Usage" in result.stdout or "usage" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 3. Returns matching result for keyword in handoff YAML
# ---------------------------------------------------------------------------

def test_recall_matches_handoff_yaml(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, handoffs=[
        {
            "filename": "2026-03-10-auth-fix.yaml",
            "content": textwrap.dedent("""\
                task: auth-fix
                agent: claude-code
                date: "2026-03-10"
                status: done
                summary: |
                  Fixed authentication token refresh bug
            """),
        }
    ])
    result = run_cmd(
        ["ruby", RECALL_RB, "--project", str(project), "authentication"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "authentication" in result.stdout.lower()
    assert "auth-fix" in result.stdout or "2026-03-10" in result.stdout


# ---------------------------------------------------------------------------
# 4. Returns matching result for keyword in ledger.md
# ---------------------------------------------------------------------------

def test_recall_matches_ledger(repo_root, tmp_path) -> None:
    project = _make_project(
        tmp_path,
        handoffs=[],
        ledger_lines=[
            "- 2026-03-11T10:00:00Z — claude-code — completed database migration task",
            "- 2026-03-11T11:00:00Z — codex-cli — reviewed pull request",
        ],
    )
    result = run_cmd(
        ["ruby", RECALL_RB, "--project", str(project), "migration"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "migration" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 5. Multiple keywords: OR logic — any match produces result
# ---------------------------------------------------------------------------

def test_recall_multiple_keywords_or_logic(repo_root, tmp_path) -> None:
    """OR logic: either 'deploy' or 'auth' should find matching files."""
    project = _make_project(tmp_path, handoffs=[
        {
            "filename": "2026-03-10-deploy-gate.yaml",
            "content": textwrap.dedent("""\
                task: deploy-gate
                agent: claude-code
                date: "2026-03-10"
                status: done
                summary: Added deployment gate check
            """),
        },
        {
            "filename": "2026-03-10-auth-module.yaml",
            "content": textwrap.dedent("""\
                task: auth-module
                agent: codex-cli
                date: "2026-03-10"
                status: done
                summary: Implemented auth module
            """),
        },
    ])
    result = run_cmd(
        ["ruby", RECALL_RB, "--project", str(project), "deploy", "auth"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    # Both files should appear since OR means each term can match different files
    assert "deploy" in result.stdout.lower() or "auth" in result.stdout.lower()
    # At least 2 result blocks (both files match one of the terms)
    lines = result.stdout.strip().splitlines()
    assert len(lines) >= 2, f"Expected at least 2 output lines, got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# 6. --since Nd excludes files older than N days
# ---------------------------------------------------------------------------

def test_recall_since_excludes_old_files(repo_root, tmp_path) -> None:
    today = date.today()
    recent_date = today.strftime("%Y-%m-%d")
    old_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")

    project = _make_project(tmp_path, handoffs=[
        {
            "filename": f"{recent_date}-new-feature.yaml",
            "content": textwrap.dedent(f"""\
                task: new-feature
                agent: claude-code
                date: "{recent_date}"
                status: done
                summary: Added caching layer
            """),
        },
        {
            "filename": f"{old_date}-old-feature.yaml",
            "content": textwrap.dedent(f"""\
                task: old-feature
                agent: codex-cli
                date: "{old_date}"
                status: done
                summary: Added caching layer
            """),
        },
    ])
    result = run_cmd(
        ["ruby", RECALL_RB, "--project", str(project), "--since", "7d", "caching"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    # Only recent file should appear
    assert "new-feature" in result.stdout
    assert "old-feature" not in result.stdout


# ---------------------------------------------------------------------------
# 7. No results → prints "(no results" and exits 0
# ---------------------------------------------------------------------------

def test_recall_no_results_exits_0(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, handoffs=[
        {
            "filename": "2026-03-10-some-task.yaml",
            "content": textwrap.dedent("""\
                task: some-task
                agent: claude-code
                date: "2026-03-10"
                status: done
                summary: Nothing relevant here
            """),
        }
    ])
    result = run_cmd(
        ["ruby", RECALL_RB, "--project", str(project), "xyzzy_nonexistent_keyword"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"Expected exit 0 for no results, got {result.returncode}"
    assert "(no results" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 8. Sorted by recency (newest date first)
# ---------------------------------------------------------------------------

def test_recall_sorted_by_recency(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, handoffs=[
        {
            "filename": "2026-01-01-old-task.yaml",
            "content": textwrap.dedent("""\
                task: old-task
                agent: claude-code
                date: "2026-01-01"
                status: done
                summary: deploy old version
            """),
        },
        {
            "filename": "2026-03-10-new-task.yaml",
            "content": textwrap.dedent("""\
                task: new-task
                agent: codex-cli
                date: "2026-03-10"
                status: done
                summary: deploy new version
            """),
        },
        {
            "filename": "2026-02-15-mid-task.yaml",
            "content": textwrap.dedent("""\
                task: mid-task
                agent: claude-code
                date: "2026-02-15"
                status: done
                summary: deploy mid version
            """),
        },
    ])
    result = run_cmd(
        ["ruby", RECALL_RB, "--project", str(project), "deploy"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    # newest (2026-03-10) should appear before oldest (2026-01-01)
    pos_new = stdout.find("2026-03-10")
    pos_mid = stdout.find("2026-02-15")
    pos_old = stdout.find("2026-01-01")
    assert pos_new != -1 and pos_mid != -1 and pos_old != -1, \
        f"Expected all dates in output:\n{stdout}"
    assert pos_new < pos_mid < pos_old, \
        f"Expected newest first, got positions new={pos_new}, mid={pos_mid}, old={pos_old}"


# ---------------------------------------------------------------------------
# 9. superharness recall --project . "keyword" works via CLI dispatcher
# ---------------------------------------------------------------------------

def test_recall_via_dispatcher(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, handoffs=[
        {
            "filename": "2026-03-10-watcher-fix.yaml",
            "content": textwrap.dedent("""\
                task: watcher-fix
                agent: claude-code
                date: "2026-03-10"
                status: done
                summary: Fixed watcher timeout issue
            """),
        }
    ])
    result = run_cmd(
        [SUPERHARNESS, "recall", "--project", str(project), "watcher"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"Dispatcher recall failed:\n{result.stderr}"
    assert "watcher" in result.stdout.lower()
