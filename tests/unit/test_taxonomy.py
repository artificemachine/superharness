from superharness.engine.taxonomy import (
    VALID_EFFORTS,
    EFFORT_ORDER,
    EFFORT_TO_TIER_VERSION,
    DEFAULT_MODEL_PER_EFFORT,
    DEFAULT_TIMEOUT_PER_EFFORT,
    OPUS_KEYWORDS,
)


def test_valid_efforts_tuple():
    assert VALID_EFFORTS == ("low", "medium", "high", "xhigh", "max")


def test_effort_order_list():
    assert EFFORT_ORDER == ["low", "medium", "high", "xhigh", "max"]


def test_effort_to_tier_version_low():
    assert EFFORT_TO_TIER_VERSION["low"] == ("standard", "*")


def test_effort_to_tier_version_xhigh():
    assert EFFORT_TO_TIER_VERSION["xhigh"] == ("max", "*")


def test_effort_to_tier_version_max():
    assert EFFORT_TO_TIER_VERSION["max"] == ("max", "*")


def test_default_model_low():
    assert DEFAULT_MODEL_PER_EFFORT["low"] == "claude-sonnet-4-6"


def test_default_model_xhigh():
    assert DEFAULT_MODEL_PER_EFFORT["xhigh"] == "claude-opus-4-8"


def test_default_model_max():
    assert DEFAULT_MODEL_PER_EFFORT["max"] == "claude-opus-4-8"


def test_default_timeout_low():
    assert DEFAULT_TIMEOUT_PER_EFFORT["low"] == 10


def test_default_timeout_max():
    assert DEFAULT_TIMEOUT_PER_EFFORT["max"] == 30


def test_opus_keywords_frozenset():
    required = {"oauth", "migration", "security audit", "architecture", "irreversible"}
    assert isinstance(OPUS_KEYWORDS, frozenset)
    assert required.issubset(OPUS_KEYWORDS)


def test_tier_version_keys_equal_valid_efforts():
    assert set(EFFORT_TO_TIER_VERSION.keys()) == set(VALID_EFFORTS)


def test_default_model_keys_equal_valid_efforts():
    assert set(DEFAULT_MODEL_PER_EFFORT.keys()) == set(VALID_EFFORTS)


def test_valid_efforts_single_source():
    from superharness.engine import taxonomy
    from superharness.commands import task, delegate, auto_dispatch
    from superharness.engine import model_router, validate

    assert task.VALID_EFFORTS is taxonomy.VALID_EFFORTS
    assert model_router.VALID_EFFORTS is taxonomy.VALID_EFFORTS
    assert validate._VALID_EFFORTS is taxonomy.VALID_EFFORTS
