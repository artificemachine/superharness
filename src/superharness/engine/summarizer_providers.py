"""External summarizer providers.

Anthropic, Gemini, OpenAI, OpenRouter, OpenCode. Each self-registers
into `summarizer._REGISTRY` at import time. HTTP transport uses stdlib
`urllib.request` to avoid pinning provider SDKs. OpenCode invokes the
local `opencode` CLI via subprocess.

Construction raises `SummarizerError` when credentials or the
required binary are missing. Transport faults raise `SummarizerError`
as well; the auto-capture caller in `engine.observation_capture`
catches every exception and returns None, so a provider fault
silently skips that snapshot without breaking the lifecycle transition.

Design notes:
- A small `_http_post_json()` helper centralises HTTP so tests can
  monkey-patch it once instead of patching `urllib.request.urlopen`
  per provider.
- `ChatCompletionsSummarizer` is shared between OpenAI and OpenRouter
  (both speak the OpenAI-compatible chat-completions shape).
- OpenCode is experimental: the subprocess shape is slow (~500ms-1s
  startup) and parses stdout. Tag is in `init_kwargs` so the operator
  can flip the invocation if their OpenCode version differs.

Default models are conservative cost-tier picks. Override per-provider
with `init_kwargs={"model": "..."}` in the registry, or via your own
`register_summarizer()` call.

Prompt template lives at module level so all providers share it; this
also makes the smoke test cheaper because every provider summarises
the same fixture context.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any

from superharness.engine.summarizer import (
    SummarizerConfig,
    SummarizerError,
    register_summarizer,
)
from superharness.utils.privacy import strip_private_tags


_DEFAULT_TIMEOUT_S = 30
_DEFAULT_MAX_TOKENS = 256
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _build_prompt(context: dict[str, Any]) -> str:
    """Compose the summarisation prompt from a task context dict."""
    task_id = context.get("task_id") or "unknown"
    phase = context.get("phase") or "unknown"
    title = context.get("title") or ""
    outcome = context.get("outcome") or ""
    from_agent = context.get("from_agent") or ""

    parts = [
        "Summarise this completed task in 2 to 3 sentences for cross-session continuity.",
        "Focus on: what was done, key decisions, anything an agent picking this up next should know.",
        "Do not invent facts. Do not include private credentials. No preamble.",
        "",
        f"task_id: {task_id}",
        f"phase: {phase}",
    ]
    if title:
        parts.append(f"title: {title}")
    if from_agent:
        parts.append(f"by: {from_agent}")
    if outcome:
        parts.append("outcome:")
        parts.append(outcome)
    return "\n".join(parts)


def _http_post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Stdlib HTTPS POST with JSON request/response. Centralised for tests."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise SummarizerError(f"HTTP {e.code} from {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise SummarizerError(f"network error to {url}: {e}") from e
    except (ValueError, json.JSONDecodeError) as e:
        raise SummarizerError(f"invalid JSON response from {url}: {e}") from e


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class AnthropicSummarizer:
    DEFAULT_MODEL = "claude-haiku-4-5-20251001"
    API_URL = "https://api.anthropic.com/v1/messages"
    API_KEY_ENV = "ANTHROPIC_API_KEY"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        key = os.environ.get(self.API_KEY_ENV)
        if not key:
            raise SummarizerError(f"{self.API_KEY_ENV} not set")
        self.api_key = key
        self.last_usage: dict[str, Any] = {}

    def summarize(self, context: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": _build_prompt(context)}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = _http_post_json(self.API_URL, body, headers)
        usage = payload.get("usage") or {}
        self.last_usage = {
            "model": self.model,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
        content = payload.get("content") or []
        text = ""
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text") or ""
        return strip_private_tags(text)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class GeminiSummarizer:
    DEFAULT_MODEL = "gemini-2.0-flash"
    API_URL_TEMPLATE = (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    )

    def __init__(self, model: str | None = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise SummarizerError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
        self.api_key = key
        self.last_usage: dict[str, Any] = {}

    def summarize(self, context: dict[str, Any]) -> str:
        url = self.API_URL_TEMPLATE.format(model=self.model, key=self.api_key)
        body = {
            "contents": [{"parts": [{"text": _build_prompt(context)}]}],
            "generationConfig": {"maxOutputTokens": _DEFAULT_MAX_TOKENS},
        }
        headers = {"Content-Type": "application/json"}
        payload = _http_post_json(url, body, headers)
        meta = payload.get("usageMetadata") or {}
        self.last_usage = {
            "model": self.model,
            "input_tokens": meta.get("promptTokenCount"),
            "output_tokens": meta.get("candidatesTokenCount"),
        }
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            text = ""
        return strip_private_tags(text or "")


# ---------------------------------------------------------------------------
# OpenAI-compatible (OpenAI + OpenRouter share the chat-completions shape)
# ---------------------------------------------------------------------------

class ChatCompletionsSummarizer:
    """Shared base for OpenAI-compatible chat-completions endpoints."""
    BASE_URL = ""  # override
    DEFAULT_MODEL = ""  # override
    API_KEY_ENV = ""  # override
    DISPLAY_NAME = ""  # override

    def __init__(self, model: str | None = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        key = os.environ.get(self.API_KEY_ENV)
        if not key:
            raise SummarizerError(f"{self.API_KEY_ENV} not set")
        self.api_key = key
        self.last_usage: dict[str, Any] = {}

    def summarize(self, context: dict[str, Any]) -> str:
        url = f"{self.BASE_URL.rstrip('/')}/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": _build_prompt(context)}],
            "max_tokens": _DEFAULT_MAX_TOKENS,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = _http_post_json(url, body, headers)
        usage = payload.get("usage") or {}
        self.last_usage = {
            "model": self.model,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
        text = ""
        choices = payload.get("choices") or []
        if choices and isinstance(choices, list):
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                text = msg.get("content") or ""
        return strip_private_tags(text)


class OpenAISummarizer(ChatCompletionsSummarizer):
    BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini"
    API_KEY_ENV = "OPENAI_API_KEY"
    DISPLAY_NAME = "openai"


class OpenRouterSummarizer(ChatCompletionsSummarizer):
    BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
    API_KEY_ENV = "OPENROUTER_API_KEY"
    DISPLAY_NAME = "openrouter"


# ---------------------------------------------------------------------------
# CLI-based summarizers (experimental: subprocess shape, slower)
# ---------------------------------------------------------------------------

class _CLISummarizer:
    """Shared base for summarizers that subprocess a local CLI.

    Subclasses override DEFAULT_BINARY and DEFAULT_SUBCOMMAND. Subprocess
    startup overhead (typically ~500ms-1.5s) plus stdout parsing make
    these slower and more brittle than HTTP providers, but they let
    you reuse whatever authentication the local CLI already has
    (DeepSeek/Claude/etc) without putting a separate API key in env.

    Constructed-time refusal when the binary is not on PATH. Strips
    ANSI escapes from stdout before returning.
    """

    DEFAULT_BINARY = ""
    DEFAULT_SUBCOMMAND: tuple[str, ...] = ()
    DEFAULT_TIMEOUT_S = 60

    def __init__(
        self,
        model: str | None = None,
        binary: str | None = None,
        subcommand: tuple[str, ...] | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self.model = model
        self.binary = binary or self.DEFAULT_BINARY
        self.subcommand = tuple(subcommand if subcommand is not None else self.DEFAULT_SUBCOMMAND)
        self.timeout_s = timeout_s if timeout_s is not None else self.DEFAULT_TIMEOUT_S
        if not shutil.which(self.binary):
            raise SummarizerError(f"{self.binary!r} not found in PATH")

    def summarize(self, context: dict[str, Any]) -> str:
        prompt = _build_prompt(context)
        args: list[str] = [self.binary, *self.subcommand, prompt]
        if self.model:
            args.extend(["--model", self.model])
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise SummarizerError(f"{self.binary} timed out after {self.timeout_s}s") from e
        except OSError as e:
            raise SummarizerError(f"{self.binary} invocation failed: {e}") from e
        if result.returncode != 0:
            tail = (result.stderr or "")[:200]
            raise SummarizerError(
                f"{self.binary} exit {result.returncode}: {tail}"
            )
        return strip_private_tags(_ANSI_RE.sub("", result.stdout).strip())


class OpenCodeSummarizer(_CLISummarizer):
    """Invoke the local `opencode` CLI for summarisation.

    Inherits whatever provider OpenCode is configured for (often
    DeepSeek, OpenRouter, or a local model). No separate API key
    needed in env; uses OpenCode's existing auth.

    Default invocation: `opencode run <prompt>`. Override via `binary`
    and `subcommand` kwargs if your OpenCode version differs.
    """

    DEFAULT_BINARY = "opencode"
    DEFAULT_SUBCOMMAND = ("run",)


class ClaudeCodeSummarizer(_CLISummarizer):
    """Invoke the local `claude` CLI for summarisation.

    Reuses whatever authentication Claude Code is configured with
    (Claude Max OAuth, or ANTHROPIC_API_KEY if set). Gets you Claude
    summaries without putting a separate API key in env.

    Default invocation: `claude -p <prompt>` (non-interactive print
    mode). Override via `binary` and `subcommand` kwargs.
    """

    DEFAULT_BINARY = "claude"
    DEFAULT_SUBCOMMAND = ("-p",)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_summarizer(
    "anthropic",
    SummarizerConfig(provider_class=AnthropicSummarizer, max_per_hour=60),
)
register_summarizer(
    "gemini",
    SummarizerConfig(provider_class=GeminiSummarizer, max_per_hour=60),
)
register_summarizer(
    "openai",
    SummarizerConfig(provider_class=OpenAISummarizer, max_per_hour=60),
)
register_summarizer(
    "openrouter",
    SummarizerConfig(provider_class=OpenRouterSummarizer, max_per_hour=60),
)
register_summarizer(
    "opencode",
    SummarizerConfig(provider_class=OpenCodeSummarizer, max_per_hour=30),
)
register_summarizer(
    "claude-code",
    SummarizerConfig(provider_class=ClaudeCodeSummarizer, max_per_hour=30),
)
