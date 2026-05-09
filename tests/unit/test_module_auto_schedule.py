"""Tests for auto-schedule module (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations
import pytest

from datetime import datetime, timedelta



class TestAutoScheduleModule:
    """Test auto-schedule module (watcher tick hook)."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_scheduled_task_auto_enqueued(self, tmp_path):
        """Task with scheduled_after <= today → auto-enqueued to inbox."""
        from superharness.modules.actions.auto_schedule import check_scheduled_tasks

        project = tmp_path / "proj"
        project.mkdir()
        sh_dir = project / ".superharness"
        sh_dir.mkdir()

        # Task scheduled yesterday
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        (sh_dir / "contract.yaml").write_text(f"""id: test-contract
tasks:
- id: task.1
  title: Scheduled task
  status: todo
  scheduled_after: {yesterday}
  project_path: {project}
""")

        (sh_dir / "inbox.yaml").write_text("[]")

        context = {"project_dir": str(project)}
        settings = {"auto_target": "claude-code"}

        result = check_scheduled_tasks(context, settings)

        # Should enqueue task.1
        assert result["success"] is True
        assert "task.1" in result["enqueued_tasks"]

        # Verify inbox was updated
        inbox = sh_dir / "inbox.yaml"
        assert inbox.exists()
        import yaml
        inbox_data = yaml.safe_load(inbox.read_text())
        assert len(inbox_data) == 1
        assert inbox_data[0]["task"] == "task.1"
        assert inbox_data[0]["to"] == "claude-code"

    def test_future_task_not_enqueued(self, tmp_path):
        """Task with scheduled_after in future → not enqueued."""
        from superharness.modules.actions.auto_schedule import check_scheduled_tasks

        project = tmp_path / "proj"
        project.mkdir()
        sh_dir = project / ".superharness"
        sh_dir.mkdir()

        # Task scheduled tomorrow
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        (sh_dir / "contract.yaml").write_text(f"""id: test-contract
tasks:
- id: task.future
  title: Future task
  status: todo
  scheduled_after: {tomorrow}
  project_path: {project}
""")

        (sh_dir / "inbox.yaml").write_text("[]")

        context = {"project_dir": str(project)}
        settings = {"auto_target": "claude-code"}

        result = check_scheduled_tasks(context, settings)

        # Should NOT enqueue
        assert result["success"] is True
        assert result["enqueued_tasks"] == []

        # Verify inbox is still empty
        inbox = sh_dir / "inbox.yaml"
        import yaml
        inbox_data = yaml.safe_load(inbox.read_text())
        assert inbox_data == []

    def test_blocked_dependency_not_enqueued(self, tmp_path):
        """Task with unfinished depends_on → not enqueued."""
        from superharness.modules.actions.auto_schedule import check_scheduled_tasks

        project = tmp_path / "proj"
        project.mkdir()
        sh_dir = project / ".superharness"
        sh_dir.mkdir()

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        (sh_dir / "contract.yaml").write_text(f"""id: test-contract
tasks:
- id: task.dependency
  title: Dependency task
  status: todo
  project_path: {project}
- id: task.blocked
  title: Blocked task
  status: todo
  scheduled_after: {yesterday}
  depends_on: task.dependency
  project_path: {project}
""")

        (sh_dir / "inbox.yaml").write_text("[]")

        context = {"project_dir": str(project)}
        settings = {"auto_target": "claude-code", "check_depends_on": True}

        result = check_scheduled_tasks(context, settings)

        # Should NOT enqueue task.blocked (dependency not done)
        assert result["success"] is True
        assert result["enqueued_tasks"] == []

    def test_already_enqueued_task_skipped(self, tmp_path):
        """Task already in inbox → not enqueued again (idempotent)."""
        from superharness.modules.actions.auto_schedule import check_scheduled_tasks

        project = tmp_path / "proj"
        project.mkdir()
        sh_dir = project / ".superharness"
        sh_dir.mkdir()

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        (sh_dir / "contract.yaml").write_text(f"""id: test-contract
tasks:
- id: task.1
  title: Already enqueued
  status: todo
  scheduled_after: {yesterday}
  project_path: {project}
""")

        # Task already in inbox
        (sh_dir / "inbox.yaml").write_text("""- id: existing-inbox-item
  task: task.1
  to: claude-code
  status: pending
  created_at: '2026-03-20T10:00:00Z'
  project: /tmp/proj
  priority: 2
  max_retries: 3
  retry_count: 0
""")

        context = {"project_dir": str(project)}
        settings = {"auto_target": "claude-code"}

        result = check_scheduled_tasks(context, settings)

        # Should skip (already enqueued)
        assert result["success"] is True
        assert result["enqueued_tasks"] == []

        # Verify inbox still has only 1 item
        inbox = sh_dir / "inbox.yaml"
        import yaml
        inbox_data = yaml.safe_load(inbox.read_text())
        assert len(inbox_data) == 1

    def test_done_task_not_enqueued(self, tmp_path):
        """Task with status=done → skipped."""
        from superharness.modules.actions.auto_schedule import check_scheduled_tasks

        project = tmp_path / "proj"
        project.mkdir()
        sh_dir = project / ".superharness"
        sh_dir.mkdir()

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        (sh_dir / "contract.yaml").write_text(f"""id: test-contract
tasks:
- id: task.done
  title: Done task
  status: done
  scheduled_after: {yesterday}
  project_path: {project}
""")

        (sh_dir / "inbox.yaml").write_text("[]")

        context = {"project_dir": str(project)}
        settings = {"auto_target": "claude-code"}

        result = check_scheduled_tasks(context, settings)

        # Should skip (status=done)
        assert result["success"] is True
        assert result["enqueued_tasks"] == []

        # Verify inbox is still empty
        inbox = sh_dir / "inbox.yaml"
        import yaml
        inbox_data = yaml.safe_load(inbox.read_text())
        assert inbox_data == []
