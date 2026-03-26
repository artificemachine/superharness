# Task Complete: Agent SDK Runner (feat.sdk-runner)

**Task ID:** feat.sdk-runner
**Title:** Agent SDK runner: replace subprocess claude CLI with Python SDK
**Owner:** claude-code
**Status:** done
**Date:** 2026-03-20T20:30:00Z

---

## Executive Summary

The Agent SDK runner is **complete and verified**. All acceptance criteria exceeded:
- ✅ Runner class uses `claude_agent_sdk.Agent` instead of subprocess
- ✅ 18 tests pass (requirement: 5 tests minimum)
- ✅ Additional features delivered: streaming, session persistence, budget guard

---

## What Was Built

### Core Implementation
**File:** `src/superharness/engine/sdk_runner.py` (238 lines)

**Key Classes:**
- `SDKRunner` — wrapper around `claude_agent_sdk.Agent`
- `BudgetExceededError` — raised when max_budget_usd exceeded

**Key Functions:**
- `sdk_available()` — check if SDK is installed
- `_create_agent()` — create configured Agent instance
- `_calculate_cost()` — calculate USD cost from token usage

### SDKRunner API

```python
runner = SDKRunner(
    project_dir=Path("/path/to/project"),
    model="claude-sonnet-4-6",         # optional
    max_budget_usd=5.0,                # optional
)

# Execute a prompt (session persists across calls)
result = runner.run(
    prompt="Fix the bug in main.py",
    log_file=Path("logs/task.log"),    # optional streaming
)

# Reset conversation and start fresh
runner.reset_session()
```

### Features Delivered

#### 1. Basic SDK Runner (5 tests)
- Wraps `claude_agent_sdk.Agent` instead of subprocess calls
- Accepts `model` parameter for model selection
- Raises `RuntimeError` if SDK not available
- Detection via `sdk_available()` function

#### 2. Streaming Support (5 tests)
- Optional `log_file` parameter on `run()`
- Streams output via `on_event` handler
- Real-time write (flush after each event)
- Creates log directory if missing
- Graceful fallback if SDK doesn't support streaming

#### 3. Session Persistence (5 tests)
- Agent instance created on first `run()`, reused for subsequent calls
- Conversation history automatically maintained by SDK
- No need for `--resume` flag
- `reset_session()` discards agent and starts fresh

#### 4. Budget Guard (3 tests)
- Tracks `total_input_tokens`, `total_output_tokens`, `total_cost_usd`
- Accumulates cost across multiple `run()` calls
- Raises `BudgetExceededError` when `max_budget_usd` exceeded
- Model pricing table for accurate cost calculation

---

## Test Results

**File:** `tests/unit/test_sdk_runner.py` (436 lines, 18 tests)

```bash
pytest tests/unit/test_sdk_runner.py -v
# ============================= test session starts ==============================
# tests/unit/test_sdk_runner.py::TestSDKRunner::test_sdk_available_returns_true_when_sdk_installed PASSED
# tests/unit/test_sdk_runner.py::TestSDKRunner::test_sdk_available_returns_false_when_sdk_missing PASSED
# tests/unit/test_sdk_runner.py::TestSDKRunner::test_runner_run_executes_prompt_via_sdk PASSED
# tests/unit/test_sdk_runner.py::TestSDKRunner::test_runner_uses_model_override_if_provided PASSED
# tests/unit/test_sdk_runner.py::TestSDKRunner::test_runner_raises_runtime_error_if_sdk_unavailable PASSED
# tests/unit/test_sdk_runner.py::TestSDKStreaming::test_runner_streams_to_log_file_when_provided PASSED
# tests/unit/test_sdk_runner.py::TestSDKStreaming::test_runner_streams_to_log_file_in_real_time PASSED
# tests/unit/test_sdk_runner.py::TestSDKStreaming::test_runner_creates_log_directory_if_missing PASSED
# tests/unit/test_sdk_runner.py::TestSDKStreaming::test_runner_handles_missing_on_event_gracefully PASSED
# tests/unit/test_sdk_runner.py::TestSDKStreaming::test_runner_without_log_file_works_as_before PASSED
# tests/unit/test_sdk_runner.py::TestSDKSession::test_multiple_run_calls_reuse_same_agent PASSED
# tests/unit/test_sdk_runner.py::TestSDKSession::test_multiple_run_calls_share_conversation_context PASSED
# tests/unit/test_sdk_runner.py::TestSDKSession::test_new_runner_instance_creates_new_agent PASSED
# tests/unit/test_sdk_runner.py::TestSDKSession::test_session_persists_across_log_file_and_non_log_calls PASSED
# tests/unit/test_sdk_runner.py::TestSDKSession::test_reset_session_clears_conversation_context PASSED
# tests/unit/test_sdk_runner.py::TestSDKBudgetGuard::test_runner_tracks_tokens_and_cost_from_sdk_response PASSED
# tests/unit/test_sdk_runner.py::TestSDKBudgetGuard::test_runner_accumulates_cost_across_multiple_runs PASSED
# tests/unit/test_sdk_runner.py::TestSDKBudgetGuard::test_runner_raises_budget_exceeded_when_limit_hit PASSED
# ============================== 18 passed in 0.18s ===============================
```

---

## Architecture Decisions

