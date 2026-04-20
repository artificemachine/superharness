"""Unit tests for engine/subtask.py — status resolver + lookup."""
from __future__ import annotations

from superharness.engine.subtask import (
    find_task_or_subtask,
    iter_all_tasks,
    resolve_subtask_status,
)


class TestResolveSubtaskStatus:
    def test_explicit_done_wins_over_pending_parent(self):
        sub = {"id": "x.1", "status": "done"}
        assert resolve_subtask_status(sub, "in_progress") == "done"

    def test_pending_subtask_inherits_from_done_parent(self):
        sub = {"id": "x.1", "status": "pending"}
        assert resolve_subtask_status(sub, "done") == "done"

    def test_missing_status_inherits_from_done_parent(self):
        sub = {"id": "x.1"}
        assert resolve_subtask_status(sub, "done") == "done"

    def test_pending_with_non_done_parent_stays_pending(self):
        sub = {"id": "x.1", "status": "pending"}
        assert resolve_subtask_status(sub, "in_progress") == "pending"

    def test_missing_status_with_non_done_parent_is_pending(self):
        sub = {"id": "x.1"}
        assert resolve_subtask_status(sub, "todo") == "pending"

    def test_review_passed_parent_treated_as_done(self):
        sub = {"id": "x.1"}
        assert resolve_subtask_status(sub, "review_passed") == "done"

    def test_explicit_in_progress_not_overridden_by_done_parent(self):
        # Defensive: if a subtask is explicitly marked in_progress and somehow
        # the parent is done, prefer the explicit signal.
        sub = {"id": "x.1", "status": "in_progress"}
        assert resolve_subtask_status(sub, "done") == "in_progress"

    def test_none_subtask_returns_pending(self):
        assert resolve_subtask_status(None, "done") == "pending"

    def test_none_parent_returns_pending_for_pending_subtask(self):
        assert resolve_subtask_status({"status": "pending"}, None) == "pending"


class TestFindTaskOrSubtask:
    @staticmethod
    def _contract():
        return {
            "tasks": [
                {
                    "id": "parent-a",
                    "title": "Parent A",
                    "status": "done",
                    "subtasks": [
                        {"id": "parent-a.1", "title": "Sub A1", "status": "pending"},
                        {"id": "parent-a.2", "title": "Sub A2", "status": "pending"},
                    ],
                },
                {
                    "id": "parent-b",
                    "title": "Parent B",
                    "status": "in_progress",
                    "subtasks": [],
                },
            ]
        }

    def test_top_level_lookup(self):
        task, parent = find_task_or_subtask(self._contract(), "parent-a")
        assert task is not None and task["id"] == "parent-a"
        assert parent is None

    def test_subtask_lookup_returns_parent(self):
        task, parent = find_task_or_subtask(self._contract(), "parent-a.1")
        assert task is not None and task["id"] == "parent-a.1"
        assert parent is not None and parent["id"] == "parent-a"

    def test_missing_id_returns_none_none(self):
        task, parent = find_task_or_subtask(self._contract(), "does-not-exist")
        assert task is None and parent is None

    def test_empty_contract(self):
        task, parent = find_task_or_subtask({}, "anything")
        assert task is None and parent is None


class TestIterAllTasks:
    def test_yields_tasks_and_subtasks_with_effective_status(self):
        contract = {
            "tasks": [
                {
                    "id": "p",
                    "status": "done",
                    "subtasks": [
                        {"id": "p.1", "title": "s1", "status": "pending"},
                    ],
                }
            ]
        }
        items = list(iter_all_tasks(contract))
        assert len(items) == 2
        assert items[0]["id"] == "p"
        assert items[1]["id"] == "p.1"
        assert items[1]["_parent_id"] == "p"
        assert items[1]["_effective_status"] == "done"  # inherited

    def test_empty_contract_yields_nothing(self):
        assert list(iter_all_tasks({})) == []
