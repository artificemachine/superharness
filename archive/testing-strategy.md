# Testing Strategy

## Test Types

### Smoke Test

A quick, shallow check that **basic functionality works at all** — before running deeper tests.

The name comes from hardware: plug it in, turn it on — does it smoke? If yes, stop. If no, proceed to real testing.

**Example:**

```bash
# Does superharness even run?
./superharness --help

# Can it init a project?
./superharness init --project /tmp/test-project

# Does the engine load?
python3 engine/inbox.py --help
```

### Unit Test

Tests **one function or command in isolation**. Fast, no external dependencies.

**Example:**

```python
def test_enqueue_adds_item(tmp_path):
    inbox = tmp_path / "inbox.yaml"
    inbox.write_text("---\n[]")
    result = run(["python3", "engine/inbox.py", "enqueue",
                   "--file", str(inbox), "--id", "test-1",
                   "--to", "codex-cli", "--task", "my-task",
                   "--project", "/tmp", "--priority", "1",
                   "--created-at", "2026-01-01T00:00:00Z"])
    assert result.returncode == 0
    items = yaml.safe_load(inbox.read_text())
    assert len(items) == 1
    assert items[0]["id"] == "test-1"
```

### Integration Test

Tests **multiple components working together**. Slower, may touch filesystem or subprocesses.

**Example:**

```python
def test_enqueue_then_dispatch(tmp_path):
    # Setup project with contract + inbox
    # Enqueue an item via inbox engine
    # Run inbox-dispatch and verify it launches
    # Check inbox status changed to "launched"
```

### End-to-End (E2E) Test

Tests the **full workflow** as a user would experience it. Slowest, exercises the entire system.

**Example:**

```bash
# Full lifecycle: init → create task → enqueue → dispatch → verify
./superharness init --project /tmp/e2e-test
./superharness task create --project /tmp/e2e-test --id test-task --title "Test"
./superharness enqueue --project /tmp/e2e-test --task test-task --to codex-cli
./superharness dispatch --project /tmp/e2e-test --print-only
# Verify prompt was generated correctly
```

## Comparison

| Type | Scope | Speed | Question Answered |
|------|-------|-------|-------------------|
| **Smoke** | Does it start? | Seconds | "Is it completely broken?" |
| **Unit** | One function | Fast | "Does this logic work?" |
| **Integration** | Multiple components | Slower | "Do they work together?" |
| **E2E** | Full workflow | Slowest | "Does the whole thing work?" |

## Test Pyramid

```
        /  E2E  \          Few, slow, high confidence
       /----------\
      / Integration \      Some, medium speed
     /----------------\
    /    Unit tests     \   Many, fast, focused
   /--------------------\
  /    Smoke tests       \  Minimal, instant, sanity check
 /________________________\
```

**Rule of thumb:** more tests at the bottom, fewer at the top. If a smoke test fails, don't bother running anything else.

## Applying to the Migration

Each Python module (M0–M11) should have:

1. **Smoke test** — `python3 engine/<name>.py --help` exits 0
2. **Unit tests** — one test per command, isolated with `tmp_path`
3. **Conformance test** — same input through Ruby and Python, assert identical output
4. **Integration test** — verify the Python module works when called from Bash scripts

Run order: smoke → unit → conformance → integration. Fail fast.
