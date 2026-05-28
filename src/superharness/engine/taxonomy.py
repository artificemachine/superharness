VALID_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

EFFORT_ORDER: list[str] = list(VALID_EFFORTS)

EFFORT_TO_TIER_VERSION: dict[str, tuple[str, str]] = {
    "low":    ("standard", "*"),
    "medium": ("standard", "*"),
    "high":   ("standard", "*"),
    "xhigh":  ("max",      "*"),
    "max":    ("max",      "*"),
}

DEFAULT_MODEL_PER_EFFORT: dict[str, str] = {
    "low":    "claude-sonnet-4-6",
    "medium": "claude-sonnet-4-6",
    "high":   "claude-sonnet-4-6",
    "xhigh":  "claude-opus-4-8",
    "max":    "claude-opus-4-8",
}

DEFAULT_TIMEOUT_PER_EFFORT: dict[str, int] = {
    "low":    10,
    "medium": 15,
    "high":   20,
    "xhigh":  25,
    "max":    30,
}

OPUS_KEYWORDS: frozenset[str] = frozenset({
    "oauth",
    "migration",
    "security audit",
    "architecture",
    "irreversible",
    "compliance",
    "gdpr",
    "hipaa",
    "iec 62304",
    "schema migration",
    "crypto",
    "auth design",
    "post-mortem",
})

# Token threshold above which effort=max auto-promotes to the max-1m tier.
# Based on Anthropic's 1M context beta: pricing is ~2× input / 1.5× output
# for prompts beyond 200K tokens. Auto-promotion is max-effort-only to prevent
# silent budget blowouts on lower-effort tasks.
_1M_TOKEN_THRESHOLD = 200_000


def should_use_1m_context(
    effort: str,
    estimated_input_tokens: int,
    context_1m: bool = False,
) -> bool:
    """Return True when the task should use the max-1m (1M context) tier.

    Three triggers (all require effort="max"):
    - Auto: estimated_input_tokens > 200_000
    - Operator pin: context_1m=True
    Only fires when effort == "max"; all other efforts return False.
    """
    if effort != "max":
        return False
    if context_1m:
        return True
    return estimated_input_tokens > _1M_TOKEN_THRESHOLD
