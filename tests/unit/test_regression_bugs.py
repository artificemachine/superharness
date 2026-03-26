"""Regression tests for bugs found during 2026-03-20 session.

Each test reproduces a specific bug that was discovered and fixed.
If any of these fail, the bug has regressed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_monitor_module(repo_root: Path):
    script = repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Bug 1: Missing Path import in delegate.py
# NameError: name 'Path' is not defined at line 566
# Caused ALL dispatched tasks to fail.
# ---------------------------------------------------------------------------

class TestBug1_DelegatePathImport:
    def test_delegate_module_imports_path(self):
        """delegate.py must import Path — missing import crashed all dispatches."""
        from superharness.commands import delegate
        # The bug was os.execvp never reached because Path() threw NameError
        assert hasattr(delegate, "Path") or "Path" in dir(delegate)

    def test_delegate_reads_instructions_file(self, tmp_path):
        """delegate reads {task_id}-instructions.md without NameError."""
        from superharness.commands.delegate import Path as _P
        instructions_file = tmp_path / "test-instructions.md"
        instructions_file.write_text("TDD instructions here")
        # This line was the exact crash point
        result = _P(instructions_file).read_text(encoding="utf-8").strip()
        assert result == "TDD instructions here"


# ---------------------------------------------------------------------------
# Bug 2: CSS --fg variable undefined in monitor modal
# Modal text invisible on dark theme (color:var(--fg) resolved to nothing).
# ---------------------------------------------------------------------------

class TestBug2_CssVariable:
    def test_modal_uses_text_variable_not_fg(self, repo_root):
        """Monitor HTML must use var(--text) not var(--fg) for modal colors."""
        module = _load_monitor_module(repo_root)
        html = module.HTML
        assert "var(--fg)" not in html, "var(--fg) is undefined — use var(--text)"
        assert "var(--text)" in html


# ---------------------------------------------------------------------------
# Bug 3: codex-cli prompt drops user instructions
# Instructions from Enqueue modal silently ignored for codex-cli targets.
# ---------------------------------------------------------------------------

class TestBug3_CodexInstructions:
    def test_codex_prompt_branches_include_user_instructions(self, repo_root):
        """Both codex-cli prompt branches must include {user_instructions}."""
        source = (repo_root / "src" / "superharness" / "commands" / "delegate.py").read_text()
        # Find the codex prompt construction (in the delegate function, not _launch_agent)
        # Both branches: with latest_handoff and without
        # Count occurrences of user_instructions in prompt assignments after the codex-cli comment
        # The prompt is built before _launch_agent is called
        codex_prompt_section = source[source.find("else:  # codex-cli"):source.find("# Enrich prompt with vault")]
        assert codex_prompt_section.count("user_instructions") >= 2, \
            "Both codex-cli prompt branches must include {user_instructions}"


# ---------------------------------------------------------------------------
# Bug 4: Duplicate enqueue not blocked for paused items
# Paused inbox items bypassed the duplicate guard, allowing double enqueue.
# ---------------------------------------------------------------------------

class TestBug4_PausedDuplicateGuard:
    def test_active_statuses_include_paused(self, repo_root):
        """The enqueue duplicate guard must check paused status too."""
        source = (repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py").read_text()
        # Find the Python backend handler (not the JS)
        idx = source.find("Block duplicate: reject if task already has an active")
        assert idx > 0, "Duplicate guard comment not found"
        guard_section = source[idx:idx + 300]
        assert "paused" in guard_section, \
            "Enqueue guard must block paused items"


# ---------------------------------------------------------------------------
# Bug 5: Missing mkdir before instructions file write
# write_text() crashed with FileNotFoundError if handoffs/ dir missing.
# ---------------------------------------------------------------------------

class TestBug5_MkdirBeforeWrite:
    def test_instructions_write_creates_parent_dir(self, repo_root):
        """Monitor must mkdir before writing instructions file."""
        source = (repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py").read_text()
        # Find instructions file write
        idx = source.find("instructions_file.write_text")
        assert idx > 0
        # Check mkdir exists within 200 chars before the write
        preceding = source[max(0, idx - 200):idx]
        assert "mkdir" in preceding, \
            "Must mkdir(parents=True) before instructions_file.write_text()"


# ---------------------------------------------------------------------------
# Bug 6: task_report skips .md handoffs without YAML frontmatter
# Agents wrote handoffs as plain markdown (no ---). Reports showed empty.
# ---------------------------------------------------------------------------

class TestBug6_MdWithoutFrontmatter:
    def test_task_report_reads_md_without_frontmatter(self, repo_root, tmp_path):
        """task_report must show content from .md files even without --- frontmatter."""
        module = _load_monitor_module(repo_root)
        project = tmp_path / "proj"
        harness = project / ".superharness"
        (harness / "handoffs").mkdir(parents=True)
        (harness / "contract.yaml").write_text(
            "id: c1\ntasks:\n- id: task-1\n  status: done\n  title: Test\n  owner: claude-code\n"
        )
        # Handoff with NO frontmatter (just plain markdown)
        (harness / "handoffs" / "task-1-report.md").write_text(
            "# Task Handoff: task-1\n\n**Status:** DONE\n\nCompleted all work.\n"
        )

        result = module.task_report(project, "task-1", "claude-code")
        assert result.get("markdown_report"), \
            "task_report must return content from .md files without frontmatter"
        assert "Completed all work" in result["markdown_report"]


# ---------------------------------------------------------------------------
# Bug 7: task_report only matches task:/task_id: YAML fields
# Handoffs with task ID only in filename (not in content) were missed.
# ---------------------------------------------------------------------------

class TestBug7_FilenameMatching:
    def test_task_report_matches_by_filename(self, repo_root, tmp_path):
        """task_report must match handoffs by filename when content has no task: field."""
        module = _load_monitor_module(repo_root)
        project = tmp_path / "proj"
        harness = project / ".superharness"
        (harness / "handoffs").mkdir(parents=True)
        (harness / "contract.yaml").write_text(
            "id: c1\ntasks:\n- id: my-task\n  status: done\n  title: Test\n  owner: claude-code\n"
        )
        # Handoff has task ID in filename but NOT in content
        (harness / "handoffs" / "my-task-2026-03-20-claude-code.md").write_text(
            "# Handoff Report\n\nDid the thing successfully.\n"
        )

        result = module.task_report(project, "my-task", "claude-code")
        assert result.get("markdown_report"), \
            "task_report must match by filename prefix"
        assert "successfully" in result["markdown_report"]

    def test_instructions_file_not_matched_as_report(self, repo_root, tmp_path):
        """Instructions files must NOT be returned as task reports."""
        module = _load_monitor_module(repo_root)
        project = tmp_path / "proj"
        harness = project / ".superharness"
        (harness / "handoffs").mkdir(parents=True)
        (harness / "contract.yaml").write_text(
            "id: c1\ntasks:\n- id: my-task\n  status: todo\n  title: Test\n  owner: claude-code\n"
        )
        (harness / "handoffs" / "my-task-instructions.md").write_text(
            "TDD instructions for this task.\n"
        )

        result = module.task_report(project, "my-task", "claude-code")
        assert not result.get("markdown_report"), \
            "Instructions files should not appear as task reports"


# ---------------------------------------------------------------------------
# Bug 8: Zombie inbox items never reconciled
# Launched items with dead process stayed as "launched" forever.
# ---------------------------------------------------------------------------

class TestBug8_ZombieReconciliation:
    def test_contract_done_zombie_reconciled(self, tmp_path):
        """Launched item + contract done → must be marked done."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        harness = project / ".superharness"
        harness.mkdir(parents=True)
        yaml.dump({"id": "c1", "tasks": [{"id": "t1", "status": "done"}]},
                  open(harness / "contract.yaml", "w"))
        with open(harness / "inbox.yaml", "w") as f:
            f.write("- id: z1\n  task: t1\n  to: claude-code\n  status: launched\n  launched_at: '2026-01-01T00:00:00Z'\n")

        count = _reconcile_zombies(str(project))
        assert count == 1
        items = yaml.safe_load(open(harness / "inbox.yaml"))
        assert items[0]["status"] == "done"

    def test_dead_pid_zombie_reconciled(self, tmp_path):
        """Launched item + dead PID → must be marked failed."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        harness = project / ".superharness"
        harness.mkdir(parents=True)
        yaml.dump({"id": "c1", "tasks": [{"id": "t1", "status": "todo"}]},
                  open(harness / "contract.yaml", "w"))
        with open(harness / "inbox.yaml", "w") as f:
            f.write("- id: z1\n  task: t1\n  to: claude-code\n  status: launched\n  pid: '999999'\n  launched_at: '2026-01-01T00:00:00Z'\n")

        count = _reconcile_zombies(str(project))
        assert count == 1
        items = yaml.safe_load(open(harness / "inbox.yaml"))
        assert items[0]["status"] == "failed"


# ---------------------------------------------------------------------------
# Bug 9: task_report endpoint crashes drop connection
# Unhandled exception in task_report() returned no HTTP response.
# Browser showed "TypeError: Failed to fetch".
# ---------------------------------------------------------------------------

class TestBug9_TaskReportCrashHandling:
    def test_task_report_crash_returns_500(self, repo_root):
        """task_report must be wrapped in try/except — crash returns 500 JSON, not dropped connection."""
        source = (repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py").read_text()
        idx = source.find("task_report(self.project_dir, task_id, agent)")
        assert idx > 0
        surrounding = source[max(0, idx - 100):idx + 200]
        assert "except" in surrounding, \
            "task_report call must be wrapped in try/except"
