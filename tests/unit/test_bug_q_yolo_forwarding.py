"""Regression tests for Bug Q — --yolo flag not forwarded to launcher script.

Root cause: `--yolo` was parsed by delegate.py's argparser but never passed to
`_launch_agent()`, so `delegate-to-gemini.sh` never received `-y --skip-trust`.
Discussion-round submissions therefore stayed permanently unauthorized.

Fix: thread `yolo: bool = False` through:
  _launch_agent() signature + launch_args build
  → delegate() signature
  → both CLI call sites (JSON mode + normal mode)
"""
from __future__ import annotations

import ast
import inspect
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Structural checks — verify the fix is wired at all levels
# ---------------------------------------------------------------------------

class TestStructural_YoloInLaunchAgent:
    def test_launch_agent_has_yolo_parameter(self):
        """`_launch_agent` must accept a `yolo` keyword argument."""
        from superharness.commands import delegate as _mod
        sig = inspect.signature(_mod._launch_agent)
        assert "yolo" in sig.parameters, (
            "_launch_agent() missing `yolo` parameter — Bug Q regression"
        )

    def test_launch_agent_appends_yolo_to_launch_args(self):
        """`--yolo` must be added to argv when yolo=True.

        Updated by docs/PLAN-steal-omnigent.md iteration 6: `_launch_agent`
        now delegates argv construction to the harness registry
        (superharness.harnesses) instead of building it inline, so the
        `if yolo: argv.append("--yolo")` shape now lives in
        harnesses.base.build_generic_invocation (codex/gemini/opencode) and
        harnesses.claude.ClaudeHarness.build_invocation (claude-code) rather
        than in `_launch_agent` itself. The forwarding behavior itself is
        unchanged and still covered end-to-end by
        TestBehavioural_LaunchArgsContainYolo below and by
        tests/unit/test_harness_adapters.py's golden parity tests.
        """
        import superharness.harnesses.base as _base_mod
        import superharness.harnesses.claude as _claude_mod

        def _has_yolo_append(src: str) -> bool:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test = node.test
                    if isinstance(test, ast.Name) and test.id == "yolo":
                        for body_node in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                            if isinstance(body_node, ast.Constant) and body_node.value == "--yolo":
                                return True
            return False

        found = _has_yolo_append(inspect.getsource(_base_mod.build_generic_invocation)) or \
            _has_yolo_append(inspect.getsource(_claude_mod.ClaudeHarness.build_invocation))
        assert found, (
            "no harness adapter appends '--yolo' to argv when yolo=True"
        )

    def test_delegate_function_has_yolo_parameter(self):
        """`delegate()` must accept a `yolo` keyword argument."""
        from superharness.commands.delegate import delegate
        sig = inspect.signature(delegate)
        assert "yolo" in sig.parameters, (
            "delegate() missing `yolo` parameter — Bug Q regression"
        )


class TestStructural_YoloPropagation:
    def _get_delegate_source(self):
        from superharness.commands import delegate as _mod
        return inspect.getsource(_mod.delegate)

    def test_delegate_passes_yolo_to_launch_agent(self):
        """`delegate()` must pass `yolo=yolo` to `_launch_agent()`."""
        src = self._get_delegate_source()
        tree = ast.parse(src)

        yolo_kwargs_at_call_sites = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                func_name = ""
                if isinstance(func, ast.Attribute):
                    func_name = func.attr
                elif isinstance(func, ast.Name):
                    func_name = func.id
                if func_name == "_launch_agent":
                    for kw in node.keywords:
                        if kw.arg == "yolo":
                            yolo_kwargs_at_call_sites.append(node)

        assert len(yolo_kwargs_at_call_sites) >= 2, (
            f"delegate() only passes yolo= to {len(yolo_kwargs_at_call_sites)} "
            "of 2 expected _launch_agent() call sites"
        )

    def test_cli_entrypoint_passes_yolo_to_delegate(self):
        """`opts.yolo` must be forwarded to both `delegate()` CLI call sites."""
        from superharness.commands import delegate as _mod
        src = inspect.getsource(_mod)
        tree = ast.parse(src)

        delegate_call_yolo_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                func_name = ""
                if isinstance(func, ast.Name):
                    func_name = func.id
                if func_name == "delegate":
                    for kw in node.keywords:
                        if kw.arg == "yolo":
                            delegate_call_yolo_count += 1

        assert delegate_call_yolo_count >= 2, (
            f"Only {delegate_call_yolo_count} of 2 expected `delegate()` call "
            "sites pass `yolo=opts.yolo`"
        )


# ---------------------------------------------------------------------------
# Behavioural check — launch_args actually contains --yolo
# ---------------------------------------------------------------------------

class TestBehavioural_LaunchArgsContainYolo:
    def _run_launch_agent(self, tmp_path, yolo: bool) -> list:
        from superharness.commands import delegate as _mod
        captured_args: list = []

        try:
            with (
                patch("superharness.engine.adapter_registry.resolve_launcher",
                      return_value="/fake/delegate-to-gemini.sh"),
                patch("superharness.engine.platform_runtime.launch_agent",
                      side_effect=lambda args, **_kw: captured_args.extend(args) or 0),
                patch("superharness.engine.platform_runtime.expand_agent_path"),
                patch("superharness.logging_utils.get_logger", return_value=MagicMock()),
                patch("superharness.logging_utils.get_audit_logger",
                      return_value=MagicMock()),
                patch("superharness.logging_utils.redact", side_effect=lambda s: s),
                patch("superharness.utils.model_routing.apply_model_prefix",
                      side_effect=lambda m: m),
            ):
                _mod._launch_agent(
                    target="gemini-cli",
                    prompt="test",
                    project_dir=str(tmp_path),
                    non_interactive=True,
                    codex_bypass=False,
                    yolo=yolo,
                )
        except SystemExit:
            pass  # _launch_agent always sys.exit()s after launch_agent()

        return captured_args

    def test_yolo_flag_ends_up_in_launch_args(self, tmp_path):
        """`_launch_agent(..., yolo=True)` must include '--yolo' in the shell args."""
        args = self._run_launch_agent(tmp_path, yolo=True)
        assert "--yolo" in args, (
            f"'--yolo' missing from launch_args: {args}"
        )

    def test_no_yolo_flag_absent_from_launch_args(self, tmp_path):
        """When yolo=False, '--yolo' must NOT appear in launch_args."""
        args = self._run_launch_agent(tmp_path, yolo=False)
        assert "--yolo" not in args, (
            f"'--yolo' unexpectedly in launch_args: {args}"
        )
