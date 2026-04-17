VALID_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

EFFORT_ORDER: list[str] = list(VALID_EFFORTS)

EFFORT_TO_TIER_VERSION: dict[str, tuple[str, str]] = {
    "low":    ("standard", "*"),
    "medium": ("standard", "*"),
    "high":   ("standard", "*"),
    "xhigh":  ("max",      "4.6"),
    "max":    ("max",      "*"),
}

DEFAULT_MODEL_PER_EFFORT: dict[str, str] = {
    "low":    "claude-sonnet-4-6",
    "medium": "claude-sonnet-4-6",
    "high":   "claude-sonnet-4-6",
    "xhigh":  "claude-opus-4-6",
    "max":    "claude-opus-4-7",
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
