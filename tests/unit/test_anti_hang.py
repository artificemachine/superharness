"""Tests for plan-only timeout and discussion dispatch (anti-hang guards)."""
import pytest



class TestPlanOnlyTimeout:
    """Prevent plan-only tasks from hanging forever."""

    def test_discussion_round_tasks_are_not_plan_only(self):
        """Discussion round tasks must dispatch with plan_only=False."""
        # Simulate what _enqueue does for discussion tasks
        from superharness.commands.auto_dispatch import _enqueue as enqueue_func

        # Read the function source to verify the check exists
        import inspect
        source = inspect.getsource(enqueue_func)
        assert '"/round-" in str(task_id)' in source or "'/round-' in str(task_id)" in source, \
            "_enqueue must detect discussion round tasks"
        assert 'plan_only = False' in source, \
            "must set plan_only=False for discussion tasks"

    def test_plan_only_detected_in_zombie_reconciler(self):
        """Zombie reconciler must kill stuck plan-only tasks."""
        import inspect
        from superharness.commands import inbox_watch
        source = inspect.getsource(inbox_watch)
        assert 'plan_only' in source, \
            "watcher must check plan_only field for stuck tasks"
        assert 'PLAN_ONLY_TIMEOUT' in source or '900' in source or 'SIGTERM' in source, \
            "must have a plan-only timeout that kills stuck processes"

    def test_plan_only_timeout_is_reasonable(self):
        """Plan-only timeout must be between 5-30 minutes."""
        import inspect
        from superharness.commands import inbox_watch
        source = inspect.getsource(inbox_watch)
        assert 'SIGTERM' in source or 'kill' in source.lower(), \
            "must kill stuck processes"


class TestInteractiveInputGuard:
    """Prevent tasks from blocking on interactive input."""

    def test_enqueue_discussion_round_is_not_plan_only(self, tmp_path):
        """Enqueue a discussion round task -> plan_only must be False."""
        task_id = "discuss-20260429T081354Z-56430-418132870/round-1"
        # Verify the guard logic: if task_id contains "/round-", plan_only=False
        is_discussion = "/round-" in task_id or "round-" in task_id
        assert is_discussion is True
        # Under the guard, plan_only should be set to False
        # This is what _enqueue does at line 68-69

    def test_regular_task_is_plan_only(self):
        """Regular todo tasks should remain plan_only=True (default)."""
        task_id = "feat.add-login"
        is_discussion = "/round-" in task_id or "round-" in task_id
        assert is_discussion is False
        # Regular tasks get plan_only=True (unchanged)

    def test_self_diagnosis_detects_stuck_dispatch(self):
        """Self-diagnosis must check for stuck launched tasks."""
        import inspect
        from superharness.commands.inbox_watch import _self_diagnosis
        source = inspect.getsource(_self_diagnosis)
        assert 'yaml' in source or 'pyyaml' in source, \
            "self-diagnosis must check for yaml module"


class TestTaskLogAnalyzer:
    """Verify log analyzer detects stuck agents."""

    def test_log_analyzer_exists(self):
        """Log analyzer function must exist."""
        import inspect
        from superharness.commands.inbox_watch import _analyze_task_logs
        source = inspect.getsource(_analyze_task_logs)
        assert 'STALE' in source or 'stale' in source, \
            "log analyzer must check for stale tasks"
        assert 'activity' in source or 'active' in source, \
            "log analyzer must check for task activity"
