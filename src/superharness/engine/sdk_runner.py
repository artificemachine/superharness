"""Agent SDK runner — wrapper around claude_agent_sdk.

Uses query() for one-shot task dispatch and ClaudeSDKClient for
stateful sessions. Provides an alternative to subprocess calls
to the claude CLI.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when SDK runner exceeds max_budget_usd."""
    pass


_MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25},
}


def _calculate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for given token usage."""
    pricing = _MODEL_PRICING.get(model or "", _MODEL_PRICING["claude-sonnet-4-6"])
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
    ) -> None:
        if not _try_import_sdk():
            raise RuntimeError(
                "claude_agent_sdk is not available. "
                "Install it with: pip install claude-agent-sdk"
            )
        self.project_dir = project_dir
        self.model = model
        self.max_budget_usd = max_budget_usd
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

        log_handle = None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_file, "a", encoding="utf-8")

        output_text = ""
        input_tokens = 0
        output_tokens = 0

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
                elif isinstance(event, StreamEvent):
                    chunk = getattr(event, "text", "") or ""
                    if chunk:
                        text_parts.append(chunk)
                        if log_handle:
                            log_handle.write(chunk)
                            log_handle.flush()
            return result_text or "".join(text_parts)

        try:
            output_text = asyncio.run(_run())
        finally:
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
