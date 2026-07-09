"""Agent SDK runner — wrapper around claude_agent_sdk.

Uses query() for one-shot task dispatch and ClaudeSDKClient for
stateful sessions. Provides an alternative to subprocess calls
to the claude CLI.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _find_latest_session(project_dir: str) -> str | None:
    """Find the most recent Claude session ID for a project directory."""
    import glob
    safe_path = project_dir.replace("/", "-").replace("\\", "-").replace(":", "-")
    session_dir = os.path.join(
        os.path.expanduser("~"), ".claude", "projects", safe_path,
    )
    if not os.path.isdir(session_dir):
        return None
    candidates = sorted(
        glob.glob(os.path.join(session_dir, "*.jsonl")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    if not candidates:
        return None
    # Extract session ID from filename (UUID.jsonl)
    basename = os.path.basename(candidates[0])
    if basename.endswith(".jsonl"):
        return basename[:-6]  # strip .jsonl
    return None


def _start_jsonl_tailer(
    project_dir: str, log_handle: Any, poll_interval: float = 1.0,
) -> tuple[Any, Any]:
    """Tail the newest Claude session JSONL and pipe assistant text to log_handle.

    Returns (stop_event, thread) so caller can signal shutdown.
    """
    import glob
    import json
    import threading
    import time as _time

    stop = threading.Event()

    def _tail() -> None:
        # Find Claude project session dir
        safe_path = project_dir.replace("/", "-").replace("\\", "-").replace(":", "-")
        session_dir = os.path.join(
            os.path.expanduser("~"), ".claude", "projects", safe_path,
        )
        # Wait briefly for session file to appear
        jsonl_file = None
        for _ in range(10):
            if stop.is_set():
                return
            candidates = sorted(
                glob.glob(os.path.join(session_dir, "*.jsonl")),
                key=lambda p: os.path.getmtime(p),
                reverse=True,
            )
            if candidates:
                jsonl_file = candidates[0]
                break
            _time.sleep(1)
        if not jsonl_file:
            return

        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                # Seek to end — only tail new content
                f.seek(0, 2)
                while not stop.is_set():
                    line = f.readline()
                    if not line:
                        _time.sleep(poll_interval)
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    msg = d.get("message", {})
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                log_handle.write(text + "\n")
                                log_handle.flush()
                        elif isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "")
                            if name:
                                log_handle.write(f"[tool: {name}]\n")
                                log_handle.flush()
        except OSError:
            pass

    t = threading.Thread(target=_tail, daemon=True)
    t.start()
    return stop, t


class BudgetExceededError(Exception):
    """Raised when SDK runner exceeds max_budget_usd."""
    pass


from superharness.engine.config_loader import load_yaml_config

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8":      {"input": 5.00,  "output": 25.00},
    "claude-opus-4-8[1m]":  {"input": 5.00,  "output": 25.00},
    "claude-opus-4-7":      {"input": 5.00,  "output": 25.00},
    "claude-opus-4-7[1m]":  {"input": 5.00,  "output": 25.00},
    "claude-opus-4-6":      {"input": 5.00,  "output": 25.00},
    "claude-sonnet-4-6":    {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25},
    "flash":                {"input": 0.10,  "output": 0.40},
    "pro":                  {"input": 1.25,  "output": 5.00},
    "ultra":                {"input": 15.00, "output": 75.00},
}
# Keep private alias for backwards compat with internal callers
_MODEL_PRICING = MODEL_PRICING

_cached_pricing: dict[str, dict[str, float]] | None = None


def _load_pricing(project_dir: str | None = None) -> dict[str, dict[str, float]]:
    """Load pricing from bundled YAML or project override."""
    global _cached_pricing
    if _cached_pricing is not None and project_dir is None:
        return _cached_pricing

    config = load_yaml_config(
        bundled_pkg="superharness",
        bundled_filename="engine/models.yaml",
        project_dir=project_dir,
        project_filename="models.yaml",
        fallback={"pricing": MODEL_PRICING}
    )
    pricing = config.get("pricing", MODEL_PRICING)
    
    if project_dir is None:
        _cached_pricing = pricing
    return pricing


def _calculate_cost(model: str | None, input_tokens: int, output_tokens: int, project_dir: str | None = None) -> float:
    """Calculate cost in USD for given token usage."""
    pricing_map = _load_pricing(project_dir)
    pricing = pricing_map.get(model or "", pricing_map.get("claude-sonnet-4-6", MODEL_PRICING["claude-sonnet-4-6"]))
    return (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]


def _try_import_sdk() -> bool:
    """Check if claude_agent_sdk is available."""
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def sdk_available() -> bool:
    """Check if the Claude Agent SDK is available."""
    if os.environ.get("SUPERHARNESS_FORCE_NO_SDK"):
        return False
    return _try_import_sdk()


class SDKRunner:
    """Agent SDK runner — executes prompts via claude_agent_sdk.

    Uses query() for dispatch. Tracks tokens, cost, and enforces budget.
    """

    def __init__(
        self,
        project_dir: Path,
        model: str | None = None,
        max_budget_usd: float | None = None,
        warm_start: bool = True,
    ) -> None:
        if not _try_import_sdk():
            raise RuntimeError(
                "claude_agent_sdk is not available. "
                "Install it with: pip install claude-agent-sdk"
            )
        self.project_dir = project_dir
        self.model = model
        self.max_budget_usd = max_budget_usd
        self.warm_start = warm_start
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    def run(
        self,
        prompt: str,
        log_file: Path | None = None,
    ) -> dict[str, Any]:
        """Execute a prompt via the SDK query() function.

        Args:
            prompt: Prompt to execute
            log_file: Optional path to write streaming output to

        Returns:
            Dict with keys: output, input_tokens, output_tokens, cost_usd

        Raises:
            BudgetExceededError: If max_budget_usd exceeded
        """
        from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, StreamEvent

        options = ClaudeAgentOptions()
        if self.model:
            options.model = self.model
        options.cwd = str(self.project_dir)
        options.permission_mode = "bypassPermissions"
        # Inherit user + project settings (MCP servers like tilth/Serena, hooks like RTK)
        options.setting_sources = ["user", "project"]

        # Warm start: fork the most recent session to inherit codebase context
        if self.warm_start:
            session_id = _find_latest_session(str(self.project_dir))
            if session_id:
                options.resume = session_id
                options.fork_session = True
                logger.info("Warm start: forking session %s", session_id)

        log_handle = None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_file, "a", encoding="utf-8")

        output_text = ""
        input_tokens = 0
        output_tokens = 0

        # JSONL tailer: streams assistant text from the SDK session file to the log
        tailer_stop = None
        tailer_thread = None
        if log_handle:
            tailer_stop, tailer_thread = _start_jsonl_tailer(
                str(self.project_dir), log_handle,
            )

        async def _run() -> str:
            nonlocal input_tokens, output_tokens
            text_parts: list[str] = []
            result_text = ""
            async for event in query(prompt=prompt, options=options):
                if isinstance(event, ResultMessage):
                    result_text = event.result or ""
                    if event.usage:
                        usage = event.usage if isinstance(event.usage, dict) else vars(event.usage) if hasattr(event.usage, '__dict__') else {}
                        input_tokens += usage.get("input_tokens", 0)
                        output_tokens += usage.get("output_tokens", 0)
            return result_text or "".join(text_parts)

        try:
            output_text = asyncio.run(_run())
        finally:
            if tailer_stop is not None:
                tailer_stop.set()
            if tailer_thread is not None:
                tailer_thread.join(timeout=2)
            if log_handle:
                log_handle.close()

        # Track cost
        run_cost = _calculate_cost(self.model, input_tokens, output_tokens)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += run_cost

        if self.max_budget_usd is not None and self.total_cost_usd > self.max_budget_usd:
            raise BudgetExceededError(
                f"Budget exceeded: ${self.total_cost_usd:.4f} > ${self.max_budget_usd:.4f}"
            )

        return {
            "output": output_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": run_cost,
        }

    def reset_session(self) -> None:
        """Reset token/cost tracking."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
