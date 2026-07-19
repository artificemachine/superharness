"""Claude Code harness adapter.

Reproduces (byte-for-byte, proven by tests/unit/test_harness_registry.py::
test_claude_invocation_parity) the argv delegate.py's `_launch_agent()` used
to build inline for target="claude-code", before this adapter existed.

env is intentionally {} — the legacy path never built a bespoke env dict for
claude-code either; the subprocess simply inherits the parent process
environment (see platform_runtime.launch_agent, which has no env parameter).

See docs/PLAN-steal-omnigent.md iteration 5.
"""
from __future__ import annotations

from pathlib import Path

from superharness.harnesses.base import Invocation


class ClaudeHarness:
    name = "claude-code"

    def build_invocation(
        self, task: dict, project_dir: str, non_interactive: bool
    ) -> Invocation:
        from superharness.engine.adapter_registry import resolve_launcher

        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        launcher = resolve_launcher("claude-code", scripts_dir)

        prompt = str(task.get("prompt", ""))
        model = str(task.get("model") or "")
        effort = str(task.get("effort") or "")
        yolo = bool(task.get("yolo", False))
        codex_bypass = bool(task.get("codex_bypass", False))

        argv: list[str] = ["bash", launcher, "--project", project_dir, "--prompt", prompt]
        if non_interactive:
            argv.append("--non-interactive")
        if yolo:
            argv.append("--yolo")
        if codex_bypass:
            argv.append("--codex-bypass")
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]

        return Invocation(argv=tuple(argv), env={}, cwd=project_dir)
