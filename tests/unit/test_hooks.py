"""Tests for event hook system (cherry-picked from hermes-agent)."""
import yaml
import pytest
from superharness.engine.hooks import HookRegistry, HookDef, get_registry, load_hooks_from_dir


class TestHooks:
    def test_register_and_fire_hook(self):
        calls = []
        def handler():
            calls.append(1)
        registry = HookRegistry()
        registry._execute_handler = lambda path, data: calls.append(path)
        registry.register("task:completed", HookDef(name="test", events=["task:completed"], handler_path="/test"))
        registry.fire("task:completed", {})
        assert len(calls) == 1

    def test_fire_event_no_handlers(self):
        registry = HookRegistry()
        registry.fire("nonexistent", {})  # should not raise

    def test_handler_error_doesnt_block(self, capsys):
        registry = HookRegistry()
        def fail(path, data):
            raise RuntimeError("fail")
        registry._execute_handler = fail
        registry.register("task:failed", HookDef(name="bad", events=["task:failed"], handler_path="/bad"))
        registry.fire("task:failed", {})  # should not raise

    def test_multiple_handlers_same_event(self):
        calls = []
        registry = HookRegistry()
        registry._execute_handler = lambda path, data: calls.append(path)
        registry.register("e", HookDef(name="a", events=["e"], handler_path="/a"))
        registry.register("e", HookDef(name="b", events=["e"], handler_path="/b"))
        registry.fire("e", {})
        assert len(calls) == 2

    def test_parse_hook_yaml(self, tmp_path):
        hooks_dir = tmp_path / ".superharness" / "hooks" / "myhook"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "HOOK.yaml").write_text("name: myhook\nevents:\n- task:completed\nhandler: handler.py\n")
        (hooks_dir / "handler.py").write_text("print('ok')\n")
        count = load_hooks_from_dir(str(tmp_path))
        assert count == 1

    def test_hook_yaml_missing_events(self, tmp_path):
        hooks_dir = tmp_path / ".superharness" / "hooks" / "myhook"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "HOOK.yaml").write_text("name: myhook\n")
        (hooks_dir / "handler.py").write_text("print('ok')\n")
        count = load_hooks_from_dir(str(tmp_path))
        assert count == 0
