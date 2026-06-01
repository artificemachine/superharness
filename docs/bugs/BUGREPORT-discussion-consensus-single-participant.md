# BUGREPORT: Discussion consensus reached with only 1 of 3 participants

> **Project:** superharness (discussion engine)
> **Discovered:** 2026-06-01, trayzury discussion "How can we improve the reinforcement loop?"
> **Severity:** HIGH — undermines the multi-agent consensus guarantee
> **Reproducible:** Yes — start discussion when other agents have no daemon

---

## Summary

A 3-participant discussion (claude-code, codex-cli, gemini-cli) reached "consensus" with only **one real submission** (claude-code). The other two participants never submitted — their daemons weren't running. The summary file shows `codex-cli: agree or disagree or partial` as a default/empty value, and gemini-cli doesn't even appear.

## Root Causes (2 independent failures)

### 1. Single contract task per discussion, inbox items don't create contract tasks

In `discuss.py`, `cmd_start()` (line 256-266):

```python
round_task_owner = next((p for p in participants if p in VALID_OWNERS), participants[0])
subprocess.run(
    [sys.executable, "-m", "superharness.commands.task", "create",
     "--id", round_task_id,
     "--owner", round_task_owner,     # ← ONLY ONE owner
     ...],
)
```

Only ONE contract task is created, assigned to the first AI agent in `VALID_OWNERS` (which is `claude-code`). The other participants (codex-cli, gemini-cli) get **inbox items** (line 311-320) but **no contract tasks**. This means:

- `shux contract` shows only `claude-code` as the task owner
- Other agents' submissions aren't tracked as contract tasks
- The discussion's progress depends entirely on inbox item dispatch, not contract state

### 2. Fast-close accepts 1 submission when other agents have no daemon

In `inbox_watch.py`, `_gc_discussion_deadlock()` (lines 3704-3741):

```python
participants = json.loads(disc.owners)
total_participants = len(participants)  # 3
required = max(2, total_participants - 1)  # = max(2, 2) = 2

if submitted >= required:
    continue  # normal advance — needs 2

# Fast-close: if all missing agents have no daemon heartbeat
all_daemon_dead = True
for agent in missing_agents:
    hb = conn.execute("SELECT status FROM agent_heartbeats WHERE agent=?", ...)
    if hb and hb["status"] not in ("zombie", None):
        all_daemon_dead = False
        break

if all_daemon_dead and submitted >= 1:  # ← ACCEPTS 1 SUBMISSION
    conn.execute(
        "UPDATE discussions SET status='failed_participant', ...")
```

When other agents have no daemon heartbeat AND at least 1 agent submitted, the discussion auto-closes as `failed_participant`. But this can produce a misleading "consensus" verdict when only one real submission exists.

### Evidence from the trayzury discussion

```
summary.yaml:
  claude-code: consensus              ← real submission (us)
  codex-cli: agree or disagree or partial  ← DEFAULT/EMPTY, not a real submission
  gemini-cli: (not even listed)       ← never responded
```

The `codex-cli` entry appears to be a fallback string, not an actual agent response. The gemini-cli entry is completely missing.

## Impact

- Discussions can reach "consensus" with only 1 of N participants actually voting
- The summary misleadingly attributes positions to agents that never responded
- `shux status` reports `consensus=1` when the discussion should be `failed_participant`
- Users trust the multi-agent review process but get single-agent results

## Fix Priority

| # | Fix | Effort | Impact |
|---|-----|:---:|---|
| 1 | Don't label as "consensus" when < required submissions received | S | Prevents misleading verdicts |
| 2 | Create contract tasks for ALL participants, not just the first | M | Proper tracking per-agent |
| 3 | Require `submitted >= required` before allowing fast-close, even with dead daemons | S | Closes the 1-submission gap |
| 4 | Don't write fallback/default agent positions to summary when agent didn't submit | S | Prevents fake entries in summary |

## Related

- `docs/bugs/BUGREPORT-watcher-silent-death-no-recovery.md` — the watcher outage that triggered this
- `superharness/commands/discuss.py` line 256 — single-owner contract task
- `superharness/commands/inbox_watch.py` line 3719-3741 — fast-close with 1 submission
- `superharness/commands/status.py` line 231 — `--fix` marks N-1 participants as stale
