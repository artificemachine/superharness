# Handoff — superharness v1.47.4 (2026-05-06)

> Branch: `main`
> Latest local: v1.47.4 (not yet shipped — ready to `/ship`)
> Last published: v1.47.1 on PyPI
> Installed locally (pipx): v1.47.1

## Session summary

Fixed a cascade of dispatch bugs that surfaced after the v1.47.0 opencode adapter landed and the cross-agent discussion infrastructure started actually working. Ran a full cross-agent discussion on `docs/ARCH-superharness-maintainability-refactor.md` — all 4 agents (claude-code, codex-cli, gemini-cli, opencode via DeepSeek V4 Pro) filed round-1 submissions with unanimous consensus. Each bug fix was TDD: test first, fix second, regression test added to `tests/unit/test_adapter_polish.py`.

## What is uncommitted and ready to ship

| Version | Files changed | Fix |
|---------|---------------|-----|
| v1.47.2 | `inbox_dispatch.py` | Discussion reconciler checked contract task status — discussions have no contract entry so it always fell to "failed". Now checks submission YAML on disk (`discussions/<id>/<round>-<agent>.yaml`). Claude-code, codex-cli, and gemini-cli all had successful submissions falsely labelled failed. |
| v1.47.3 | `inbox_watch.py`, `adapter_manifests/opencode.yaml` | Watcher `"both"` target hardcoded `["claude-code", "codex-cli", "gemini-cli"]` — opencode inbox items were never dispatched. Fixed by calling `list_adapters()`. Also fixed `_cancel_undispatchable_agents` to use registry as primary source. OpenCode manifest updated from Anthropic (not configured on this machine) to DeepSeek V4 Pro. |
| v1.47.4 | `inbox_watch.py` | `inbox_watch.py:2033` indentation bug: paused dead-pid reconciler was nested inside the `except` block of `_analyze_task_logs` — it only ran when the log analyzer threw. Fixed with standalone `try/except`. Flagged by gemini-cli + opencode in the discussion. |

All changes have regression tests. 10 tests in `tests/unit/test_adapter_polish.py`, all pass.

## State: cross-agent discussion

Discussion `discuss-20260506T135220Z-50383-232040761` — **round 1 complete, 4/4 submissions on disk**.

Inbox status shows `failed` (false-failed — fixed in v1.47.2, but the fix wasn't installed when they ran). Submissions are real and complete at `.superharness/discussions/discuss-20260506T135220Z-50383-232040761/`.

**Round 1 consensus (unanimous across all 4 agents):**

1. **Unify `_launch_agent()` in `delegate.py`** with `resolve_launcher()`. Watcher path is already manifest-driven via `adapter_registry.resolve_launcher()`; direct CLI dispatch still uses a hardcoded if/elif chain (claude-code → gemini-cli → opencode → else codex-cli). Model prefix transform (`anthropic/`, `openai/`, `google/`) should move to a shared utility callable by both paths. Scope: ~90 lines in `_launch_agent` + shared utility.

2. **Decompose `_do_dispatch()` in `inbox_dispatch.py`** into 4 staged units: claim_item → prepare_dispatch_context → run_launcher → record_outcome. Currently ~425 lines with 8+ interleaved concerns. 3 consecutive patch releases (v1.46.5, v1.47.0, v1.47.1) concentrated bugs here.

**Also flagged by opencode (new finding):** `auto_dispatch.py:20` has `_VALID_AGENTS = ("claude-code", "codex-cli")` missing gemini-cli and opencode. `auto_dispatch._classify_task()` has its own hardcoded agent mapping (mini→codex-cli, standard/max→claude-code) — also missing gemini-cli and opencode. Both should be fixed as part of the adapter unification sprint.

**Deferred (all 4 agents disagree):** SQLite/YAML unification, dashboard monolith split, inbox_watch.py full split.

## What to do next session

1. **Run `/ship`** — commits v1.47.2–v1.47.4, opens PR, merges, tags, publishes to PyPI.

2. **Start the adapter unification sprint** (two tracked tasks, sequential):
   - Task A: Unify `_launch_agent()` in `delegate.py` + fix `auto_dispatch.py` hardcoded agents
   - Task B: Decompose `_do_dispatch()` into 4 stages

3. Optionally start **round 2** of the discussion after task A lands to get agent feedback on the decomposition design before implementing task B.

## Key files changed this session

| File | Change |
|------|--------|
| `src/superharness/commands/inbox_dispatch.py` | v1.47.2: submission-YAML reconcile for discussion rounds |
| `src/superharness/commands/inbox_watch.py` | v1.47.3: `list_adapters()` in "both" target + `_cancel_undispatchable_agents` registry fix; v1.47.4: indentation bug fixed |
| `src/superharness/adapter_manifests/opencode.yaml` | v1.47.3: DeepSeek V4 Pro model tiers (Anthropic not configured in opencode) |
| `tests/unit/test_adapter_polish.py` | 10 regression tests covering bugs 1–5 |
| `CHANGELOG.md` | Entries for v1.47.2, v1.47.3, v1.47.4 |

## Known remaining issues

- `auto_dispatch.py` hardcoded `_VALID_AGENTS` and `_classify_task()` agent mapping — tracked for next sprint.
- Watcher lock hash differs between Python environments (pyenv 3.11 vs pipx homebrew 3.14) — two processes can each believe they hold the lock for the same project. Short-term: manual cleanup. Long-term: normalize to `os.path.realpath()` in `watcher_lock_path()`.
- `find_tier_for_model` import warning in dispatch log — non-blocking.

## Quick setup for next session

```bash
cd ~/DevOpsSec/superharness
shux daemon stop --project .
pipx upgrade superharness          # should install v1.47.4 after shipping
shux --version                     # verify 1.47.4
pytest tests/unit/test_adapter_polish.py -q  # should be 10 passed
```

## Previous roadmap items (from v1.44.18 handoff)

Still relevant — deferred during the dispatch/adapter sprint:

- **PR #2-B**: split-brain test fixtures (20 tests in `test_task_workflow_v2_phase1.py` + `test_task_failed_reason.py`)
- **PR #2-C**: reconciler bugs (`_reconcile_zombies` never defined, `zombie_reconcile.py` missing)
- **PR #3-B**: ancillary commands YAML→SQLite (`onboard.py`, `inbox_watch.py` contract mutations, `handoff_write.py`, `recap.py`, `preflight.py`, `recall.py`)