### 1. Agent Instance Lifecycle
**Decision:** Create Agent on first `run()`, reuse for all subsequent calls in same runner instance.

**Rationale:**
- SDK maintains conversation history automatically
- No need for manual session management
- Matches expected behavior of interactive agents
- Reduces API overhead (no re-authentication per call)

**Trade-offs:**
- Session persists indefinitely until `reset_session()` called
- Memory grows with conversation history
- Acceptable for bounded task execution scenarios

### 2. Streaming Implementation
**Decision:** Optional `log_file` parameter with `on_event` handler.

**Rationale:**
- Non-breaking change (log_file is optional)
- Real-time streaming critical for live task logs (feat.live-task-log)
- Graceful fallback if SDK doesn't support `on_event`

**Trade-offs:**
- Requires file I/O on every event
- Flush after each write (performance cost)
- Acceptable for human-readable logs, not high-volume

### 3. Budget Guard
**Decision:** Track cost in runner, raise exception when exceeded.

**Rationale:**
- Prevents runaway costs in long-running agents
- Fail-fast prevents partial work + unexpected bill
- Per-runner budget (not global) for task isolation

**Trade-offs:**
- Cost calculation relies on hardcoded pricing table
- Must be updated when Anthropic changes pricing
- No warning before hitting limit (hard stop)

---

## Known Limitations

1. **No SDK installation check** — Runner raises `RuntimeError` if SDK missing, but doesn't guide user to install
   - Mitigation: Clear error message with install command

2. **Cost calculation hardcoded** — Model pricing table will become stale
   - Mitigation: Document pricing source and update date

3. **No streaming backpressure** — Log file writes block event handler
   - Mitigation: Acceptable for human-readable logs

4. **No token usage estimate** — Can't predict if budget will be exceeded before run
   - Mitigation: User sets conservative max_budget_usd

---

## Integration Points

### Downstream Dependencies Unblocked
1. **feat.sdk-delegate** (blocked: requires this runner)
   - Can now dispatch tasks via SDK instead of CLI subprocess
   - Use `SDKRunner` in delegate.py when `--via sdk` flag set

2. **feat.sdk-streaming** (already complete — merged into this task)
   - Streaming implemented via `log_file` parameter

3. **feat.sdk-session** (already complete — merged into this task)
   - Session persistence implemented via Agent reuse

### Upstream Dependencies (none)
- This task had no blockers
- Standalone implementation, no contract or module system dependency

---

## Files Changed

```
src/superharness/engine/sdk_runner.py        (created, 238 lines)
tests/unit/test_sdk_runner.py                (created, 436 lines)
```

---

## Usage Example

```python
from pathlib import Path
from superharness.engine.sdk_runner import SDKRunner, BudgetExceededError, sdk_available

# Check if SDK is available before creating runner
if not sdk_available():
    print("claude_agent_sdk not installed. Install with: pip install claude-agent-sdk")
    exit(1)

# Create runner with budget guard
runner = SDKRunner(
    project_dir=Path("/Users/airm2max/DevOpsSec/myproject"),
    model="claude-sonnet-4-6",
    max_budget_usd=2.0,
)

try:
    # Run first prompt (creates Agent, starts conversation)
    result1 = runner.run(
        prompt="Read the README and list all features",
        log_file=Path("logs/task1.log"),  # optional streaming
    )
    print(f"Result: {result1['content']}")
    print(f"Cost so far: ${runner.total_cost_usd:.4f}")

    # Run follow-up prompt (reuses Agent, maintains context)
    result2 = runner.run(
        prompt="Which feature should we implement first?",
    )
    print(f"Result: {result2['content']}")
    print(f"Total cost: ${runner.total_cost_usd:.4f}")

except BudgetExceededError as e:
    print(f"Budget limit hit: {e}")
    print(f"Spent: ${runner.total_cost_usd:.4f}")
```

---

## Verification Commands

```bash
# Run all SDK runner tests
pytest tests/unit/test_sdk_runner.py -v

# Run specific test class
pytest tests/unit/test_sdk_runner.py::TestSDKBudgetGuard -v

# Check SDK availability in Python
python3 -c "from superharness.engine.sdk_runner import sdk_available; print(sdk_available())"
```

---

## Next Steps

### Recommended: feat.sdk-delegate
Now that the SDK runner is complete, the next logical task is **feat.sdk-delegate**:
- Add `--via sdk` flag to `shux delegate`
- Use `SDKRunner` instead of subprocess when flag set
- Fall back to CLI if SDK unavailable

**Why now?**
- Unblocks real-world usage of SDK runner
- Validates streaming and session persistence in production
- Dependency chain: this task → feat.sdk-delegate → feat.sdk-streaming (complete)

### Alternative: Integration Tests
Before moving to feat.sdk-delegate, consider adding integration tests:
- Test with real claude_agent_sdk (not mocked)
- Verify streaming to actual log files
- Test budget guard with real API calls (small prompts)

---

## Questions for Owner

None. Task is complete and all acceptance criteria exceeded.

---

## Session Metadata

**Contract ID:** initial-setup
**Actor:** claude-code
**Session duration:** <1 minute (verification + protocol update)
**Context source:** `.superharness/handoffs/feat.sdk-runner-instructions.md`

---

**End of handoff — ready for owner review or next task assignment.**
